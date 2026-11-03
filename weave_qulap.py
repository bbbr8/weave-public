"""Bounded native QULAP adapter with an independent finite integer oracle.

Synthetic-only integer models, executed on the Mac holding QULAP. Input programs
contain typed coefficients and finite domains; expression text is generated here.
"""
import argparse
import itertools
import json
import keyword
import math
import operator
from pathlib import Path
import re
import subprocess
import time
from weave_verify import digest_json, file_digest, verify

RELATIONS = {'<':operator.lt, '<=':operator.le, '==':operator.eq,
             '!=':operator.ne, '>=':operator.ge, '>':operator.gt}


def integer(value):
    if type(value) is not int or abs(value)>10**6:
        raise ValueError('Integer literal bounded to 10^6 required')
    return value


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[a-z][a-z0-9_]{0,31}',value) or keyword.iskeyword(value):
        raise ValueError('Short lowercase identifier required')
    return value


def validate(program):
    if not isinstance(program,dict) or set(program)!={'version','variables','constraints','metrics'} or program['version']!='weave.qulap.integer.v1':
        raise ValueError('Expected weave.qulap.integer.v1 program')
    variables=program['variables']
    if not isinstance(variables,list) or not 1<=len(variables)<=6:
        raise ValueError('Expected 1..6 finite variables')
    names=set()
    for var in variables:
        if not isinstance(var,dict) or set(var)!={'id','domain'}:raise ValueError('Variable fields')
        name=identifier(var['id'])
        if name in names:raise ValueError('Duplicate variable')
        names.add(name);domain=var['domain']
        if not isinstance(domain,list) or not 1<=len(domain)<=8:raise ValueError('Expected 1..8 alternatives')
        for x in domain:integer(x)
        if len(domain)!=len(set(domain)):raise ValueError('Duplicate alternatives')
    if math.prod(len(v['domain']) for v in variables)>4096:raise ValueError('Domain exceeds 4096 states')
    for field,low,high in [('constraints',0,16),('metrics',1,4)]:
        entries=program[field]
        if not isinstance(entries,list) or not low<=len(entries)<=high:raise ValueError('Entry count')
        seen=set()
        for entry in entries:
            required={'id','coefficients','relation','bound'} if field=='constraints' else {'id','coefficients','constant'}
            if not isinstance(entry,dict) or set(entry)!=required:raise ValueError('Expression fields')
            ident=identifier(entry['id'])
            if ident in seen:raise ValueError('Duplicate expression')
            seen.add(ident);coeff=entry['coefficients']
            if not isinstance(coeff,dict) or not set(coeff)<=names:raise ValueError('Unknown coefficient variable')
            for value in coeff.values():integer(value)
            if field=='constraints':
                if not isinstance(entry['relation'],str) or entry['relation'] not in RELATIONS:raise ValueError('Comparison required')
                integer(entry['bound'])
            else:integer(entry['constant'])
    return program


def linear_text(coefficients,constant=0):
    return ' + '.join(['('+str(value)+') * '+name for name,value in sorted(coefficients.items())]+['('+str(constant)+')'])


def native_model(program,source_sha):
    validate(program)
    return {'schema':'qulap.model.v1','source_tier':'synthetic',
            'variables':[dict(v,unit='integer',source_ids=['program']) for v in program['variables']],
            'constraints':[{'id':c['id'],'expr':'('+linear_text(c['coefficients'])+') '+c['relation']+' ('+str(c['bound'])+')',
                            'source_ids':['program']} for c in program['constraints']],
            'metrics':[{'id':m['id'],'expr':linear_text(m['coefficients'],m['constant']),
                        'unit':'integer','source_ids':['program']} for m in program['metrics']],
            'propositions':[], 'sources':[{'id':'program','lineage_id':'finite-input',
                                         'locator':'synthetic:program.json@sha256:'+source_sha}]}


def reference(program):
    """Evaluate integer dictionaries directly; never evaluate generated expressions."""
    validate(program)
    variables=program['variables'];worlds=[]
    for values in itertools.product(*(v['domain'] for v in variables)):
        world=dict(zip((v['id'] for v in variables),values))
        if all(RELATIONS[c['relation']](sum(world[k]*v for k,v in c['coefficients'].items()),c['bound']) for c in program['constraints']):
            worlds.append(world)
    bounds={}
    for m in program['metrics']:
        values=[m['constant']+sum(w[k]*v for k,v in m['coefficients'].items()) for w in worlds]
        bounds[m['id']]={'min':min(values) if values else None,'max':max(values) if values else None,'unit':'integer'}
    return {'candidate_states':math.prod(len(v['domain']) for v in variables),
            'feasible_states':len(worlds),'metrics':bounds,'worlds':worlds}


def runtime_fingerprint(runtime):
    runtime=Path(runtime).resolve();package=runtime.parent/'qulap'
    files=sorted(package.glob('*.py'))
    if not files or not all((package/name).is_file() for name in ['cli.py','model.py','worlds.py']):
        raise ValueError('Installed QULAP Python package required')
    hashes={p.name:file_digest(p) for p in files}
    return {'entrypoint':file_digest(runtime),'modules':hashes}


def validate_native(native,code,model,oracle):
    if not isinstance(native,dict) or native.get('schema')!='qulap.result.v1' or native.get('backend')!='reference' or native.get('search_mode')!='enumerate':
        raise ValueError('Unexpected native QULAP result contract')
    if native.get('model_sha256')!=digest_json(model) or native.get('sources')!=model['sources']:
        raise ValueError('Native model identity or source retention mismatch')
    if native.get('candidate_states')!=oracle['candidate_states'] or type(native.get('complete')) is not bool:
        raise ValueError('Native domain/completeness mismatch')
    complete=native['complete'];state=native.get('state')
    if (code,state) not in ([(0,'COMPLETE'),(0,'INCONSISTENT_MODEL')] if complete else [(3,'INCOMPLETE')]):
        raise ValueError('Native exit/state/completeness disagreement')
    count=native.get('feasible_states');worlds=native.get('worlds')
    if type(count) is not int or not isinstance(worlds,list) or len(worlds)!=count or native.get('worlds_truncated') is not False:
        raise ValueError('Expected all retained observed worlds')
    keys=[digest_json(w) for w in worlds];allowed={digest_json(w) for w in oracle['worlds']}
    if len(keys)!=len(set(keys)) or not set(keys)<=allowed:raise ValueError('Invalid or duplicate native world')
    if complete:
        if count!=oracle['feasible_states'] or set(keys)!=allowed:raise ValueError('Native enumeration disagrees with oracle')
        expected='COMPLETE' if count else 'INCONSISTENT_MODEL'
        if state!=expected or native.get('cutoff') is not None:raise ValueError('Native complete state mismatch')
    elif not native.get('cutoff'):raise ValueError('Incomplete cutoff reason required')
    metrics=native.get('metrics',{})
    if set(metrics)!=set(oracle['metrics']):raise ValueError('Native metric names mismatch')
    bounds={name:{k:metrics[name][k] for k in ('min','max','unit')} for name in metrics}
    expected=oracle['metrics'] if complete else {name:{'min':None,'max':None,'unit':'integer'} for name in metrics}
    if digest_json(bounds)!=digest_json(expected):raise ValueError('Native global bounds disagree with independent oracle')
    return {'complete':complete,'candidate_states':oracle['candidate_states'],
            'global_feasible_states':count if complete else None,'observed_feasible_states':count,'metrics':bounds}


def run(program_path,runtime,output,max_nodes=20000,allow_incomplete=False):
    if type(max_nodes) is not int or not 1<=max_nodes<=20000:raise ValueError('Node budget must be 1..20000')
    if type(allow_incomplete) is not bool:raise ValueError('Completion policy must be boolean')
    program_path,runtime,output=Path(program_path),Path(runtime),Path(output)
    raw=program_path.read_bytes()
    if len(raw)>16384:raise ValueError('Program exceeds 16 KiB')
    program=validate(json.loads(raw));oracle=reference(program)
    output.mkdir(exist_ok=False)
    def save(name,value):
        with (output/name).open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2)
    (output/'program.json').write_bytes(raw);sha=file_digest(output/'program.json')
    model=native_model(program,sha);save('model.json',model);model_sha=file_digest(output/'model.json')
    fingerprint=runtime_fingerprint(runtime);pin=digest_json(fingerprint)
    started=time.perf_counter()
    command=[str(runtime),'solve',str((output/'model.json').resolve()),'--backend','reference',
             '--mode','enumerate','--max-nodes',str(max_nodes),'--seconds','2','--retain-worlds','4096']
    proc=subprocess.run(command,capture_output=True,text=True,timeout=10,check=False)
    elapsed=(time.perf_counter()-started)*1000
    (output/'native.stdout.json').write_text(proc.stdout,encoding='utf-8')
    (output/'native.stderr.txt').write_text(proc.stderr,encoding='utf-8')
    if len(proc.stdout)>2*1024*1024 or proc.returncode not in (0,3):raise ValueError('QULAP execution failed')
    if runtime_fingerprint(runtime)!=fingerprint or program_path.read_bytes()!=raw or file_digest(output/'model.json')!=model_sha:
        raise ValueError('Runtime or input changed during execution')
    native=json.loads(proc.stdout);result=validate_native(native,proc.returncode,model,oracle)
    save('result.json',result);save('reference.json',oracle);save('runtime-fingerprint.json',fingerprint)
    complete=result['complete'];step={'id':'finite','op':'solve','inputs':[],'args':{'program_ref':'qulap/integer-v1'}}
    plan={'version':'weave.v1','steps':[step]}
    expected_bounds=oracle['metrics'] if complete else {name:{'min':None,'max':None,'unit':'integer'} for name in oracle['metrics']}
    request={'version':'weave.request.v1','plan':plan,'require_complete':not allow_incomplete,
             'sources':[{'id':'program','origin_id':'finite-input','path':'program.json','sha256':sha}],
             'required_sources':{'finite':['program']},'checks':[
                 {'kind':'equals','step':'finite','pointer':'/candidate_states','value':oracle['candidate_states']},
                 {'kind':'equals','step':'finite','pointer':'/global_feasible_states','value':oracle['feasible_states'] if complete else None},
                 {'kind':'equals','step':'finite','pointer':'/metrics','value':expected_bounds},
                 {'kind':'equals','step':'finite','pointer':'/complete','value':complete},
                 {'kind':'receipt_status','step':'finite','value':native['state'],'completion_state':'COMPLETE' if complete else 'INCOMPLETE'}]}
    catalog={'version':'weave.capabilities.v1','data_class':'synthetic','observed_at':time.time(),
             'registry':{'mode':'native-adapter-snapshot'},'operations':{'solve':{'engine':'qulap','installed':True,
                 'available':True,'adapter_ready':True,'runtime_sha256':pin,'qualified_runtime_sha256':pin,
                 'programs':{'qulap/integer-v1':{'sha256':sha,'available':True}}}}}
    receipts=[{'step_id':'finite','engine':'qulap','op':'solve','executed':True,'native_status':native['state'],
               'completion_state':'COMPLETE' if complete else 'INCOMPLETE','incomplete':not complete,
               'elapsed_ms':elapsed,'coverage':{k:native[k] for k in ('candidate_states','visited_nodes','feasible_states','cutoff')},
               'plan_sha256':digest_json(plan),'args_sha256':digest_json(step['args']),'runtime_sha256':pin,'program_sha256':sha,
               'source_ids':['program'],'origin_ids':['finite-input'],'input_hashes':{},'result_path':'result.json',
               'result_sha256':file_digest(output/'result.json'),'native_result_path':'native.stdout.json',
               'native_result_sha256':file_digest(output/'native.stdout.json'),'native_exit_code':proc.returncode}]
    report=verify(request,catalog,receipts,output)
    for name,value in [('request.json',request),('catalog.json',catalog),('receipts.json',receipts),
                       ('verification.json',report),('invocation.json',{'argv':command,'exit_code':proc.returncode})]:save(name,value)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('program',type=Path)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--max-nodes',type=int,default=20000)
    parser.add_argument('--allow-incomplete',action='store_true');args=parser.parse_args()
    try:
        report=run(args.program,args.runtime,args.out,args.max_nodes,args.allow_incomplete)
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'receipt_directory':str(args.out)}))
        return 0 if report['passed'] else 1
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as exc:parser.exit(2,str(exc)+'\n')


if __name__=='__main__':raise SystemExit(main())
