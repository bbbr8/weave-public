"""Execute bounded synthetic adapter pipelines with typed scalar dependencies.

Supports read, infer, calculate, solve and aggregate on a host with the selected runtimes.
Native bundles stay byte-preserved; combined receipts explicitly bind them to
the outer plan. Native artifact verification does not provide remote attestation.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import subprocess
import time
from weave import compile_plan
from weave_checks import pointer,pointer_parts,validate_check
from weave_verify import digest_json,file_digest,verify,inside
import weave_tally
import weave_qulap
import weave_olap
import weave_loom
import weave_loom_bundle
import weave_infer

SUPPORTED={'read','infer','calculate','solve','aggregate'}


def unit_for(op,program,path,destination=False):
    pointer_parts(path)
    if op=='infer':
        if not destination and path in ('/supported_goals','/support_origin_count'):return 'count'
        match=re.fullmatch(r'/observations/(\d+)/value',path) if destination else None
        if match and int(match[1])<len(program['observations']):return program['observations'][int(match[1])]['unit']
    if op=='read' and not destination and path=='/independent_origins':return 'count'
    if op=='calculate' and (path=='/value' if not destination else re.fullmatch(r'/terms/\d+',path)):
        return program['unit']
    if op=='solve':
        if destination and (re.fullmatch(r'/constraints/\d+/bound',path) or re.fullmatch(r'/variables/\d+/domain/\d+',path)):
            return 'integer'
        if not destination and re.fullmatch(r'/metrics/[^/]+/(min|max)',path):return 'integer'
        if not destination and path in ('/global_feasible_states','/observed_feasible_states','/candidate_states'):return 'count'
    if op=='aggregate':
        if destination and re.fullmatch(r'/records/\d+/amount_units',path):return program['unit']
        if not destination and re.fullmatch(r'/groups/\d+/amount_(sum|min|max)',path):return program['unit']
        if not destination and (re.fullmatch(r'/groups/\d+/row_count',path) or path in ('/global_group_count','/returned_group_count')):return 'count'
    raise ValueError('Binding pointer has no supported unit contract: '+path)


def validate(packet):
    fields={'version','data_class','plan','programs','bindings','checks','node_options'}
    if not isinstance(packet,dict) or set(packet)!=fields or packet['version']!='weave.pipeline.v1' or packet['data_class']!='synthetic':raise ValueError('Expected synthetic weave.pipeline.v1')
    plan=compile_plan(packet['plan']);steps=plan['steps']
    if len(steps)>8 or any(s['op'] not in SUPPORTED or not re.fullmatch('[a-z][a-z0-9_]{0,31}',s['id']) for s in steps):raise ValueError('Expected at most eight read/infer/calculate/solve/aggregate steps with short IDs')
    by_id={s['id']:s for s in steps};refs=[s['args']['program_ref'] for s in steps]
    if len(refs)!=len(set(refs)) or not isinstance(packet['programs'],dict) or set(packet['programs'])!=set(refs):raise ValueError('One unique program reference per step required')
    for s in steps:
        program=packet['programs'][s['args']['program_ref']]
        if s['op']=='calculate':weave_tally.expression(program)
        elif s['op']=='solve':weave_qulap.validate(program)
        elif s['op']=='aggregate':weave_olap.validate(program)
        elif s['op']=='infer':weave_infer.validate(program)
        else:weave_loom.validate(program)
    if not isinstance(packet['node_options'],dict) or not set(packet['node_options'])<=set(by_id):raise ValueError('Node options contract')
    for ident,opts in packet['node_options'].items():
        if by_id[ident]['op']!='solve' or not isinstance(opts,dict) or set(opts)!={'max_nodes'} or type(opts['max_nodes']) is not int or not 1<=opts['max_nodes']<=20000:raise ValueError('Only bounded QULAP max_nodes options supported')
    if not isinstance(packet['checks'],list) or not 1<=len(packet['checks'])<=128:raise ValueError('Explicit result checks required')
    for check in packet['checks']:validate_check(check,set(by_id))
    if not isinstance(packet['bindings'],list) or len(packet['bindings'])>32:raise ValueError('Bounded bindings required')
    targets={};consumed={ident:set() for ident in by_id}
    for binding in packet['bindings']:
        if not isinstance(binding,dict) or set(binding)!={'step','target','source_step','pointer','unit'}:raise ValueError('Binding fields')
        dest,source=binding['step'],binding['source_step']
        if dest not in by_id or source not in by_id or source not in by_id[dest]['inputs']:raise ValueError('Binding must name a declared earlier dependency')
        target=pointer_parts(binding['target'])
        for previous in targets.get(dest,[]):
            if target[:len(previous)]==previous or previous[:len(target)]==target:raise ValueError('Overlapping binding targets')
        targets.setdefault(dest,[]).append(target);consumed[dest].add(source)
        src_program=packet['programs'][by_id[source]['args']['program_ref']]
        dst_program=packet['programs'][by_id[dest]['args']['program_ref']]
        try:target_value=pointer(dst_program,binding['target'])
        except (IndexError,KeyError,TypeError) as exc:raise ValueError('Binding target unavailable') from exc
        if type(target_value) is not int:raise ValueError('Binding target must be an existing integer literal')
        if binding['unit']!=unit_for(by_id[source]['op'],src_program,binding['pointer']) or binding['unit']!=unit_for(by_id[dest]['op'],dst_program,binding['target'],True):raise ValueError('Binding unit mismatch')
    if any(consumed[s['id']]!=set(s['inputs']) for s in steps):raise ValueError('Every declared dependency needs a concrete data binding')
    return steps


def set_integer(program,path,value):
    if type(value) is not int:raise ValueError('Binding source must be a complete exact integer')
    parts=pointer_parts(path);node=program
    for part in parts[:-1]:node=node[int(part)] if isinstance(node,list) else node[part]
    key=int(parts[-1]) if isinstance(node,list) else parts[-1]
    if (isinstance(node,dict) and key not in node) or (isinstance(node,list) and not 0<=key<len(node)):raise ValueError('Binding target missing')
    node[key]=value


def resolve(packet,step,parents,programs):
    program=copy.deepcopy(programs[step['args']['program_ref']]);records=[]
    for b in packet['bindings']:
        if b['step']!=step['id']:continue
        parent=parents[b['source_step']]
        if file_digest(parent['path'])!=parent['sha256']:raise ValueError('Parent result changed before binding')
        try:value=pointer(parent['result'],b['pointer'])
        except (IndexError,KeyError,TypeError) as exc:
            raise ValueError('Binding source pointer unavailable: '+b['pointer']) from exc
        set_integer(program,b['target'],value)
        records.append(dict(b,source_result_sha256=parent['sha256'],value=value,value_sha256=digest_json(value)))
    return program,records


def dispatch(op,program_path,runtime,output,options):
    if op=='infer':return weave_infer.run(program_path,runtime,output)
    if op=='read':return weave_loom_bundle.run(program_path,runtime,output)
    if op=='calculate':return weave_tally.run(program_path,runtime,output)
    if op=='solve':return weave_qulap.run(program_path,runtime,output,max_nodes=options.get('max_nodes',20000))
    if op=='aggregate':return weave_olap.run(program_path,runtime,output)
    raise ValueError('Unsupported adapter')


def audit_transfers(packet,root,receipts,bindings):
    steps=validate(packet);by_id={s['id']:s for s in steps};parents={};expected_bindings=[];seen=set()
    for receipt in receipts:
        ident=receipt['step_id']
        if ident in seen or ident not in by_id:raise ValueError('Unexpected pipeline receipt')
        seen.add(ident);step=by_id[ident]
        if any(dep not in parents for dep in step['inputs']):raise ValueError('Unverified parent in transfer audit')
        expected,transfers=resolve(packet,step,parents,packet['programs']);expected_bindings.extend(transfers)
        folder=root/'nodes'/ident/'native'
        if step['op']=='read':weave_loom_bundle.audit(folder)
        if step['op']=='infer':weave_infer.audit(folder)
        native_receipts=json.loads((folder/'receipts.json').read_text())
        if len(native_receipts)!=1 or file_digest(folder/'receipts.json')!=receipt['native_receipts_sha256'] or digest_json(native_receipts[0])!=receipt['native_receipt_digest']:raise ValueError('Native receipt link changed')
        native=native_receipts[0]
        local_catalog=json.loads((folder/'catalog.json').read_text())
        local_report=verify(json.loads((folder/'request.json').read_text()),local_catalog,native_receipts,folder,now=local_catalog.get('observed_at'))
        if receipt['completion_state']=='COMPLETE' and not local_report['passed']:raise ValueError('Native bundle failed its own complete-result checks')
        for key in ['op','engine','runtime_sha256','program_sha256','result_sha256','native_status','completion_state','incomplete','executed']:
            if native.get(key)!=receipt.get(key):raise ValueError('Native receipt adaptation changed '+key)
        if digest_json(json.loads((folder/'program.json').read_text()))!=digest_json(expected) or digest_json(json.loads((folder.parent/'resolved-program.json').read_text()))!=digest_json(expected):raise ValueError('Resolved program disagrees with parent transfer')
        if file_digest(folder/'program.json')!=receipt['program_sha256']:raise ValueError('Resolved program hash changed')
        result_path=inside(root,receipt['result_path'])
        if result_path.resolve()!=(folder/native['result_path']).resolve():raise ValueError('Native result path adaptation changed')
        if file_digest(result_path)!=receipt['result_sha256']:raise ValueError('Parent result artifact changed')
        if receipt['completion_state']=='COMPLETE':parents[ident]={'result':json.loads(result_path.read_text()),'path':result_path,'sha256':receipt['result_sha256']}
    if digest_json(expected_bindings)!=digest_json(bindings):raise ValueError('Binding ledger changed')
    return {'passed':True,'verified_bindings':len(expected_bindings),'verified_native_links':len(receipts)}


def audit_directory(root):
    root=Path(root);packet=json.loads((root/'pipeline.json').read_text())
    receipts=json.loads((root/'receipts.json').read_text());bindings=json.loads((root/'bindings.json').read_text())
    transfers=audit_transfers(packet,root,receipts,bindings)
    request=json.loads((root/'request.json').read_text())
    expected={'version':'weave.request.v1','plan':packet['plan'],'require_complete':True,
        'sources':[{'id':'pipeline','origin_id':'pipeline-input','path':'pipeline.json','sha256':file_digest(root/'pipeline.json')}],
        'required_sources':{s['id']:['pipeline'] for s in validate(packet)},'checks':packet['checks']}
    if digest_json(request)!=digest_json(expected):raise ValueError('Pipeline request changed after execution')
    catalog=json.loads((root/'catalog.json').read_text())
    report=verify(request,catalog,receipts,root,now=catalog.get('observed_at'))
    return {'passed':report['passed'] and transfers['passed'],'transfers':transfers,'verification':report,
            'audit_mode':'historical_artifacts','live_runtime_rechecked':False}


def run(pipeline_path,runtimes,output):
    pipeline_path,output=Path(pipeline_path),Path(output);raw=pipeline_path.read_bytes()
    if len(raw)>512*1024:raise ValueError('Pipeline exceeds 512 KiB')
    packet=json.loads(raw);steps=validate(packet)
    used={s['op'] for s in steps}
    if not isinstance(runtimes,dict) or not used<=set(runtimes) or any(not isinstance(runtimes[op],str) or not runtimes[op] for op in used):raise ValueError('Operator-supplied runtime paths required')
    output.mkdir(exist_ok=False)
    def save(name,value):
        path=output/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(json.dumps(value,indent=2).encode())
    (output/'pipeline.json').write_bytes(raw);save('runtimes.json',runtimes)
    source={'id':'pipeline','origin_id':'pipeline-input','path':'pipeline.json','sha256':file_digest(output/'pipeline.json')}
    parents={};receipts=[];nodes=[];bindings=[]
    catalog={'version':'weave.capabilities.v1','data_class':'synthetic','observed_at':time.time(),'registry':{'mode':'pipeline-adapter-snapshot'},'operations':{}}
    for step in steps:
        ident=step['id'];op=step['op']
        if any(dep not in parents for dep in step['inputs']):
            nodes.append({'step':ident,'state':'SKIPPED_DEPENDENCY'});continue
        try:
            program,transfers=resolve(packet,step,parents,packet['programs'])
            save('nodes/'+ident+'/resolved-program.json',program)
            folder=output/'nodes'/ident/'native'
            local_report=dispatch(op,folder.parent/'resolved-program.json',Path(runtimes[op]),folder,packet['node_options'].get(ident,{}))
            local_catalog=json.loads((folder/'catalog.json').read_text())
            local_receipts=json.loads((folder/'receipts.json').read_text())
            if len(local_receipts)!=1:raise ValueError('Single-operation native bundle required')
            local_report=verify(json.loads((folder/'request.json').read_text()),local_catalog,local_receipts,folder)
            local=local_receipts[0];cap=copy.deepcopy(local_catalog['operations'][op])
            native_ref=next(iter(cap['programs']));program_entry=cap['programs'][native_ref]
            ref=step['args']['program_ref'];cap['programs']={ref:program_entry}
            if op in catalog['operations']:
                if cap['runtime_sha256']!=catalog['operations'][op]['runtime_sha256']:raise ValueError('Runtime changed across pipeline steps')
                catalog['operations'][op]['programs'][ref]=program_entry
            else:catalog['operations'][op]=cap
            result_path=folder/local['result_path'];result_hash=file_digest(result_path)
            if result_hash!=local['result_sha256']:raise ValueError('Native result changed after verification')
            if digest_json(json.loads((folder/'program.json').read_text()))!=digest_json(program):raise ValueError('Adapter used a different input program')
            lifted=copy.deepcopy(local)
            lifted.update(step_id=ident,plan_sha256=digest_json(packet['plan']),args_sha256=digest_json(step['args']),
                source_ids=['pipeline'],origin_ids=['pipeline-input'],input_hashes={dep:parents[dep]['sha256'] for dep in step['inputs']},
                result_path=str(result_path.relative_to(output)),native_bundle_root=str(folder.relative_to(output)),
                native_receipts_sha256=file_digest(folder/'receipts.json'),native_receipt_digest=digest_json(local))
            receipts.append(lifted);bindings.extend(transfers)
            state='VERIFIED' if local_report.get('passed') and local_report.get('results_verified') else 'FAILED_VERIFICATION'
            nodes.append({'step':ident,'state':state,'native_status':local['native_status'],'native_bundle':str(folder.relative_to(output))})
            if state=='VERIFIED':parents[ident]={'result':json.loads(result_path.read_text()),'path':result_path,'sha256':result_hash}
        except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as exc:
            nodes.append({'step':ident,'state':'ERROR','error':str(exc)[:500]})
    request={'version':'weave.request.v1','plan':packet['plan'],'require_complete':True,'sources':[source],
             'required_sources':{s['id']:['pipeline'] for s in steps},'checks':packet['checks']}
    report=verify(request,catalog,receipts,output)
    if pipeline_path.read_bytes()!=raw or file_digest(output/'pipeline.json')!=source['sha256']:
        raise ValueError('Pipeline changed during execution')
    report['nodes']=nodes;report['binding_count']=len(bindings)
    report['native_bundle_scope']='Native adapter receipts preserved; outer receipts are explicit pipeline adaptations.'
    try:transfers=audit_transfers(packet,output,receipts,bindings)
    except (ValueError,KeyError,TypeError,OSError) as exc:transfers={'passed':False,'error':str(exc)[:500]}
    report['transfers']=transfers
    report['passed']=report['passed'] and transfers['passed'] and all(n['state']=='VERIFIED' for n in nodes)
    report['results_verified']=report['results_verified'] and report['passed']
    for name,value in [('request.json',request),('catalog.json',catalog),('receipts.json',receipts),
                       ('bindings.json',bindings),('verification.json',report)]:save(name,value)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('pipeline',type=Path,nargs='?')
    parser.add_argument('--runtimes',type=Path);parser.add_argument('--out',type=Path);parser.add_argument('--audit',type=Path);args=parser.parse_args()
    try:
        if args.audit:
            if args.pipeline or args.runtimes or args.out:parser.error('--audit accepts only an existing directory')
            report=audit_directory(args.audit);print(json.dumps({'passed':report['passed'],'transfers':report['transfers']}));return 0 if report['passed'] else 1
        if not args.pipeline or not args.runtimes or not args.out:parser.error('Provide pipeline, --runtimes and --out')
        report=run(args.pipeline,json.loads(args.runtimes.read_text()),args.out)
        print(json.dumps({'passed':report['passed'],'nodes':report['nodes'],'binding_count':report['binding_count']}));return 0 if report['passed'] else 1
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as exc:parser.exit(2,str(exc)+'\n')


if __name__=='__main__':raise SystemExit(main())
