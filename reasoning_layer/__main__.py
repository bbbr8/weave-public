"""python -m reasoning_layer: check, execute, run, direct, route and recover-native."""
import argparse
import json
from pathlib import Path
from .contracts import make_task, route, validate_task
from .core import validate_program
from .model import CodexModel
from .native import MacBackend, ReferenceBackend
from .pipeline import ReasoningLayer, execute_packets
from .curriculum import qualify
from .evaluate import evaluate
from .recovery import resume_staging
from .source_audit import audit_source, reasoning_trace

def main():
    ap=argparse.ArgumentParser(description='Question/source/answer-policy layer around native reasoning languages')
    ap.add_argument('command',choices=['init','check','audit','execute','run','direct','route','recover-native','resume-native','export-curriculum','evaluate'])
    ap.add_argument('input',type=Path);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--backend',choices=['mac','reference'],default='mac');ap.add_argument('--model',default='gpt-6.1-sol');ap.add_argument('--effort',choices=['low','medium','high'],default='high');ap.add_argument('--no-review',action='store_true')
    ap.add_argument('--batch-size',type=int,default=8)
    ap.add_argument('--legacy-source-review',action='store_true',help='Replay pre-0.3 review without whole-source accounting; explicitly recorded')
    args=ap.parse_args()
    if args.command in ['recover-native','resume-native']:
        result=MacBackend().recover(args.input) if args.command=='recover-native' else resume_staging(args.input);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2));print(json.dumps(result));return
    data=json.loads(args.input.read_text(encoding='utf-8-sig'))
    backend=MacBackend() if args.backend=='mac' else ReferenceBackend()
    if args.command=='init':
        result=[make_task(x['id'],x['context'],x['question'],x['labels'],policy=x.get('policy'),data_class=x.get('data_class','public'),operation=x.get('operation','rules')) for x in (data if isinstance(data,list) else [data])]
    elif args.command=='check':
        packets=data if isinstance(data,list) else [data];result={x['task']['id']:validate_program(x['task'],x['program']) for x in packets}
    elif args.command=='execute':
        packets=data if isinstance(data,list) else [data];result=execute_packets([(x['task'],x['program']) for x in packets],backend,args.output)
    elif args.command=='audit':
        packets=data if isinstance(data,list) else [data];result={}
        for x in packets:
            check=validate_program(x['task'],x['program'])
            result[x['task']['id']]=dict(validation=check,source_audit=audit_source(x['task'],x['program'],x.get('source_review')) if check['valid'] else None,reasoning_trace=reasoning_trace(x['task'],x['program']) if check['valid'] else None)
    elif args.command=='route':result={x['id']:route(x) for x in data}
    elif args.command=='export-curriculum':result=[qualify(x['task'],x['program'],x['result'],x['approval'],x['expected']) for x in data]
    elif args.command=='evaluate':result=evaluate(data,args.output,model=args.model,effort=args.effort,backend=args.backend,batch_size=args.batch_size,source_accounting=not args.legacy_source_review)
    else:
        layer=ReasoningLayer(CodexModel(args.model,args.effort),backend,source_accounting=not args.legacy_source_review)
        result=layer.direct(data,args.output,review=not args.no_review) if args.command=='direct' else layer.run(data,args.output,review=not args.no_review)
    if args.command in ['init','check','audit','route','recover-native','export-curriculum']:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'command':args.command,'output':str(args.output),'items':result.get('questions',len(result)) if isinstance(result,dict) else len(result)}))

if __name__=='__main__':main()
