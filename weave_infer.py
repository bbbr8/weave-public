"""Bounded sourced positive-rule programs executed by native Tally sessions."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
from weave_tally import invoke,fingerprint
from weave_verify import digest_json,file_digest,verify


def validate(program):
    fields={'version','atoms','sources','facts','observations','rules','goal','max_nodes'}
    if not isinstance(program,dict) or set(program)!=fields or program['version']!='weave.tally.rules.v1':raise ValueError('Expected weave.tally.rules.v1')
    ident=lambda x:isinstance(x,str) and re.fullmatch('[a-z][a-z0-9_]{0,23}',x)
    atoms=program['atoms']
    if not isinstance(atoms,list) or not 1<=len(atoms)<=8 or any(not ident(a) for a in atoms) or len(set(atoms))!=len(atoms):raise ValueError('One to eight distinct ordered atom IDs required')
    if program['goal'] not in atoms:raise ValueError('Declared goal atom required')
    if type(program['max_nodes']) is not int or not 1<=program['max_nodes']<=512:raise ValueError('Bounded proof graph required')
    sources=program['sources']
    if not isinstance(sources,list) or not 1<=len(sources)<=16:raise ValueError('One to sixteen source declarations required')
    ids=[]
    for s in sources:
        if not isinstance(s,dict) or set(s)!={'id','origin_id'} or not ident(s['id']) or not isinstance(s['origin_id'],str) or not 1<=len(s['origin_id'])<=64:raise ValueError('Source identity required')
        ids.append(s['id'])
    if len(set(ids))!=len(ids):raise ValueError('Duplicate source ID')
    used=set();pairs=set();names=set()
    for field in ['facts','observations','rules']:
        if not isinstance(program[field],list) or len(program[field])>16:raise ValueError('Bounded facts, observations and rules required')
        for row in program[field]:
            expected={'atom','source_id'} if field=='facts' else ({'id','atom','value','minimum','unit','source_id'} if field=='observations' else {'id','premises','conclusion','source_id'})
            if not isinstance(row,dict) or set(row)!=expected or row['source_id'] not in ids:raise ValueError('Declared rule/fact source required')
            used.add(row['source_id'])
            if field=='facts':
                pair=(row['atom'],row['source_id'])
                if row['atom'] not in atoms or pair in pairs:raise ValueError('Unique declared fact/source pair required')
                pairs.add(pair)
            else:
                if not ident(row['id']) or row['id'] in names:raise ValueError('Distinct rule/observation IDs required')
                names.add(row['id'])
            if field=='observations':
                if row['atom'] not in atoms or any(type(row[k]) is not int or abs(row[k])>10**12 for k in ['value','minimum']):raise ValueError('Exact bounded observation integers required')
                if not isinstance(row['unit'],str) or not 1<=len(row['unit'])<=64:raise ValueError('Observation unit required')
            if field=='rules':
                ps=row['premises'];c=row['conclusion']
                if c not in atoms or not isinstance(ps,list) or not 1<=len(ps)<=4 or len(set(ps))!=len(ps) or any(p not in atoms or atoms.index(p)>=atoms.index(c) for p in ps):raise ValueError('Ordered acyclic positive premises required')
    if used!=set(ids):raise ValueError('Each declared source needs supplied material')
    return program


def reference(program):
    validate(program);support={};asserted={f['atom'] for f in program['facts']}
    for fact in program['facts']:support.setdefault(fact['atom'],set()).add(fact['source_id'])
    for obs in program['observations']:
        if obs['atom'] not in asserted and obs['value']>=obs['minimum']:support.setdefault(obs['atom'],set()).add(obs['source_id'])
    for atom in program['atoms']:
        for rule in program['rules']:
            if atom not in asserted and rule['conclusion']==atom and all(p in support for p in rule['premises']):
                sources={rule['source_id']}
                for p in rule['premises']:sources.update(support[p])
                support.setdefault(atom,set()).update(sources)
    return {'status':'true' if program['goal'] in support else 'unknown',
            'support_source_ids':sorted(support.get(program['goal'],set()))}


def render(program):
    validate(program);lines=[]
    for f in program['facts']:lines.append(f'fact P_{f["atom"]}("item") from "{f["source_id"]}"')
    for o in program['observations']:
        lines.append(f'fact O_{o["id"]}("item", {o["value"]}) from "{o["source_id"]}"')
        lines.append(f'rule obs_{o["id"]} {{ when O_{o["id"]}(x, v), v >= ({o["minimum"]}) => P_{o["atom"]}(x) }}')
    for r in program['rules']:
        premises=', '.join('P_'+p+'(x)' for p in r['premises'])
        lines.append(f'rule rule_{r["id"]} {{ when {premises} => P_{r["conclusion"]}(x) }}')
    return '\n'.join(lines)


def normalize(program,graph):
    expected=reference(program);root='P_'+program['goal']+'("item")'
    if not isinstance(graph,dict) or graph.get('schema')!='tally.proof_graph.v1' or graph.get('root')!=root or graph.get('status')!=expected['status'] or graph.get('max_nodes')!=program['max_nodes'] or type(graph.get('truncated')) is not bool:raise ValueError('Native proof graph contract failed')
    if not isinstance(graph.get('nodes'),list) or not isinstance(graph.get('edges'),list):raise ValueError('Proof graph nodes and edges required')
    complete=not graph['truncated'];selected=None;origins=None
    if complete:
        nodes=[n for n in graph['nodes'] if n.get('id')==root and n.get('kind')=='fact']
        if len(nodes)!=1 or nodes[0].get('status')!=expected['status']:raise ValueError('Native goal node failed')
        labels={s['id']:s['id'] for s in program['sources']}
        labels.update({'rule rule_'+r['id']:r['source_id'] for r in program['rules']})
        labels.update({'rule obs_'+r['id']:r['source_id'] for r in program['observations']})
        native_sources=nodes[0].get('sources',[])
        if not isinstance(native_sources,list) or any(s not in labels for s in native_sources):raise ValueError('Unknown native proof source')
        selected=sorted({labels[s] for s in native_sources})
        if selected!=expected['support_source_ids']:raise ValueError('Native proof support differs from independent rule closure')
        lookup={s['id']:s['origin_id'] for s in program['sources']};origins=sorted({lookup[s] for s in selected})
    return {'goal':program['goal'],'status':graph['status'],'complete':complete,
        'supported_goals':int(expected['status']=='true') if complete else None,
        'support_source_ids':selected,'support_origin_ids':origins,'support_origin_count':len(origins) if complete else None,
        'proof_graph':graph}


def audit(root):
    root=Path(root);load=lambda name:json.loads((root/name).read_text())
    program=validate(load('program.json'));responses=load('native.json');receipts=load('receipts.json')
    if len(responses)!=3 or len(receipts)!=1:raise ValueError('Inference artifact count changed')
    receipt=receipts[0]
    for field,name in [('native_sha256','native.json'),('source_tly_sha256','source.tly'),('requests_sha256','requests.json')]:
        if receipt.get(field)!=file_digest(root/name):raise ValueError('Native inference link changed')
    if (root/'source.tly').read_bytes()!=render(program).encode():raise ValueError('Rendered inference program changed')
    if digest_json(normalize(program,responses[2]['value']))!=digest_json(load('result.json')):raise ValueError('Native inference normalization changed')
    for source in program['sources']:
        expected={'source':source,'facts':[f for f in program['facts'] if f['source_id']==source['id']],
            'observations':[o for o in program['observations'] if o['source_id']==source['id']],
            'rules':[r for r in program['rules'] if r['source_id']==source['id']]}
        if digest_json(load(source['id']+'.source.json'))!=digest_json(expected):raise ValueError('Inference source snapshot changed')
    catalog=load('catalog.json')
    return verify(load('request.json'),catalog,receipts,root,now=catalog['observed_at'])


def run(program_path,runtime,output):
    program_path,runtime,output=Path(program_path),Path(runtime),Path(output);raw=program_path.read_bytes()
    if len(raw)>64*1024:raise ValueError('Program exceeds 64 KiB')
    program=validate(json.loads(raw));code=render(program);output.mkdir(exist_ok=False)
    def save(name,value):
        with (output/name).open('xb') as stream:stream.write(json.dumps(value,indent=2).encode())
    (output/'program.json').write_bytes(raw);(output/'source.tly').write_bytes(code.encode())
    requests=[{'id':'load','op':'exec','code':code,'max_steps':5000},
              {'id':'goal','op':'proof_graph','pattern':'P_'+program['goal']+'("item")','max_nodes':program['max_nodes'],'max_steps':5000}]
    save('requests.json',requests);probe=invoke(runtime,'0');pin=fingerprint(runtime,probe);save('probe.json',probe)
    started=time.monotonic()
    proc=subprocess.run([str(runtime),'serve'],input=''.join(json.dumps(r)+'\n' for r in requests),capture_output=True,text=True,timeout=10,check=False)
    elapsed=(time.monotonic()-started)*1000
    save('invocation.json',{'argv':[str(runtime),'serve'],'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr})
    if proc.returncode or len(proc.stdout)>2*1024*1024:raise ValueError('Native rule session failed or exceeded bound')
    responses=[json.loads(line) for line in proc.stdout.splitlines()];save('native.json',responses)
    if len(responses)!=3 or responses[0].get('op')!='hello' or responses[0].get('tally')!='0.28' or [r.get('id') for r in responses[1:]]!=['load','goal'] or any(r.get('ok') is not True or r.get('error') is not None for r in responses[1:]):raise ValueError('Native rule session response failed')
    if fingerprint(runtime,invoke(runtime,'0'))!=pin or program_path.read_bytes()!=raw or (output/'source.tly').read_bytes()!=code.encode():raise ValueError('Runtime or input changed during inference')
    result=normalize(program,responses[2]['value']);save('result.json',result)
    source_ids=[s['id'] for s in program['sources']]
    for s in program['sources']:
        save(s['id']+'.source.json',{'source':s,'facts':[f for f in program['facts'] if f['source_id']==s['id']],
            'observations':[o for o in program['observations'] if o['source_id']==s['id']],
            'rules':[r for r in program['rules'] if r['source_id']==s['id']]})
    plan={'version':'weave.v1','steps':[{'id':'inference','op':'infer','inputs':[],'args':{'program_ref':'tally/rules-v1'}}]}
    status=responses[2]['value']['status'];complete=result['complete'];program_sha=file_digest(output/'program.json')
    sources=[{'id':s['id'],'origin_id':s['origin_id'],'path':s['id']+'.source.json','sha256':file_digest(output/(s['id']+'.source.json'))} for s in program['sources']]
    checks=[{'kind':'equals','step':'inference','pointer':'/status','value':reference(program)['status']},
            {'kind':'equals','step':'inference','pointer':'/support_source_ids','value':reference(program)['support_source_ids']},
            {'kind':'receipt_status','step':'inference','value':status,'completion_state':'COMPLETE' if complete else 'INCOMPLETE'}]
    request={'version':'weave.request.v1','plan':plan,'sources':sources,'required_sources':{'inference':source_ids},'checks':checks}
    catalog={'version':'weave.capabilities.v1','data_class':'synthetic','observed_at':time.time(),'registry':{'mode':'native-adapter-snapshot'},
        'operations':{'infer':{'engine':'tally','installed':True,'available':True,'adapter_ready':True,'runtime_sha256':pin,'qualified_runtime_sha256':pin,
        'programs':{'tally/rules-v1':{'sha256':program_sha,'available':True}}}}}
    receipts=[{'step_id':'inference','engine':'tally','op':'infer','executed':True,'native_status':status,
        'completion_state':'COMPLETE' if complete else 'INCOMPLETE','incomplete':not complete,'elapsed_ms':elapsed,
        'coverage':{'proof_nodes':len(result['proof_graph']['nodes']),'truncated':not complete,'max_nodes':program['max_nodes']},
        'plan_sha256':digest_json(plan),'args_sha256':digest_json(plan['steps'][0]['args']),'runtime_sha256':pin,'program_sha256':program_sha,
        'source_ids':source_ids,'origin_ids':sorted({s['origin_id'] for s in program['sources']}),'input_hashes':{},
        'result_path':'result.json','result_sha256':file_digest(output/'result.json'),
        'native_sha256':file_digest(output/'native.json'),'source_tly_sha256':file_digest(output/'source.tly'),'requests_sha256':file_digest(output/'requests.json'),
        'result_units':{'/supported_goals':'count','/support_origin_count':'count'},'adapter_sha256':file_digest(Path(__file__))}]
    report=verify(request,catalog,receipts,output)
    for name,value in [('request.json',request),('catalog.json',catalog),('receipts.json',receipts),('verification.json',report)]:save(name,value)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('program',type=Path);parser.add_argument('--runtime',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    try:report=run(args.program,args.runtime,args.out)
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as exc:parser.exit(2,str(exc)+'\n')
    print(json.dumps({'passed':report['passed']}));raise SystemExit(0 if report['passed'] else 1)
