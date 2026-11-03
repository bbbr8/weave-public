"""Deterministic capability, receipt and exact-result verifier for Weave."""
import argparse
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import time
import subprocess
import re
from weave import compile_plan
from weave_checks import canonical,exact_equal,pointer,exact_number,validate_check,evaluate_check

MESSAGES={
 'INVALID_REQUEST':'The request needs a valid plan and at least one explicit result check.',
 'INVALID_CATALOG':'The capability catalog has an invalid format.',
 'STALE_CAPABILITIES':'The capability observations have expired or have an invalid timestamp.',
 'STALE_REGISTRY_SOURCE':'The registered capability source needs a freshness recheck.',
 'OPERATION_NOT_REGISTERED':'The operation and engine mapping is absent from the catalog.',
 'ADAPTER_UNAVAILABLE':'The selected operation has no ready execution adapter.',
 'PROGRAM_NOT_REGISTERED':'The native program reference is absent from the catalog.',
 'RUNTIME_HASH_MISMATCH':'The receipt names a different runtime version.',
 'PROGRAM_HASH_MISMATCH':'The receipt names a different native program version.',
 'RECEIPTS_REQUIRED':'Execution receipts are required to verify results.',
 'DEPENDENCY_RECEIPT_MISMATCH':'A dependency has an invalid receipt or a different result hash.',
 'INVOCATION_MISMATCH':'The receipt belongs to a different plan or different arguments.',
 'RESULT_ARTIFACT_INVALID':'The result artifact cannot be matched to its receipt.',
 'SOURCE_ARTIFACT_INVALID':'A source artifact cannot be matched to its declared identity.',
 'DEPENDENT_SOURCE_DROPPED':'Source lineage from a consumed parent result was dropped.',
 'REQUIRED_SOURCE_MISSING':'A source required by the request is missing from the receipt.',
 'RESULT_NOT_COMPLETE':'The engine status fails the request completion policy.',
 'REQUEST_CHECK_FAILED':'An explicit result assertion failed.',
 'REQUEST_CHECK_UNRESOLVED':'A request check awaits a verified input result.',
 'ADAPTER_RUNTIME_UNQUALIFIED':'The adapter is unqualified for the observed runtime version.',
 'PROGRAM_UNAVAILABLE':'The registered native program is unavailable or its artifact changed.',
}


def digest_json(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(65536),b''):h.update(chunk)
    return h.hexdigest()


def inside(root,name):
    if not isinstance(name,str) or not name:raise ValueError('Artifact path required')
    path=(root/name).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('Artifact leaves declared root')
    if path.stat().st_size>16*1024*1024:raise ValueError('Artifact exceeds 16 MiB bound')
    return path


def verify(request,catalog,receipts=None,root=Path('.'),now=None,plan_only=False):
    now=time.time() if now is None else now
    issues=[]; checked=[]; outputs={}; valid_receipts={}; sources={}
    def issue(code,step=None):issues.append({'code':code,'message':MESSAGES.get(code,code.replace('_',' ').capitalize()+'.'),**({'step':step} if step else {})})
    registry=catalog.get('registry',{}) if isinstance(catalog,dict) else {}
    if not isinstance(registry,dict):registry={}
    report={'version':'weave.verification.v1','passed':False,'scope':'Explicit request checks and hash-bound receipt consistency',
            'registry_mode':registry.get('mode','snapshot'),'data_class':catalog.get('data_class','unspecified') if isinstance(catalog,dict) else 'unspecified',
            'checks':checked,'issues':issues,'engine_execution_proven':False,'stage':'preflight' if plan_only else 'results','results_verified':False,'step_readiness':[]}
    try:
        if not isinstance(request,dict) or request.get('version')!='weave.request.v1':raise ValueError('Request version')
        compiled=compile_plan(request['plan'])
        checks=request['checks']
        if not isinstance(checks,list) or not checks or len(checks)>128:raise ValueError('Expected 1..128 request checks')
        if type(request.get('require_complete',True)) is not bool:raise ValueError('Completion policy must be boolean')
        if not isinstance(request.get('sources',[]),list) or len(request.get('sources',[]))>128:raise ValueError('Source list required')
        required=request.get('required_sources',{})
        if not isinstance(required,dict) or any(not isinstance(k,str) or not isinstance(v,list) or any(not isinstance(x,str) for x in v) for k,v in required.items()):raise ValueError('Source requirements invalid')
        if not set(required).issubset({s['id'] for s in compiled['steps']}):raise ValueError('Unknown source requirement target')
        for check in checks:validate_check(check,{s['id'] for s in compiled['steps']})
        report['planned_checks']=len(checks)
        report['plan_sha256']=digest_json(request['plan'])
        report['request_sha256']=digest_json(request)
        purposes={'search':'Locate matching records.','read':'Inspect source contents.','aggregate':'Group and summarize rows.','calculate':'Compute exact values.','infer':'Apply stated rules.','solve':'Evaluate finite alternatives.'}
        report['tool_choices']=[{'step':s['id'],'engine':s['engine'],'purpose':purposes[s['op']]} for s in compiled['steps']]
    except (KeyError,TypeError,ValueError,AttributeError):
        issue('INVALID_REQUEST');return finish(report)
    if not isinstance(catalog,dict) or catalog.get('version')!='weave.capabilities.v1':
        issue('INVALID_CATALOG');return finish(report)
    if 'registry' in catalog and not isinstance(catalog['registry'],dict):issue('INVALID_CATALOG');return finish(report)
    observed=catalog.get('observed_at')
    if type(observed) not in (int,float) or (type(observed) is float and not math.isfinite(observed)) or now-observed>3600 or observed>now+60:
        issue('STALE_CAPABILITIES')
    if registry.get('mode')=='live' and registry.get('freshness')!='CURRENT':
        issue('STALE_REGISTRY_SOURCE')
    operations=catalog.get('operations',{})
    if not isinstance(operations,dict):issue('INVALID_CATALOG');return finish(report)
    catalog_ready=not issues
    for step in compiled['steps']:
        before=len(issues)
        cap=operations.get(step['op'],{})
        if not isinstance(cap,dict) or cap.get('engine')!=step['engine']:
            issue('OPERATION_NOT_REGISTERED',step['id']);report['step_readiness'].append({'step':step['id'],'ready':False});continue
        if cap.get('installed') is not True or cap.get('available') is not True or cap.get('adapter_ready') is not True:issue('ADAPTER_UNAVAILABLE',step['id'])
        if cap.get('adapter_ready') is True and (not isinstance(cap.get('runtime_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',cap['runtime_sha256']) or cap.get('qualified_runtime_sha256')!=cap['runtime_sha256']):issue('ADAPTER_RUNTIME_UNQUALIFIED',step['id'])
        if step['op']=='search':
            modes=cap.get('modes',[])
            if not isinstance(modes,list) or any(not isinstance(x,str) for x in modes) or not set(step['args']['modes']).issubset(modes):issue('SEARCH_MODE_UNSUPPORTED',step['id'])
        else:
            programs=cap.get('programs',{})
            if not isinstance(programs,dict) or step['args']['program_ref'] not in programs:issue('PROGRAM_NOT_REGISTERED',step['id'])
            else:
                program=programs[step['args']['program_ref']]
                if not isinstance(program,dict) or program.get('available') is not True or not isinstance(program.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',program['sha256']):issue('PROGRAM_UNAVAILABLE',step['id'])
        report['step_readiness'].append({'step':step['id'],'ready':catalog_ready and len(issues)==before})
    for source in request.get('sources',[]):
        try:
            if not isinstance(source,dict) or any(not isinstance(source.get(k),str) or not source[k] for k in ('id','origin_id','path','sha256')):raise ValueError('Source contract')
            if source['id'] in sources:raise ValueError('Duplicate source ID')
            if not isinstance(source['origin_id'],str) or not source['origin_id']:raise ValueError('Origin required')
            if file_digest(inside(root,source['path']))!=source['sha256']:raise ValueError('Source hash')
            sources[source['id']]=source
        except (KeyError,TypeError,ValueError,OSError):issue('SOURCE_ARTIFACT_INVALID')
    for ident,ids in request.get('required_sources',{}).items():
        if not set(ids)<=set(sources):issue('REQUIRED_SOURCE_NOT_DECLARED',ident)
    if any(i['code'] in ('SOURCE_ARTIFACT_INVALID','REQUIRED_SOURCE_NOT_DECLARED') for i in issues):
        for item in report['step_readiness']:item['ready']=False
    if plan_only:
        report['passed']=not issues
        return finish(report)
    if not isinstance(receipts,list):
        issue('RECEIPTS_REQUIRED');return finish(report)
    by_id={}
    for receipt in receipts:
        if not isinstance(receipt,dict) or not isinstance(receipt.get('step_id'),str):issue('INVALID_RECEIPT');continue
        ident=receipt['step_id']
        if ident in by_id:issue('DUPLICATE_RECEIPT',ident)
        by_id[ident]=receipt
    expected={s['id'] for s in compiled['steps']}
    for extra in set(by_id)-expected:issue('UNEXPECTED_RECEIPT',extra)
    for step in compiled['steps']:
        ident=step['id']; receipt=by_id.get(ident)
        if receipt is None:issue('RECEIPT_MISSING',ident);continue
        before=len(issues)
        cap=operations.get(step['op'],{})
        if not isinstance(cap,dict):cap={}
        if receipt.get('engine')!=step['engine'] or receipt.get('op')!=step['op']:issue('RECEIPT_ENGINE_MISMATCH',ident)
        if receipt.get('plan_sha256')!=report['plan_sha256'] or receipt.get('args_sha256')!=digest_json(step['args']):issue('INVOCATION_MISMATCH',ident)
        if receipt.get('executed') is not True:issue('EXECUTION_NOT_REPORTED',ident)
        status=receipt.get('native_status')
        completion=receipt.get('completion_state',status)
        if not isinstance(status,str) or not status or len(status)>256 or completion not in ('COMPLETE','INCOMPLETE','FAILED'):issue('NATIVE_STATUS_INVALID',ident)
        if status in ('COMPLETE','INCOMPLETE','FAILED') and completion!=status:issue('COMPLETION_STATUS_MISMATCH',ident)
        if type(receipt.get('incomplete')) is not bool or receipt.get('incomplete')!=(completion=='INCOMPLETE'):issue('COMPLETION_STATUS_MISMATCH',ident)
        if completion=='FAILED' or (completion=='INCOMPLETE' and request.get('require_complete',True)):issue('RESULT_NOT_COMPLETE',ident)
        expected_inputs={dep:by_id[dep].get('result_sha256') for dep in step['inputs'] if dep in by_id}
        if receipt.get('input_hashes')!=expected_inputs or any(dep not in valid_receipts for dep in step['inputs']):issue('DEPENDENCY_RECEIPT_MISMATCH',ident)
        runtime_hash=cap.get('runtime_sha256')
        if not isinstance(runtime_hash,str) or len(runtime_hash)!=64 or receipt.get('runtime_sha256')!=runtime_hash:issue('RUNTIME_HASH_MISMATCH',ident)
        if step['op']!='search':
            program=cap.get('programs',{}).get(step['args']['program_ref'],{}) if isinstance(cap.get('programs',{}),dict) else {}
            if not isinstance(program,dict) or not program.get('sha256') or receipt.get('program_sha256')!=program['sha256']:issue('PROGRAM_HASH_MISMATCH',ident)
        source_ids=receipt.get('source_ids'); origins=receipt.get('origin_ids')
        if not isinstance(source_ids,list) or any(not isinstance(x,str) or x not in sources for x in source_ids):issue('SOURCE_BINDING_INVALID',ident)
        elif len(source_ids)!=len(set(source_ids)) or not exact_equal(origins,sorted({sources[x]['origin_id'] for x in source_ids})):issue('ORIGIN_BINDING_INVALID',ident)
        else:
            required=request.get('required_sources',{}).get(ident,[])
            if not isinstance(required,list) or not set(required).issubset(source_ids):issue('REQUIRED_SOURCE_MISSING',ident)
            inherited={s for dep in step['inputs'] if dep in valid_receipts for s in valid_receipts[dep]['source_ids']}
            if not inherited.issubset(source_ids):issue('DEPENDENT_SOURCE_DROPPED',ident)
        elapsed=receipt.get('elapsed_ms')
        if type(elapsed) not in (int,float) or (type(elapsed) is float and not math.isfinite(elapsed)) or elapsed<0:issue('INVALID_TIMING',ident)
        if not isinstance(receipt.get('coverage'),dict):issue('COVERAGE_REQUIRED',ident)
        try:
            artifact=inside(root,receipt['result_path'])
            if file_digest(artifact)!=receipt['result_sha256']:raise ValueError('Result hash')
            result=json.loads(artifact.read_text(encoding='utf-8'))
            canonical(result)
        except (KeyError,TypeError,ValueError,OSError):issue('RESULT_ARTIFACT_INVALID',ident);continue
        if len(issues)==before:
            outputs[ident]=result; valid_receipts[ident]=receipt
    for i,check in enumerate(checks):
        outcome=evaluate_check(check,outputs,valid_receipts,sources)
        outcome['index']=i;checked.append(outcome)
        if not outcome['passed']:issue('REQUEST_CHECK_UNRESOLVED' if outcome['status']=='NOT_EVALUATED' else 'REQUEST_CHECK_FAILED',check['step'])
    report['valid_receipts']=len(valid_receipts)
    report['expected_receipts']=len(compiled['steps'])
    report['native_states']={k:r.get('native_status') for k,r in by_id.items()}
    report['completion_states']={k:r.get('completion_state',r.get('native_status')) for k,r in by_id.items()}
    report['passed']=not issues
    report['results_verified']=report['passed']
    return finish(report)


def finish(report):
    preflight=report.get('stage')=='preflight'
    report['status']=('PREFLIGHT_READY' if report['passed'] else 'PREFLIGHT_BLOCKED') if preflight else ('CHECKS_PASSED' if report['passed'] else 'CHECKS_FAILED')
    report['counts']={'checks_passed':sum(c['passed'] for c in report['checks']),
                      'checks_failed':sum(c.get('status')=='FAILED' for c in report['checks']),
                      'checks_not_evaluated':sum(c.get('status')=='NOT_EVALUATED' for c in report['checks']),
                      'ready_steps':sum(s['ready'] for s in report['step_readiness']),
                      'steps':len(report['step_readiness'])}
    repairs={'ADAPTER_UNAVAILABLE':'Bind and qualify the selected operation adapter.',
             'ADAPTER_RUNTIME_UNQUALIFIED':'Qualify the adapter against the current runtime hash.',
             'PROGRAM_NOT_REGISTERED':'Register the intended native program and its hash.',
             'PROGRAM_UNAVAILABLE':'Refresh or restore the registered program artifact.',
             'STALE_CAPABILITIES':'Refresh observations through the live register.',
             'DEPENDENCY_RECEIPT_MISMATCH':'Use the checked parent result hash for this dependency.',
             'REQUEST_CHECK_FAILED':'Inspect the failed assertion reason and correct its result.',
             'REQUEST_CHECK_UNRESOLVED':'Supply a valid result receipt for the referenced step.'}
    seen=set();report['actions']=[]
    for item in report['issues']:
        key=(item['code'],item.get('step'))
        if key in seen:continue
        seen.add(key)
        report['actions'].append({'code':item['code'],'step':item.get('step'),'instruction':repairs.get(item['code'],'Review the named contract or artifact binding.')})
    if report['passed']:
        report['explanation']='The plan and catalog are ready; result checks await execution receipts.' if preflight else str(len(report['checks']))+' request checks passed against '+str(report.get('valid_receipts',0))+' bound receipts.'
    else:report['explanation']=' '.join(dict.fromkeys(i['message'] for i in report['issues']))
    return report


def append_memory(path,report):
    """One exclusive append; retain only hashes and codes, never source contents."""
    row={'version':'weave.feedback.v1','time':time.time(),'request_sha256':report.get('request_sha256'),
         'plan_sha256':report.get('plan_sha256'),'report_sha256':digest_json(report),'passed':report['passed'],
         'stage':report.get('stage','results'),'issue_codes':sorted({i['code'] for i in report['issues']}),'checked_assertions':len(report['checks']),
         'failure_kinds':sorted({c['kind'] for c in report['checks'] if c.get('status')=='FAILED'}),
         'failure_reasons':sorted({c['reason'] for c in report['checks'] if c.get('status')=='FAILED'}),
         'data_class':report.get('data_class') if report.get('data_class') in ('operational','synthetic','case_private') else 'unspecified'}
    lock_path=Path(str(path)+'.lock')
    with lock_path.open('a+b') as lock:
        if os.name=='nt':
            import msvcrt
            if lock_path.stat().st_size==0:lock.write(b'0');lock.flush()
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX)
        try:
            with Path(path).open('a',encoding='utf-8') as f:
                f.write(canonical(row)+'\n');f.flush();os.fsync(f.fileno())
        finally:
            if os.name=='nt':lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request',type=Path)
    parser.add_argument('--plan-only',action='store_true',help='Check plan/catalog/source readiness without result receipts')
    parser.add_argument('--summary',action='store_true',help='Print compact status, counts and explanation')
    parser.add_argument('--catalog',type=Path,help='Use an explicit catalog snapshot; omit to load the local capability file')
    parser.add_argument('--receipts',type=Path)
    parser.add_argument('--root',type=Path,default=Path('.'))
    parser.add_argument('--out',type=Path)
    parser.add_argument('--memory',type=Path,help='Append checked hashes and issue codes to this JSONL')
    args=parser.parse_args()
    if args.plan_only and args.receipts:parser.error('--plan-only accepts no execution receipts')
    try:
        from weave_registry import fetch_catalog
        request=json.loads(args.request.read_text(encoding='utf-8'))
        catalog=json.loads(args.catalog.read_text(encoding='utf-8')) if args.catalog else fetch_catalog()
        if args.catalog and isinstance(catalog,dict):catalog.setdefault('registry',{})['mode']='snapshot'
        receipts=json.loads(args.receipts.read_text(encoding='utf-8')) if args.receipts else None
        report=verify(request,catalog,receipts,args.root,plan_only=args.plan_only)
        if args.memory:append_memory(args.memory,report)
        if args.out:
            with args.out.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
        else:print(json.dumps({k:report[k] for k in ('status','stage','results_verified','counts','explanation')} if args.summary else report,indent=2))
        return 0 if report['passed'] else 1
    except (OSError,ValueError,TypeError,subprocess.SubprocessError) as exc:
        parser.exit(2,str(exc)+'\n')


if __name__=='__main__':raise SystemExit(main())
