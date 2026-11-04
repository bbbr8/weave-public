"""One initial program, actual execution, and at most one source-based model review."""
from pathlib import Path
import json
from .contracts import ABSTAIN, digest, route, validate_task, runtime_recipe
from .core import validate_program
from .model import BASE, WRITER, REVIEW, PROGRAMS, REVIEWS, ANSWERS, payload, AUDITED_PROGRAMS, AUDITED_REVIEWS, SOURCE_WRITER, SOURCE_REVIEW_INSTRUCTION, audited_payload
from .source_audit import audit_source, reasoning_trace
from . import __version__

def save(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')

def check_tasks(tasks,hosted=False):
    if len({t['id'] for t in tasks})!=len(tasks):raise ValueError('Duplicate task IDs')
    for t in tasks:
        errors=validate_task(t)
        if errors:raise ValueError(t['id']+': '+'; '.join(errors))
        if hosted and {'gold','expected','answer','correct_answer','answer_key'}&set(t):raise ValueError('Scoring fields cannot enter a model task')
        if hosted and t['data_class'] not in ['public','synthetic']:raise ValueError('Hosted model route accepts only caller-declared public/synthetic inputs; case_private stays on its authorized Mac route')

def indexed(rows,key,ids):
    result={r[key]:r for r in rows}
    if len(result)!=len(rows) or set(result)!=set(ids):raise ValueError('Model response IDs do not exactly cover the frozen tasks')
    return result

def execute_packets(packets,backend,folder,accepted=None,uncertainty_only=None,source_reviews=None,require_source_ledger=False):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    checks={};valid=[]
    for t,p in packets:
        check=validate_program(t,p);checks[t['id']]=check
        if check['valid']:valid.append((t,p))
    native=backend.run_many(valid,folder/'native') if valid else {}
    results={}
    for t,p in packets:
        k=t['id'];check=checks[k]
        result=native.get(k,dict(answer=ABSTAIN,state='validation_failed',native=False))
        status='unreviewed' if accepted is None else 'accepted_by_model' if accepted.get(k) else 'declined_by_model'
        answer=result['answer']
        source_check=audit_source(t,p,(source_reviews or {}).get(k)) if check['valid'] else None
        if accepted is not None and not accepted.get(k):
            preserve_unknown=check['valid'] and (uncertainty_only or {}).get(k,False) and result['state']=='undetermined' and answer in ['Unknown','NotMentioned']
            if preserve_unknown:status='preserved_unknown_by_task_policy'
            else:answer=ABSTAIN
        if require_source_ledger and (source_check is None or not source_check['valid'] or (accepted is not None and k not in (source_reviews or {}))):
            answer=ABSTAIN;status='source_review_required'
        results[k]=dict(id=k,question_sha256=t['question_sha256'],program_digest=digest(p),validation=check,execution=result,answer=answer,review_status=status,
                        source_audit=source_check,reasoning_trace=reasoning_trace(t,p) if check['valid'] else None)
    save(folder/'results.json',results)
    return results

class ReasoningLayer:
    def __init__(self,model,backend,*,source_accounting=True):self.model=model;self.backend=backend;self.source_accounting=source_accounting
    def run(self,tasks,folder,review=True):
        check_tasks(tasks,hosted=True);folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
        snapshot=digest(tasks);recipe=runtime_recipe()
        if (folder/'tasks.json').exists() and digest(json.loads((folder/'tasks.json').read_text()))!=snapshot:raise ValueError('Run folder owns different tasks')
        if (folder/'run.json').exists():
            previous=json.loads((folder/'run.json').read_text())
            if previous.get('recipe_digest')!=recipe:raise ValueError('Completed run belongs to different package source; retain it and choose a new output folder')
            if previous.get('package_version')!=__version__:raise ValueError('Completed run belongs to a different layer version; retain it and choose a new output folder')
            if previous.get('task_digest')!=snapshot or previous.get('review')!=review or previous.get('backend')!=self.backend.name or previous.get('source_accounting')!=self.source_accounting:raise ValueError('Completed run settings differ')
            import hashlib
            for name,h in previous['files'].items():
                if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=h:raise RuntimeError('Completed run artifact changed: '+name)
            return json.loads((folder/'results.json').read_text())
        save(folder/'tasks.json',tasks)
        native_tasks=[];direct_tasks=[]
        for t in tasks:
            (direct_tasks if route(t)['operation']=='direct' else native_tasks).append(t)
        results={}
        if native_tasks:
            source_instruction='\n'+SOURCE_WRITER if self.source_accounting else ''
            source_payload=audited_payload(native_tasks) if self.source_accounting else payload(native_tasks)
            save(folder/'source-units.json',source_payload.get('source_units',{}))
            prompt=BASE+'\n'+WRITER+source_instruction+'\n'+json.dumps(source_payload,ensure_ascii=False)
            first=self.model.respond(prompt,AUDITED_PROGRAMS if self.source_accounting else PROGRAMS,folder/'calls'/'write')
            programs=indexed(first['programs'],'task_id',[t['id'] for t in native_tasks])
            initial=execute_packets([(t,programs[t['id']]) for t in native_tasks],self.backend,folder/'attempt-0',require_source_ledger=self.source_accounting)
            save(folder/'initial-programs.json',programs)
            if review:
                compact={k:dict(validation=v['validation'],execution={name:value for name,value in v['execution'].items() if name!='engines'},review_status=v['review_status'],source_audit=v['source_audit'],reasoning_trace=v['reasoning_trace']) for k,v in initial.items()}
                feedback=dict(inputs=source_payload,programs=programs,execution_and_checks=compact)
                revised=self.model.respond(BASE+'\n'+WRITER+'\n'+REVIEW+source_instruction+('\n'+SOURCE_REVIEW_INSTRUCTION if self.source_accounting else '')+'\n'+json.dumps(feedback,ensure_ascii=False),AUDITED_REVIEWS if self.source_accounting else REVIEWS,folder/'calls'/'review')
                reviews=indexed(revised['reviews'],'id',[t['id'] for t in native_tasks])
                accepted={k:v['accepted'] for k,v in reviews.items()}
                uncertainty_only={k:bool(v['issues']) and all(isinstance(x,dict) and x.get('kind')=='insufficient_evidence' for x in v['issues']) for k,v in reviews.items()}
                programs={k:v['program'] for k,v in reviews.items()}
                if any(p['task_id']!=k for k,p in programs.items()):raise ValueError('Review substituted another task')
                source_reviews={k:v.get('source_review') for k,v in reviews.items() if v.get('source_review') is not None}
                results.update(execute_packets([(t,programs[t['id']]) for t in native_tasks],self.backend,folder/'attempt-1',accepted,uncertainty_only,source_reviews,require_source_ledger=self.source_accounting))
                save(folder/'reviews.json',reviews)
            else:results.update(initial)
            save(folder/'final-programs.json',programs)
        if direct_tasks:
            direct=self.direct(direct_tasks,folder/'direct',review=review)
            results.update({k:dict(id=k,answer=v['answer'],execution=dict(state='direct_model_answer',native=False),review_status='direct_review' if review else 'direct_once') for k,v in direct.items()})
        if digest(tasks)!=snapshot:raise RuntimeError('Task inputs changed during run')
        if runtime_recipe()!=recipe:raise RuntimeError('Package source changed during run; retain attempts and choose a new output folder')
        save(folder/'results.json',results)
        import hashlib
        files={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in ['tasks.json','results.json','final-programs.json','initial-programs.json','reviews.json','source-units.json'] if (folder/name).exists()}
        save(folder/'run.json',dict(package_version=__version__,recipe_digest=recipe,files=files,task_digest=snapshot,review=review,source_accounting=self.source_accounting,max_model_passes_per_route=2 if review else 1,backend=self.backend.name,route_decisions={t['id']:route(t) for t in tasks},status='complete'))
        return results
    def direct(self,tasks,folder,review=False):
        check_tasks(tasks,hosted=True);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        prompt=BASE+'\nAnswer directly. Give one allowed label (or numeric answer matching policy), with a brief justification. No program execution.\n'+json.dumps(payload(tasks),ensure_ascii=False)
        first=self.model.respond(prompt,ANSWERS,folder/'calls'/'answer')
        result=indexed(first['answers'],'id',[t['id'] for t in tasks]);save(folder/'initial.json',result)
        if review:
            second=self.model.respond(BASE+'\nReview these direct answers against the original source. Revise only when justified; retain correct answers. No tools or execution feedback.\n'+json.dumps(dict(inputs=payload(tasks),earlier_answers=result),ensure_ascii=False),ANSWERS,folder/'calls'/'review')
            result=indexed(second['answers'],'id',[t['id'] for t in tasks])
        for t in tasks:
            ans=result[t['id']]['answer']
            if t['policy']['mode']!='numeric' and ans not in t['labels']+[ABSTAIN]:raise ValueError('Direct response returned an unsupported label')
        save(folder/'results.json',result)
        return result

