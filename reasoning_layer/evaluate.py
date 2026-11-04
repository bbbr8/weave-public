"""Matched direct/review/native-feedback trial; scoring is a separate operation."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import time
from .contracts import digest,route,runtime_recipe
from .model import CodexModel
from .native import MacBackend,ReferenceBackend
from .pipeline import ReasoningLayer,check_tasks,save
from . import __version__

def evaluate(tasks,folder,*,model='gpt-6.1-sol',effort='high',backend='mac',batch_size=8,source_accounting=True):
    check_tasks(tasks,hosted=True);folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    if not 1<=batch_size<=16:raise ValueError('batch size must be 1..16')
    plan=dict(package_version=__version__,model=model,effort=effort,task_digest=digest(tasks),questions=len(tasks),conditions=['A_direct_once','B_direct_review','C_language_feedback'],source_accounting=source_accounting,batch_size=batch_size,max_simultaneous_model_calls=2,feedback='Own program, deterministic checks and actual execution; no gold',scope='One review maximum; shared native rule interface plus Tally arithmetic; no model-weight changes')
    plan['recipe_digest']=runtime_recipe()
    if (folder/'plan.json').exists() and json.loads((folder/'plan.json').read_text())!=plan:raise ValueError('Run owns a different frozen plan')
    if (folder/'FROZEN.json').exists():
        frozen=json.loads((folder/'FROZEN.json').read_text())
        for name,h in frozen['files'].items():
            if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=h:raise RuntimeError('Frozen run artifact changed: '+name)
        return dict(questions=len(tasks),status='reused_frozen_run',output=str(folder))
    save(folder/'plan.json',plan);save(folder/'tasks.json',tasks)
    started=time.time();jobs=[]
    for i in range(0,len(tasks),batch_size):
        selected=tasks[i:i+batch_size];batch=folder/f'batch-{i//batch_size+1:02d}'
        for mode in ['direct','language']:jobs.append((selected,batch,mode))
    def work(task_batch,batch,mode):
        layer=ReasoningLayer(CodexModel(model,effort),MacBackend() if backend=='mac' else ReferenceBackend(),source_accounting=source_accounting)
        if mode=='direct':result=layer.direct(task_batch,batch/'direct',review=True)
        else:result=layer.run(task_batch,batch/'language',review=True)
        print(json.dumps(dict(batch=batch.name,condition=mode,status='finished',questions=len(task_batch))),flush=True)
        return dict(batch=batch.name,condition=mode,results=result)
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futs=[pool.submit(work,*job) for job in jobs]
        for future in concurrent.futures.as_completed(futs):results.append(future.result())
    if runtime_recipe()!=plan['recipe_digest']:raise RuntimeError('Package source changed during evaluation; retain requests and results')
    files={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*.json') if p.name!='FROZEN.json'}
    save(folder/'FROZEN.json',dict(started_at=started,finished_at=time.time(),plan_digest=digest(plan),tasks_digest=digest(tasks),files=files,status='all_predictions_frozen'))
    return dict(questions=len(tasks),batches=len(jobs)//2,status='all_predictions_frozen',output=str(folder))
