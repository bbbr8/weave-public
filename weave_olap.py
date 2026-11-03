"""Bounded synthetic integer rollups through the installed native OLAP backend."""
import argparse
import json
import operator
from pathlib import Path
import re
import subprocess
import sys
import time
from weave_verify import digest_json,file_digest,verify

COLUMNS=('entry_id','bucket','amount_units','source_id','origin_id')
MEASURES=('row_count','amount_sum','amount_min','amount_max')


def validate(program):
    if not isinstance(program,dict) or set(program)!={'version','records','dimensions','filters','max_rows','unit'} or program['version']!='weave.olap.integer.v1':raise ValueError('Expected weave.olap.integer.v1')
    records=program['records']
    if not isinstance(records,list) or not 1<=len(records)<=128:raise ValueError('Expected 1..128 source records')
    ids=set();origins={}
    for r in records:
        if not isinstance(r,dict) or set(r)!=set(COLUMNS):raise ValueError('Record fields')
        if not isinstance(r['entry_id'],str) or not re.fullmatch('[a-z][a-z0-9_]{0,31}',r['entry_id']) or r['entry_id'] in ids:raise ValueError('Unique entry identifiers required')
        ids.add(r['entry_id'])
        for name in ['bucket','source_id','origin_id']:
            if not isinstance(r[name],str) or not 1<=len(r[name])<=64:raise ValueError('Bounded source metadata required')
        if r['amount_units'] is not None and (type(r['amount_units']) is not int or abs(r['amount_units'])>10**9):raise ValueError('Integer units bounded to 10^9 or null required')
        if r['source_id'] in origins and origins[r['source_id']]!=r['origin_id']:raise ValueError('Conflicting source origin')
        origins[r['source_id']]=r['origin_id']
    dims=program['dimensions']
    if not isinstance(dims,list) or any(not isinstance(d,str) or d not in ('bucket','origin_id') for d in dims) or len(dims)!=len(set(dims)):raise ValueError('Unique bucket/origin dimensions required')
    if type(program['max_rows']) is not int or not 1<=program['max_rows']<=100:raise ValueError('Row limit 1..100 required')
    if not isinstance(program['unit'],str) or not 1<=len(program['unit'])<=64:raise ValueError('Unit label required')
    if not isinstance(program['filters'],list) or len(program['filters'])>8:raise ValueError('Bounded filters required')
    for f in program['filters']:
        if not isinstance(f,dict) or set(f)!={'column','op','value'} or f['column'] not in COLUMNS or f['op'] not in ('eq','ne','gte','lte','in','is_null','not_null'):raise ValueError('Filter contract')
        if f['op'] in ('gte','lte') and f['column']!='amount_units':raise ValueError('Range filters need amount_units')
        if f['op'] in ('is_null','not_null'):
            if f['value'] is not None:raise ValueError('Null filter value must be null')
            continue
        values=f['value'] if f['op']=='in' else [f['value']]
        if not isinstance(values,list) or not 1<=len(values)<=16:raise ValueError('Bounded filter alternatives required')
        for value in values:
            if f['column']=='amount_units':
                if type(value) is not int or abs(value)>10**9:raise ValueError('Integer filter required')
            elif not isinstance(value,str) or len(value)>64:raise ValueError('Text filter required')
    return program


def matches(record,filters):
    compare={'eq':operator.eq,'ne':operator.ne,'gte':operator.ge,'lte':operator.le}
    for f in filters:
        value=record[f['column']];op=f['op']
        if op=='is_null':ok=value is None
        elif op=='not_null':ok=value is not None
        elif value is None:ok=False  # SQL's ordinary comparisons retain unknown as filtered out.
        elif op=='in':ok=value in f['value']
        else:ok=compare[op](value,f['value'])
        if not ok:return False
    return True


def reference(program):
    validate(program);groups={};dims=program['dimensions']
    if not dims:groups[()]=[]
    for r in program['records']:
        if matches(r,program['filters']):groups.setdefault(tuple(r[d] for d in dims),[]).append(r)
    result=[]
    for key,records in sorted(groups.items()):
        values=[r['amount_units'] for r in records if r['amount_units'] is not None]
        result.append(dict(zip(dims,key),row_count=len(records),amount_sum=sum(values) if values else None,
                           amount_min=min(values) if values else None,amount_max=max(values) if values else None))
    return result


def validate_native(program,schema,snapshot_rows,native,snapshot_sha):
    if schema.get('status')!='OK' or schema.get('snapshot_sha256')!=snapshot_sha:raise ValueError('Schema/snapshot pin mismatch')
    expected_records=[{k:r[k] for k in COLUMNS} for r in sorted(program['records'],key=lambda r:r['entry_id'])]
    if snapshot_rows.get('status')!='ROWS' or snapshot_rows.get('truncated') is not False or snapshot_rows.get('snapshot_sha256')!=snapshot_sha or snapshot_rows.get('columns')!=list(COLUMNS):raise ValueError('Native source read contract')
    decoded=[dict(zip(COLUMNS,r)) for r in snapshot_rows['rows']]
    if digest_json(decoded)!=digest_json(expected_records):raise ValueError('Native source snapshot differs from inputs')
    if native.get('status') not in ('ROWS','QUERY_EMPTY','TRUNCATED') or type(native.get('truncated')) is not bool or native.get('snapshot_sha256')!=snapshot_sha:raise ValueError('Native aggregation contract')
    if (native['status']=='TRUNCATED')!=native['truncated']:raise ValueError('Native truncation status mismatch')
    columns=program['dimensions']+list(MEASURES)
    if native.get('columns')!=columns:raise ValueError('Native column contract')
    oracle=reference(program);rows=native.get('rows',[])
    if not isinstance(rows,list) or any(not isinstance(r,list) or len(r)!=len(columns) for r in rows):raise ValueError('Native row shape')
    groups=[dict(zip(columns,r)) for r in rows]
    if digest_json(groups)!=digest_json(oracle[:program['max_rows']]):raise ValueError('Native rollup disagrees with independent grouping')
    if native['truncated']!=(len(oracle)>program['max_rows']) or native.get('returned_rows')!=len(groups):raise ValueError('Native coverage mismatch')
    receipt=native.get('receipt',{})
    if receipt.get('resource_control',{}).get('shared_read_slots')!=2:raise ValueError('Native shared query guard missing')
    if native.get('rollup',{}).get('filters')!=program['filters'] or native['rollup'].get('dimensions')!=program['dimensions']:raise ValueError('Native invocation mismatch')
    return {'groups':groups,'complete':not native['truncated'],'global_group_count':None if native['truncated'] else len(oracle),
            'returned_group_count':len(groups),'unit':program['unit']}


def run(program_path,runtime,output,allow_incomplete=False):
    if type(allow_incomplete) is not bool:raise ValueError('Boolean completion policy required')
    program_path,runtime,output=Path(program_path),Path(runtime),Path(output);raw=program_path.read_bytes()
    if len(raw)>256*1024:raise ValueError('Program exceeds 256 KiB')
    program=validate(json.loads(raw));oracle=reference(program);output.mkdir(exist_ok=False)
    def save(name,value):
        with (output/name).open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2)
    (output/'program.json').write_bytes(raw);program_sha=file_digest(output/'program.json')
    bridge=Path(__file__).with_name('weave_olap_native.py');bridge_sha=file_digest(bridge);pin=file_digest(runtime)
    command=[sys.executable,str(bridge),str(runtime),str((output/'program.json').resolve()),str(output.resolve())]
    start=time.perf_counter();proc=subprocess.run(command,capture_output=True,text=True,timeout=20,check=False);elapsed=(time.perf_counter()-start)*1000
    save('invocation.json',{'argv':command,'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr})
    if proc.returncode:raise ValueError('Native OLAP bridge failed: '+proc.stderr[-500:])
    if file_digest(runtime)!=pin or file_digest(bridge)!=bridge_sha or program_path.read_bytes()!=raw or file_digest(output/'program.json')!=program_sha:raise ValueError('Runtime or input changed during execution')
    schema=json.loads((output/'native-schema.json').read_text());source_rows=json.loads((output/'native-source-rows.json').read_text())
    native=json.loads((output/'native-rollup.json').read_text());snapshot=json.loads((output/'native-snapshot.json').read_text())
    if file_digest(output/snapshot['path'])!=snapshot['sha256']:raise ValueError('Native snapshot bytes changed')
    result=validate_native(program,schema,source_rows,native,snapshot['sha256']);save('result.json',result);save('reference.json',oracle)
    by_source={}
    for r in program['records']:by_source.setdefault(r['source_id'],[]).append(r)
    sources=[]
    for i,(sid,records) in enumerate(sorted(by_source.items())):
        name='source_'+str(i)+'.json';save(name,records)
        sources.append({'id':sid,'origin_id':records[0]['origin_id'],'path':name,'sha256':file_digest(output/name)})
    ids=[s['id'] for s in sources];origins=sorted({s['origin_id'] for s in sources})
    plan={'version':'weave.v1','steps':[{'id':'grouped','op':'aggregate','inputs':[],'args':{'program_ref':'olap/integer-rollup-v1'}}]}
    request={'version':'weave.request.v1','plan':plan,'require_complete':not allow_incomplete,'sources':sources,'required_sources':{'grouped':ids},'checks':[
        {'kind':'equals','step':'grouped','pointer':'/groups','value':oracle[:program['max_rows']]},
        {'kind':'equals','step':'grouped','pointer':'/global_group_count','value':None if native['truncated'] else len(oracle)},
        {'kind':'equals','step':'grouped','pointer':'/complete','value':not native['truncated']},
        {'kind':'receipt_status','step':'grouped','value':native['status'],'completion_state':'INCOMPLETE' if native['truncated'] else 'COMPLETE'}]}
    catalog={'version':'weave.capabilities.v1','data_class':'synthetic','observed_at':time.time(),'registry':{'mode':'native-adapter-snapshot'},'operations':{'aggregate':{
        'engine':'olap','installed':True,'available':True,'adapter_ready':True,'runtime_sha256':pin,'qualified_runtime_sha256':pin,
        'programs':{'olap/integer-rollup-v1':{'sha256':program_sha,'available':True}}}}}
    receipts=[{'step_id':'grouped','engine':'olap','op':'aggregate','executed':True,'native_status':native['status'],
        'completion_state':'INCOMPLETE' if native['truncated'] else 'COMPLETE','incomplete':native['truncated'],'elapsed_ms':elapsed,
        'coverage':{'input_rows':len(program['records']),'returned_groups':len(result['groups']),'truncation_reason':native.get('truncation_reason')},
        'plan_sha256':digest_json(plan),'args_sha256':digest_json(plan['steps'][0]['args']),'runtime_sha256':pin,'program_sha256':program_sha,
        'source_ids':ids,'origin_ids':origins,'input_hashes':{},'result_path':'result.json','result_sha256':file_digest(output/'result.json'),
        'native_result_path':'native-rollup.json','native_result_sha256':file_digest(output/'native-rollup.json'),'snapshot_sha256':snapshot['sha256']}]
    report=verify(request,catalog,receipts,output)
    for name,value in [('request.json',request),('catalog.json',catalog),('receipts.json',receipts),('verification.json',report)]:save(name,value)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('program',type=Path)
    parser.add_argument('--runtime',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--allow-incomplete',action='store_true');args=parser.parse_args()
    try:
        report=run(args.program,args.runtime,args.out,args.allow_incomplete)
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks'])}));return 0 if report['passed'] else 1
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as exc:parser.exit(2,str(exc)+'\n')


if __name__=='__main__':raise SystemExit(main())
