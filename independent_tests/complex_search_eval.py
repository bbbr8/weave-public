"""Larger-corpus retrieval, conversational context, and fictional lifecycle tests.
No LLM or learned semantic model. Programs, metadata and links are supplied.
"""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import random
import re
import sys
import tempfile
import time
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from evidence_search import EvidenceIndex,canonical,sha
from real_data_eval import download,corpus_rows,compile_program,number,literal,close,FINQA_REF

CONV_REF='cf3eed2d5984960bf06bb8145bcea5e80b0222a6'
PLAN=dict(version=1,finqa_ref=FINQA_REF,convfinqa_ref=CONV_REF,
    documents='All FinQA train/dev/test report pages and ConvFinQA dev pages, deduplicated by page plus source content; QA fields never indexed',
    financial_queries='256 FinQA public-test questions with at least two gold evidence rows, ordered by SHA256(id)',
    conversational_queries='All published ConvFinQA dev turns with resolvable original per-turn support labels',
    profiles=['flat10','flat64','expand64','provided_page_expand64'],
    expansion='First ten lexical hits select two parent pages; fixed query-family followups and parent context; 64 records / 64000 chars',
    conversation='Compare last question with prior+current questions; no answers, gold programs or future questions in retrieval query',
    lifecycle='64 seeded fictional scenarios: 14 financial adjustments + 4 informational events, actor receipt, version/account/obligation, conflicting claims, missing dependencies and later import',
    boundaries=['No full natural-language answer generation','No semantic model','Gold arithmetic programs supplied',
                'Synthetic case controls are not real case findings','Changed corpus and backend prohibit comparison with prior headline as model improvement'])


def dump(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str)+'\n')


def page_rows(item):
    rows=corpus_rows(item);page=item.get('filename') or item['id'].rsplit('-',1)[0]
    page=page+'~'+hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()[:12]
    return page,[dict(id=page+'::'+r['id'],parent_id=page,text=r['text'],locator=page+'#'+r['id'],
                     metadata=dict(corpus='financial_reports',page=page,entity=page.split('/')[0],
                                   source_row=r['id'],order=i,data_class='external_report'))
                 for i,r in enumerate(rows) if r['text'].strip()]


def bounded(hits,n=64,chars=64000):
    out=[];used=0
    for h in hits:
        if len(out)<n and used+len(h['text'])<=chars:out.append(h);used+=len(h['text'])
    return out


def score(hits,gold):
    got={h['id'] for h in hits};found=gold&got
    return dict(all_evidence=gold<=got,recall=len(found)/len(gold),precision=len(found)/len(got) if got else 0,
                records=len(hits),chars=sum(len(h['text']) for h in hits),ids=[h['id'] for h in hits])


def aggregate(rows,profiles):
    summary=dict(queries=len(rows))
    for p in profiles:
        xs=[r[p] for r in rows if p in r]
        summary[p]=dict(evaluated=len(xs),all_evidence=sum(r['all_evidence'] for r in xs),
            mean_recall=sum(r['recall'] for r in xs)/len(xs) if xs else None,
            mean_precision=sum(r['precision'] for r in xs)/len(xs) if xs else None,
            mean_records=sum(r['records'] for r in xs)/len(xs) if xs else None)
    return summary


def retrieve_finance(ix,test,out):
    cohort=sorted((x for x in test if len(x['qa']['gold_inds'])>=2),key=lambda x:sha(x['id']))[:256]
    dump(out/'finance-query-plan.json',[dict(id=x['id'],question=x['qa']['question'],gold=x['qa']['gold_inds']) for x in cohort])
    results=[];integrity=Counter()
    for n,item in enumerate(cohort):
        page,rr=page_rows(item);gold={page+'::'+k for k in item['qa']['gold_inds']}
        q=item['qa']['question'];flat=bounded(ix.search(q,64)['hits'])
        expanded=ix.expand(q);control=ix.expand(q,where=dict(parent_id=page))
        row=dict(id=item['id'],question=q,gold=sorted(gold),
                 flat10=score(flat[:10],gold),flat64=score(flat,gold),expand64=score(expanded['hits'],gold),
                 provided_page_expand64=score(control['hits'],gold),trace=expanded['trace'],budget=expanded['budget'])
        for h in expanded['hits']:
            sn=h['snippet'];integrity['checked']+=1;integrity['exact']+=h['text'][sn['start']:sn['end']]==sn['text']
        results.append(row)
        if (n+1)%64==0:print('FINANCE_PROGRESS',n+1,flush=True)
    summary=aggregate(results,PLAN['profiles']);summary['snippet_integrity']=dict(integrity)
    dump(out/'financial-search.json',dict(summary=summary,results=results));print('FINANCIAL_SEARCH '+json.dumps(summary),flush=True)
    return summary


def label_keys(value):
    if isinstance(value,dict):return set(value)
    if isinstance(value,list) and all(isinstance(x,str) for x in value):return set(value)
    return None


def conversational(ix,turns,tally_path,out):
    sys.path.insert(0,str(tally_path));import tally as T
    fields=['turn_ind','cur_dial','gold_ind','cur_program','exe_ans']
    turns=[dict(x,**{k:x.get(k,x.get('annotation',{}).get(k)) for k in fields}) for x in turns]
    results=[];skipped=[];counts=Counter();execution=[]
    dump(out/'conversation-plan.json',[dict(id=x.get('id'),turn=x.get('turn_ind'),questions=x.get('cur_dial'),gold=x.get('gold_ind'),program=x.get('cur_program')) for x in turns])
    for n,item in enumerate(turns):
        goldkeys=label_keys(item.get('gold_ind'));questions=item.get('cur_dial')
        page,rr=page_rows(item);valid={r['id'] for r in rr}
        gold={page+'::'+x for x in goldkeys} if goldkeys else set()
        if not gold or not gold<=valid or not isinstance(questions,list) or not questions:
            skipped.append(dict(id=item.get('id'),turn=item.get('turn_ind'),reason='unresolved turn source labels or dialogue',gold=item.get('gold_ind')))
        else:
            last=questions[-1];history=' '.join(questions)
            a=bounded(ix.search(last,64)['hits']);b=bounded(ix.search(history,64)['hits']);c=ix.expand(history)
            results.append(dict(id=item['id'],turn=item.get('turn_ind'),last_question=last,history=questions,gold=sorted(gold),
                last10=score(a[:10],gold),last64=score(a,gold),history10=score(b[:10],gold),history64=score(b,gold),history_expand64=score(c['hits'],gold)))
        program=item.get('cur_program');expected=item.get('exe_ans');erow=dict(id=item.get('id'),turn=item.get('turn_ind'),program=program,gold=expected)
        try:
            if not isinstance(program,str):raise ValueError('program not text')
            if '(' not in program:
                expr=literal(number(program));mode='value_selection';steps=0
            else:
                compiled=compile_program(dict(qa=dict(program=program),table=item['table']));expr=compiled['tally'];mode='supplied_program';steps=len(compiled['ops'])
            actual=T.strip(T.Interp(out=io.StringIO()).run(expr))
            want=(expected=='yes') if expected in ['yes','no'] else number(expected)
            matched=close(actual,want);counts[mode+'_total']+=1;counts[mode+'_matched']+=matched
            counts['max_steps']=max(counts['max_steps'],steps)
            erow.update(status='executed',mode=mode,steps=steps,actual=str(actual),matched=matched)
        except Exception as e:erow.update(status='unsupported',reason=type(e).__name__+': '+str(e));counts['unsupported']+=1
        execution.append(erow)
        if (n+1)%300==0:print('CONVERSATION_PROGRESS',n+1,flush=True)
    summary=aggregate(results,['last10','last64','history10','history64','history_expand64']);summary.update(total_turns=len(turns),unresolved=len(skipped),execution=dict(counts))
    dump(out/'conversational-search.json',dict(summary=summary,results=results,unresolved=skipped))
    dump(out/'conversational-execution.json',dict(summary=dict(counts),results=execution))
    print('CONVERSATIONAL_SEARCH '+json.dumps(summary),flush=True);return summary


def money(cents):return '$'+str(cents//100)+'.'+str(cents%100).zfill(2)


def lifecycle(tally_path,out):
    sys.path.insert(0,str(tally_path));import tally as T
    plans=[]
    for seed in range(64):
        rng=random.Random(902100+seed);opening=rng.randrange(100000,200000)
        values=[];charges=[rng.randrange(4000,8000) for _ in range(3)];pays=[rng.randrange(2000,4000) for _ in range(5)];credits=[rng.randrange(200,500) for _ in range(2)]
        for i,x in enumerate(charges):values.append(('q'+str(i),'charge',x,None))
        for i,x in enumerate(pays):values.append(('p'+str(i),'payment_applied',x,None))
        for i,x in enumerate(credits):values.append(('c'+str(i),'credit_applied',x,None))
        values += [('r0','payment_reversal',pays[0]//4,'p0'),('r1','payment_reversal',pays[0]//5,'p0'),
                   ('r2','credit_reversal',credits[0]//3,'c0'),('r3','charge_reversal',charges[0]//6,'q0')]
        for stage in ['payment_sent','payment_received','credit_promised','approved']:values.append(('info'+stage,stage,rng.randrange(10000,20000),None))
        expected=opening+sum(charges)-sum(pays)-sum(credits)+pays[0]//4+pays[0]//5+credits[0]//3-charges[0]//6
        plans.append(dict(seed=seed,opening=opening,events=values,expected=expected,late_credit=credits[1]))
    dump(out/'fictional-lifecycle-plan.json',plans);results=[]
    with tempfile.TemporaryDirectory() as tmp:
        ix=EvidenceIndex(Path(tmp)/'fictional.sqlite',True)
        for plan in plans:
            seed=plan['seed'];prefix='s'+str(seed)+':';scope=dict(project='P'+str(seed),account='000'+str(seed),obligation='INV'+str(seed),version='v2')
            records=[];wanted=[]
            for i,(ident,stage,value,reverse) in enumerate(plan['events']):
                rid=prefix+ident;wanted.append(rid);received='2044-03-01' if ident=='c1' else '2044-01-15'
                meta=dict(scope,kind='event',event_id=ident,stage=stage,amount_cents=value,day='2044-01-'+str(i+1).zfill(2),received=received,
                          depends_on=[prefix+reverse] if reverse else [])
                if reverse:meta['reverses']=reverse
                records.append(dict(id=rid,parent_id=prefix+'register-'+stage,text=stage+' '+money(value),locator='fictional:'+rid,metadata=meta))
            records.append(dict(id=prefix+'root',parent_id=prefix+'root',text='reconciliationrequest invoice records',locator='fictional:'+prefix+'root',metadata=dict(scope,received='2044-01-01',depends_on=wanted)))
            for label,text in [('claim_paid','The builder asserts paid in full.'),('claim_unpaid','The supplier asserts an unpaid balance.'),('memory','The witness cannot recall authorization.')]:
                records.append(dict(id=prefix+label,parent_id=prefix+'statements',text=text,locator='fictional:'+prefix+label,metadata=dict(scope,kind='statement',epistemic='reported_statement')))
            records.append(dict(id=prefix+'old',parent_id=prefix+'old',text='reconciliationrequest wrong-version adjustment',locator='fictional:old',metadata=dict(scope,version='v1',amount_cents=999999)))
            ix.ingest(records);allr=ix.expand('reconciliationrequest',where=scope);found={r['id'] for r in allr['hits']}
            events=[r['metadata'] for r in allr['hits'] if r['metadata'].get('kind')=='event']
            def calculate(events,expected):
                args=[]
                for e in events:
                    args.append('{id:'+json.dumps(e['event_id'])+',scope:"invoice",stage:'+json.dumps(e['stage'])+',amount:'+money(e['amount_cents'])+',day:@'+e['day']+
                                (',reverses:'+json.dumps(e['reverses']) if 'reverses' in e else '')+'}')
                expr='receivable_rollforward('+money(plan['opening'])+',['+','.join(args)+'],'+money(expected)+',"invoice")'
                got=T.to_json(T.Interp(out=io.StringIO()).run(expr));return int(Decimal(got['calculated_closing'].replace('$','').replace(',',''))*100),got['clean']
            checks={};value,clean=calculate(events,plan['expected']);checks['full_reconciliation']=value==plan['expected'] and clean and set(wanted)<=found and not allr['unresolved_dependencies']
            known=ix.expand('reconciliationrequest',where=scope,before=dict(received='2044-02-01'))
            ke=[r['metadata'] for r in known['hits'] if r['metadata'].get('kind')=='event'];kv,kclean=calculate(ke,plan['expected']+plan['late_credit'])
            checks['knowledge_frame']=kv==plan['expected']+plan['late_credit'] and any(x['required_id']==prefix+'c1' and x['reason']=='excluded_by_scope' for x in known['unresolved_dependencies'])
            missing=prefix+'c0';saved=next(r for r in records if r['id']==missing);ix.remove([missing])
            incomplete=ix.expand('reconciliationrequest',where=scope)
            checks['missing_input_exposed']=any(x['required_id']==missing and x['reason']=='missing_from_index' for x in incomplete['unresolved_dependencies'])
            ix.ingest([saved]);checks['more_data_resolves_input']=not ix.expand('reconciliationrequest',where=scope)['unresolved_dependencies']
            statements=ix.search('asserts witness',20,dict(scope,kind='statement'))
            checks['claims_and_memory_preserved']={h['id'] for h in statements['hits']}=={prefix+x for x in ['claim_paid','claim_unpaid','memory']}
            old=next(h for h in allr['hits'] if h['id']==prefix+'p0');changed=next(r for r in records if r['id']==prefix+'p0');changed=dict(changed,text=changed['text']+' corrected source wording')
            ix.ingest([changed]);checks['stale_citation_rejected']=not ix.validate_citation(old)['valid']
            results.append(dict(seed=seed,data_class='fictional',checks=checks,calculated_cents=value,expected_cents=plan['expected'],known_frame_cents=kv,missing_input=incomplete['unresolved_dependencies'],source_rows=len(records),financial_adjustments=14))
        ix.close()
    summary=dict(scenarios=len(results),checks=sum(len(r['checks']) for r in results),passed=sum(sum(r['checks'].values()) for r in results),
                 categories={k:sum(r['checks'][k] for r in results) for k in results[0]['checks']})
    dump(out/'fictional-lifecycle-results.json',dict(summary=summary,results=results));print('FICTIONAL_LIFECYCLE '+json.dumps(summary),flush=True)
    if summary['passed']!=summary['checks']:raise AssertionError('fictional lifecycle mechanical control failed')
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--tally',required=True);a=p.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);sources=out/'sources';sources.mkdir(exist_ok=True)
    dump(out/'frozen-plan.json',PLAN);manifest=[];datasets={}
    blobs=dict(train='a6c2c5a60f9abe3fba5a793cc4d9e1dee2e09209',dev='970f239f591c782b17df420c0d343b780737f3da',test='59958c7c3bb3b21f4dff6bc912a0fe0ae710aee0')
    for split in ['train','dev','test']:
        path=sources/('finqa-'+split+'.json');manifest.append(download('https://raw.githubusercontent.com/czyssrs/FinQA/'+FINQA_REF+'/dataset/'+split+'.json',path,blobs[split]));datasets[split]=json.loads(path.read_text())
    convpath=sources/'convfinqa.zip';manifest.append(download('https://raw.githubusercontent.com/czyssrs/ConvFinQA/'+CONV_REF+'/data.zip',convpath,'bde03381e2d9ef0043796f2722f7a87633887358'))
    with zipfile.ZipFile(convpath) as z:convos=json.loads(z.read('data/dev.json'));turns=json.loads(z.read('data/dev_turn.json'))
    dump(out/'source-manifest.json',manifest)
    ix=EvidenceIndex(out/'evidence.sqlite',True);pages=set();record_ids=set();question_fields=0
    def records():
        for dataset in list(datasets.values())+[convos]:
            for item in dataset:
                page,rr=page_rows(item)
                if page in pages:continue
                pages.add(page)
                for row in rr:
                    record_ids.add(row['id']);yield row
    indexed=ix.ingest(records());print('INDEXED '+json.dumps(indexed),flush=True)
    dump(out/'index-audit.json',dict(stats=indexed,finqa_records={k:len(v) for k,v in datasets.items()},conv_dev_conversations=len(convos),conv_dev_turns=len(turns),
         corpus_fields=['id','parent_id','text','locator','metadata: corpus,page,entity,source_row,order,data_class'],qa_fields_indexed=0))
    summary=dict(index=indexed,financial=retrieve_finance(ix,datasets['test'],out),
                 conversations=conversational(ix,turns,Path(a.tally).resolve(),out),
                 fictional_lifecycle=lifecycle(Path(a.tally).resolve(),out))
    # Ready-to-search index is included in the GitHub artifact; source downloads are separately pinned.
    ix.close();dump(out/'SUMMARY.json',summary);print('COMPLEX_EVALUATION_COMPLETE '+json.dumps(summary),flush=True)


if __name__=='__main__':main()
