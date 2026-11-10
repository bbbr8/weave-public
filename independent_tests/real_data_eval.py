"""External real-data evaluation. Gold programs are supplied, not predicted.

No model calls. FinQA questions/gold are never placed in the retrieval corpus.
Retrieval, oracle consistency, supplied-program execution, and snippet integrity
are separate measurements; no combined 'AI accuracy' is reported.
"""
import argparse
import ast
from collections import Counter
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import re
import statistics
import sys
import time
import zipfile

FINQA_REF = '0f16e2867befa6840783e58be38c9efb9229d742'
FINQA_BLOB = '59958c7c3bb3b21f4dff6bc912a0fe0ae710aee0'
PLAN = dict(version=2, data_class='external_real_report_and_scientific_data',
    finqa_split='public test, all records', finqa_ref=FINQA_REF,
    finqa_expected_blob=FINQA_BLOB,
    retrieval=dict(configuration='unmodified SearchIndex defaults', k=[1,3,5,10],
                   scopes=['one supplied report page','all test report pages'],
                   corpus='pre_text + post_text + all table rows, including row zero; no QA fields'),
    execution=dict(input='dataset gold program and table, supplied explicitly',
                   oracle='independent Fraction arithmetic; five-place comparison',
                   operators=['add','subtract','multiply','divide','greater',
                              'table_sum','table_average','table_min','table_max'],
                   exclusions='exp is explicitly unsupported; adapters are not engines',
                   tolerance='absolute 0.0000050001 against five-place gold'),
    scientific=dict(datasets=['scifact','nfcorpus'], split='BEIR test qrels', k=10),
    limitations=['not end-to-end QA','no semantic encoder','no LLM',
                 'FinQA source extraction is supplied by dataset, not PDF/OCR tested',
                 'existing public datasets may have influenced project development'])


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str)+'\n')


def read_dataset(url, path, expected_blob=None):
    if not path.is_file():
        raise FileNotFoundError('Supply the pinned dataset file locally: '+str(path))
    b=path.read_bytes()
    blob=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
    if expected_blob and blob != expected_blob:
        raise ValueError('upstream content changed: '+url)
    return dict(url=url, bytes=len(b), sha256=hashlib.sha256(b).hexdigest(), git_blob=blob)


def number(s):
    s=str(s).replace(',','').strip()
    if s.startswith('const_'):
        s=s[6:]
        if s=='m1':s='-1'
    percent=s.endswith('%')
    if percent:s=s[:-1]
    return Fraction(s)/(100 if percent else 1)


def dec(x):
    with localcontext() as c:
        c.prec=70
        return Decimal(x.numerator)/Decimal(x.denominator)


def literal(x):
    # Fraction literals preserve original finite decimals and exact division.
    return '('+str(x.numerator)+' / '+str(x.denominator)+')'


class Unsupported(Exception):pass


def compile_program(item):
    program=item['qa']['program']
    matches=list(re.finditer(r'([a-z_]+)\(([^()]*)\)',program))
    if re.sub(r'[\s,]','',re.sub(r'[a-z_]+\([^()]*\)','',program)):
        raise Unsupported('unparsed program: '+program)
    exact=[]; tally=[]; weave=[]; ops=[]
    for m in matches:
        op=m[1];args=m[2].split(', ')
        if len(args)!=2:raise Unsupported('argument layout')
        ops.append(op)
        def resolve(a):
            return exact[int(a[1:])] if a.startswith('#') else number(a)
        def tref(a):
            return 'v'+a[1:] if a.startswith('#') else literal(number(a))
        if op.startswith('table_'):
            values=next((r[1:] for r in item['table'] if r[0]==args[0]),None)
            if values is None:raise Unsupported('table row absent')
            # Match the published evaluator's documented row normalization.
            vals=[number(v.replace('$','').strip().split('(')[0].strip()) for v in values]
            if not vals:raise Unsupported('empty table row')
            if op=='table_sum':z=sum(vals);expr='sum(['+','.join(map(literal,vals))+'])'
            elif op=='table_average':z=sum(vals)/len(vals);expr='sum(['+','.join(map(literal,vals))+']) / '+str(len(vals))
            elif op=='table_min':z=min(vals);expr='min(['+','.join(map(literal,vals))+'])'
            elif op=='table_max':z=max(vals);expr='max(['+','.join(map(literal,vals))+'])'
            else:raise Unsupported(op)
            # Weave only documents + - * /; table selection is unsupported.
            w=None
        else:
            a,b=map(resolve,args)
            if op=='add':z=a+b;symbol='+'
            elif op=='subtract':z=a-b;symbol='-'
            elif op=='multiply':z=a*b;symbol='*'
            elif op=='divide':z=a/b;symbol='/'
            elif op=='greater':z=a>b;symbol='>'
            else:raise Unsupported(op)
            expr='('+tref(args[0])+' '+symbol+' '+tref(args[1])+')'
            w=None if op=='greater' else dict(op=symbol,args=args)
        exact.append(z);tally.append('let v'+str(len(exact)-1)+' = '+expr);weave.append(w)
    if not exact:raise Unsupported('empty program')
    return dict(exact=exact, tally='\n'.join(tally)+'\nv'+str(len(exact)-1),weave=weave,ops=ops)


def close(actual, expected):
    if isinstance(expected,bool):
        if isinstance(actual,str):return actual.lower()==('yes' if expected else 'no')
        return actual is expected
    if isinstance(actual,bool):return False
    return abs(Decimal(str(actual))-dec(expected))<=Decimal('0.0000050001')


def finance_execution(data, tally_path, weave_path, out):
    sys.path.insert(0,str(tally_path));import tally as T
    sys.path.insert(0,str(weave_path));from reasoning_layer.core import calculate
    results=[];counts=Counter()
    for item in data:
        row=dict(id=item['id'],question=item['qa']['question'],gold=item['qa']['exe_ans'],
                 program=item['qa']['program'])
        try:p=compile_program(item)
        except Exception as e:
            row.update(adapter_status='unsupported',adapter_reason=type(e).__name__+': '+str(e))
            counts['adapter_unsupported']+=1;results.append(row);continue
        row.update(adapter_status='supported',steps=len(p['ops']),operators=p['ops'],
                   oracle=str(p['exact'][-1]),tally_program=p['tally'])
        row['gold_consistent']=close(row['gold'],p['exact'][-1]);counts['gold_consistent']+=row['gold_consistent']
        counts['supported']+=1;counts['multistep']+=len(p['ops'])>1
        for op in p['ops']:counts['op_'+op]+=1
        try:
            got=T.strip(T.Interp(out=io.StringIO()).run(p['tally']))
            row['tally']=dict(actual=str(got),matches_oracle=close(got,p['exact'][-1]))
            counts['tally_pass']+=row['tally']['matches_oracle']
        except Exception as e:row['tally']=dict(error=type(e).__name__+': '+str(e));counts['tally_error']+=1
        if all(p['weave']):
            counts['weave_supported']+=1
            try:
                ws=[]
                for step in p['weave']:
                    args=[ws[int(a[1:])] if a.startswith('#') else dec(number(a)) for a in step['args']]
                    ws.append(calculate(dict(operands=[dict(name='a',value=str(args[0])),dict(name='b',value=str(args[1]))],formula='a '+step['op']+' b')))
                row['weave']=dict(actual=str(ws[-1]),matches_oracle=close(ws[-1],p['exact'][-1]))
                counts['weave_pass']+=row['weave']['matches_oracle']
            except Exception as e:row['weave']=dict(error=type(e).__name__+': '+str(e));counts['weave_error']+=1
        else:row['weave']=dict(status='unsupported_operator');counts['weave_unsupported']+=1
        results.append(row)
    dump(out/'finqa-execution.json',dict(summary=dict(counts),results=results))
    print('FINQA_EXECUTION '+json.dumps(dict(counts)),flush=True)
    return dict(counts)


def corpus_rows(item):
    # Correct upstream template uses header[0], never the gold question/answer.
    rows=[]
    for i,t in enumerate(item['pre_text']+item['post_text']):
        rows.append(dict(id='text_'+str(i),text=t))
    table=item['table'];header=table[0]
    for i,row in enumerate(table):
        text=(header[0]+' ' if header[0] else '')+' '.join('the '+row[0]+' of '+h+' is '+v+' ;' for h,v in zip(header[1:],row[1:]))
        rows.append(dict(id='table_'+str(i),text=' '.join(text.split())))
    return rows


def finance_retrieval(data, SearchIndex, out):
    rows=[];local={};seen=set()
    for item in data:
        # Same report page can have several questions; retain each page once.
        page=item['id'].rsplit('-',1)[0]
        rr=corpus_rows(item)
        fingerprint=hashlib.sha256(json.dumps(rr,sort_keys=True).encode()).hexdigest()
        page=page+'~'+fingerprint[:12]
        local[item['id']]=(page,rr)
        if page in seen:continue
        seen.add(page)
        rows.extend(dict(id=page+'::'+r['id'],text=r['text'],metadata=dict(page=page)) for r in rr if r['text'].strip())
    index=SearchIndex(rows);results=[];counts=Counter();coverage=[]
    for item in data:
        page,rr=local[item['id']];gold=set(item['qa']['gold_inds'])
        ids={r['id'] for r in rr if r['text'].strip()}
        if not gold or not gold<=ids:
            counts['gold_index_unresolved']+=1
            results.append(dict(id=item['id'],status='gold_index_unresolved',gold=sorted(gold),missing=sorted(gold-ids)))
            continue
        counts['evaluated']+=1;counts['multiple_evidence_questions']+=len(gold)>1
        for scope in ['page','global']:
            opts=dict(k=10,explain=False)
            if scope=='page':opts['where']=dict(page=page)
            r=index.search(item['qa']['question'],opts)
            expected={page+'::'+g for g in gold};hits=[h['id'] for h in r['hits']]
            row=dict(id=item['id'],question=item['qa']['question'],scope=scope,gold=sorted(expected),hits=hits)
            for k in [1,3,5,10]:
                found=expected&set(hits[:k]);row['recall'+str(k)]=len(found)/len(expected)
                row['all'+str(k)]=expected<=set(hits[:k]);counts[scope+'_all'+str(k)]+=row['all'+str(k)]
                if k==10:coverage.append((scope,row['recall10']))
            for h in r['hits']:
                d=index.document(h['id']);sn=h['snippet'];counts['snippets_checked']+=1
                counts['snippets_exact']+=d['text'][sn['start']:sn['end']]==sn['text']
            results.append(row)
    summary=dict(counts,documents=len(rows),report_pages=len(seen))
    for scope in ['page','global']:summary[scope+'_mean_recall10']=statistics.mean(v for s,v in coverage if s==scope)
    dump(out/'finqa-retrieval.json',dict(summary=summary,results=results))
    print('FINQA_RETRIEVAL '+json.dumps(summary),flush=True)
    return summary


def scientific(name, path, SearchIndex, out):
    import math
    with zipfile.ZipFile(path) as z:
        docs=[json.loads(x) for x in z.read(name+'/corpus.jsonl').decode().splitlines()]
        queries={q['_id']:q['text'] for q in map(json.loads,z.read(name+'/queries.jsonl').decode().splitlines())}
        gold={}
        for line in z.read(name+'/qrels/test.tsv').decode().splitlines()[1:]:
            q,d,s=line.split('\t');gold.setdefault(q,{})[d]=int(s)
    ix=SearchIndex([dict(id=d['_id'],title=d.get('title',''),text=d['text'],locator='BEIR:'+name+':'+d['_id']) for d in docs])
    rows=[];snippets=0;exact=0
    for qid,rel in sorted(gold.items()):
        r=ix.search(queries[qid],dict(k=10,explain=False));hits=[h['id'] for h in r['hits']]
        positive={d for d,g in rel.items() if g>0};found=positive&set(hits)
        ideal=sum((2**g-1)/math.log2(i+2) for i,g in enumerate(sorted(rel.values(),reverse=True)[:10]))
        dcg=sum((2**rel.get(d,0)-1)/math.log2(i+2) for i,d in enumerate(hits))
        rows.append(dict(qid=qid,query=queries[qid],gold=rel,hits=hits,recall10=len(found)/len(positive),
                         ndcg10=dcg/ideal if ideal else 0,mrr10=next((1/(i+1) for i,d in enumerate(hits) if d in positive),0)))
        for h in r['hits']:
            sn=h['snippet'];snippets+=1;exact+=ix.document(h['id'])['text'][sn['start']:sn['end']]==sn['text']
    summary=dict(documents=len(docs),queries=len(rows),recall10=statistics.mean(r['recall10'] for r in rows),
                 ndcg10=statistics.mean(r['ndcg10'] for r in rows),mrr10=statistics.mean(r['mrr10'] for r in rows),
                 complete_misses=sum(r['recall10']==0 for r in rows),snippets_checked=snippets,snippets_exact=exact)
    dump(out/(name+'.json'),dict(summary=summary,rankings=rows))
    print(name.upper()+' '+json.dumps(summary),flush=True)
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--loom',required=True);p.add_argument('--tally',required=True);p.add_argument('--weave',required=True);p.add_argument('--out',required=True);p.add_argument('--sources',type=Path,required=True,help='Directory containing caller-supplied datasets; no downloads');a=p.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);sources=a.sources.resolve()
    if not sources.is_dir():p.error('--sources must be an existing local directory')
    dump(out/'frozen-plan.json',PLAN)
    sys.path.insert(0,str(Path(a.loom).resolve()/'runtime'));from surd_search import SearchIndex
    manifest=[];base='https://raw.githubusercontent.com/czyssrs/FinQA/'+FINQA_REF+'/'
    manifest.append(read_dataset(base+'dataset/test.json',sources/'finqa-test.json',FINQA_BLOB))
    data=json.loads((sources/'finqa-test.json').read_text())
    # Retain full upstream data only in the downloadable run artifact, not git.
    manifest.append(read_dataset(base+'LICENSE',sources/'FinQA-LICENSE.txt'))
    summary=dict(finqa_total=len(data))
    summary['execution']=finance_execution(data,Path(a.tally).resolve(),Path(a.weave).resolve(),out)
    summary['financial_retrieval']=finance_retrieval(data,SearchIndex,out)
    for name in PLAN['scientific']['datasets']:
        try:
            path=sources/(name+'.zip')
            manifest.append(read_dataset('https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/'+name+'.zip',path))
            summary[name]=scientific(name,path,SearchIndex,out)
        except Exception as e:summary[name]=dict(error=type(e).__name__+': '+str(e));print(name.upper()+'_ERROR '+str(e),flush=True)
    dump(out/'source-manifest.json',manifest);dump(out/'SUMMARY.json',summary)
    print('EVALUATION_COMPLETE '+json.dumps(summary),flush=True)


if __name__=='__main__':main()
