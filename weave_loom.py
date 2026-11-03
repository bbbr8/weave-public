"""Native Loom search/read adapter over bounded synthetic corpus programs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from weave_verify import digest_json,file_digest,verify


def validate(program):
    if not isinstance(program,dict) or set(program)!={'version','documents','query','top_k','ranker'} or program['version']!='weave.loom.corpus.v1':
        raise ValueError('Expected weave.loom.corpus.v1 program')
    if not isinstance(program['query'],str) or not program['query'].strip() or len(program['query'])>256:raise ValueError('Bounded query text required')
    if type(program['top_k']) is not int or not 1<=program['top_k']<=50:raise ValueError('top_k must be 1..50')
    if program['ranker'] not in ('hybrid','bm25','overlap'):raise ValueError('Supported native ranker required')
    docs=program['documents'];ids=set()
    if not isinstance(docs,list) or not 1<=len(docs)<=64:raise ValueError('Expected 1..64 documents')
    for doc in docs:
        if not isinstance(doc,dict) or set(doc)!={'id','origin_id','title','text'}:raise ValueError('Document fields')
        if not isinstance(doc['id'],str) or not re.fullmatch('[a-z][a-z0-9_]{0,31}',doc['id']) or doc['id'] in ids:raise ValueError('Unique short document IDs required')
        ids.add(doc['id'])
        for name,maximum in [('origin_id',64),('title',256),('text',4096)]:
            if not isinstance(doc[name],str) or len(doc[name])>maximum or (name=='origin_id' and not doc[name]):raise ValueError('Bounded source text required')
    return program


def row(doc):
    return {'id':doc['id'],'title':doc['title'],'text':doc['text'],
            'locator':'synthetic:'+doc['id'],'metadata':{'origin_id':doc['origin_id']},'fields':{}}


def expected_document(doc):
    value=row(doc)
    content_hash=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return dict(value,content_hash=content_hash)


def validate_native(program,native,documents):
    """Check source contents independently of native normalization and hashing."""
    by_id={d['id']:d for d in program['documents']}
    if not isinstance(native,dict) or native.get('schema')!='surd.search.results.v1' or native.get('query')!=program['query'] or native.get('mode')!=program['ranker'] or native.get('k')!=program['top_k']:
        raise ValueError('Native search invocation mismatch')
    if native.get('status') not in ('ok','no_match','no_documents','empty_query'):raise ValueError('Unknown native search status')
    hits=native.get('hits');matched=native.get('matched_documents')
    if not isinstance(hits,list) or type(matched) is not int or not len(hits)<=matched<=len(by_id) or len(hits)>program['top_k']:
        raise ValueError('Native coverage mismatch')
    if (native['status']=='ok')!=bool(hits):raise ValueError('Native status/hit disagreement')
    if not isinstance(documents,list) or len(documents)!=len(hits):raise ValueError('Read coverage mismatch')
    seen=set()
    for rank,(hit,doc) in enumerate(zip(hits,documents),1):
        ident=hit.get('id')
        if ident not in by_id or ident in seen or hit.get('rank')!=rank:raise ValueError('Unknown, duplicate or misranked hit')
        seen.add(ident);expected=expected_document(by_id[ident]);content_hash=expected['content_hash']
        if digest_json(doc)!=digest_json(expected):raise ValueError('Native read differs from supplied source')
        if hit.get('content_hash')!=content_hash or hit.get('metadata')!=expected['metadata'] or hit.get('locator')!=expected['locator'] or hit.get('title')!=expected['title']:
            raise ValueError('Native hit source identity changed')
        snippet=hit.get('snippet',{});start,end=snippet.get('start'),snippet.get('end')
        if type(start) is not int or type(end) is not int or not 0<=start<=end<=len(expected['text']) or snippet.get('text')!=expected['text'][start:end]:raise ValueError('Native snippet changed')
    return [hit['id'] for hit in hits]


def runtime_fingerprint(runtime):
    folder=Path(runtime).resolve().parent
    return {name:file_digest(folder/name) for name in ['loom.py','surd.py','surd_search.py','surd_search_core.py','surd_stemmer.py']}


def run(program_path,runtime,output):
    program_path,runtime,output=Path(program_path),Path(runtime),Path(output)
    raw=program_path.read_bytes()
    if len(raw)>512*1024:raise ValueError('Program exceeds 512 KiB')
    program=validate(json.loads(raw));output.mkdir(exist_ok=False)
    def save(name,value):
        with (output/name).open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2)
    (output/'program.json').write_bytes(raw)
    for doc in program['documents']:save(doc['id']+'.source.json',doc)
    bridge=Path(__file__).with_name('weave_loom_native.py');bridge_sha=file_digest(bridge)
    native_input={'rows':[row(d) for d in program['documents']],**{k:program[k] for k in ['query','top_k','ranker']}}
    save('native-input.json',native_input);input_sha=file_digest(output/'native-input.json')
    fingerprint=runtime_fingerprint(runtime);pin=digest_json(fingerprint)
    command=[sys.executable,str(bridge),str(runtime),str((output/'native-input.json').resolve()),str(output.resolve())]
    proc=subprocess.run(command,capture_output=True,text=True,timeout=10,check=False)
    save('invocation.json',{'argv':command,'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr})
    if proc.returncode:raise ValueError('Native Loom component failed: '+proc.stderr[-500:])
    if runtime_fingerprint(runtime)!=fingerprint or file_digest(bridge)!=bridge_sha or program_path.read_bytes()!=raw or file_digest(output/'native-input.json')!=input_sha:
        raise ValueError('Runtime, bridge or input changed during execution')
    for name in ['native-search.json','native-read.json']:
        if (output/name).stat().st_size>2*1024*1024:raise ValueError('Native artifact exceeds bound')
    native=json.loads((output/'native-search.json').read_text());documents=json.loads((output/'native-read.json').read_text())
    selected=validate_native(program,native,documents)
    timing=json.loads((output/'native-timing.json').read_text())
    source_ids=[d['id'] for d in program['documents']];origins=sorted({d['origin_id'] for d in program['documents']})
    selected_origins=sorted({d['metadata']['origin_id'] for d in documents})
    search_result={'document_ids':selected,'corpus_size':len(source_ids),'matched_documents':native['matched_documents'],'returned_documents':len(selected)}
    read_result={'document_ids':selected,'documents':documents,'independent_origins':len(selected_origins),'origin_ids':selected_origins}
    save('search-result.json',search_result);save('read-result.json',read_result);save('runtime-fingerprint.json',fingerprint)
    plan={'version':'weave.v1','steps':[
        {'id':'matches','op':'search','inputs':[],'args':{'query':program['query'],'modes':['exact'],'top_k':program['top_k']}},
        {'id':'contents','op':'read','inputs':['matches'],'args':{'program_ref':'loom/selected-documents-v1'}}]}
    program_sha=file_digest(output/'program.json')
    sources=[{'id':d['id'],'origin_id':d['origin_id'],'path':d['id']+'.source.json','sha256':file_digest(output/(d['id']+'.source.json'))} for d in program['documents']]
    checks=[{'kind':'equals','step':'matches','pointer':'/corpus_size','value':len(source_ids)},
            {'kind':'range','step':'matches','pointer':'/matched_documents','minimum':len(selected),'maximum':len(source_ids)},
            {'kind':'unchanged','step':'contents','pointer':'/document_ids','baseline_step':'matches','baseline_pointer':'/document_ids'},
            {'kind':'equals','step':'contents','pointer':'/documents','value':[expected_document(next(d for d in program['documents'] if d['id']==i)) for i in selected]},
            {'kind':'receipt_status','step':'matches','value':native['status'],'completion_state':'COMPLETE'},
            {'kind':'receipt_status','step':'contents','value':'document_returned','completion_state':'COMPLETE'}]
    if selected:checks.append({'kind':'origin_count','step':'contents','pointer':'/independent_origins','source_ids':selected})
    else:checks.append({'kind':'equals','step':'contents','pointer':'/independent_origins','value':0})
    request={'version':'weave.request.v1','plan':plan,'sources':sources,'required_sources':{'matches':source_ids,'contents':source_ids},'checks':checks}
    catalog={'version':'weave.capabilities.v1','data_class':'synthetic','observed_at':time.time(),'registry':{'mode':'native-adapter-snapshot'},'operations':{}}
    for op in ['search','read']:
        catalog['operations'][op]={'engine':'loom','installed':True,'available':True,'adapter_ready':True,'runtime_sha256':pin,'qualified_runtime_sha256':pin,
                                   'modes':['exact'],'programs':{'loom/selected-documents-v1':{'sha256':program_sha,'available':True}}}
    receipts=[]
    for step,path,status,elapsed in [(plan['steps'][0],'search-result.json',native['status'],timing['search_ms']),
                                     (plan['steps'][1],'read-result.json','document_returned',timing['read_ms'])]:
        receipts.append({'step_id':step['id'],'engine':'loom','op':step['op'],'executed':True,'native_status':status,
            'completion_state':'COMPLETE','incomplete':False,'elapsed_ms':elapsed,
            'coverage':{'corpus_documents':len(source_ids),'matched_documents':native['matched_documents'],'returned_documents':len(selected),'top_k_truncated':native['matched_documents']>len(selected)},
            'plan_sha256':digest_json(plan),'args_sha256':digest_json(step['args']),'runtime_sha256':pin,'program_sha256':program_sha,
            'source_ids':source_ids,'origin_ids':origins,'input_hashes':{r['step_id']:r['result_sha256'] for r in receipts},
            'result_path':path,'result_sha256':file_digest(output/path),'adapter_sha256':bridge_sha})
    report=verify(request,catalog,receipts,output)
    for name,value in [('request.json',request),('catalog.json',catalog),('receipts.json',receipts),('verification.json',report)]:save(name,value)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('program',type=Path)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    try:
        report=run(args.program,args.runtime,args.out)
        print(json.dumps({'passed':report['passed'],'valid_receipts':report.get('valid_receipts'),'checks':len(report['checks'])}))
        return 0 if report['passed'] else 1
    except (ValueError,TypeError,KeyError,OSError,subprocess.SubprocessError) as exc:parser.exit(2,str(exc)+'\n')


if __name__=='__main__':raise SystemExit(main())
