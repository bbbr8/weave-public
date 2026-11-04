"""Fresh development evaluation, version 2. Synthetic inputs; frozen pre-run gold.

Retrieval probes measure selected-source relevance, not answer comprehension.
Structured cases supply their meanings explicitly. No live model is invoked.
"""
import argparse
from collections import Counter
import copy
from decimal import Decimal
from fractions import Fraction
import hashlib
import io
import itertools
import json
import math
import os
from pathlib import Path
import random
import sys
import tempfile
import time
import traceback

PLAN=[]


def add(ident,category,inputs,expected,execute):
    PLAN.append(dict(id=ident,category=category,inputs=inputs,expected=expected,execute=execute))


def graph(texts,metadata=None):
    from loom_research.store import GraphStore
    tmp=tempfile.TemporaryDirectory();s=GraphStore(Path(tmp.name)/'fresh.sqlite',create=True)
    nodes=[]
    for i,(ident,text) in enumerate(texts):
        nodes.extend([dict(id='s'+str(i),type='source',origin='synthetic:fresh-'+str(i),locator='fresh synthetic row '+str(i)),
                      dict(id=ident,type='passage',label=ident,text=text,source_ids=['s'+str(i)],data=(metadata or {}).get(ident,{}))])
    s.apply(dict(schema='loom.graph.batch.v1',batch_id='seed',nodes=nodes))
    return tmp,s


RETRIEVAL=[
 ('receipt', 'Mira acknowledged delivery of the revised attachment.',
  'Mira authorized the extra excavation described in the revised attachment.',
  ['Who acknowledged delivery?', 'Who confirmed getting the revised attachment?', 'Who said the updated file had arrived?']),
 ('application', 'The supplier applied the adjustment to invoice INV-Z73 and reduced the balance.',
  'The owner mailed a check intended to cover invoice INV-Z73.',
  ['Which record shows the adjustment was applied?', 'What reduced the supplier balance?', 'Was the correction actually booked against the amount owed?']),
 ('expert_report', 'Aster served the signed expert report on the parties on March 12.',
  'Aster retained the expert on January 8; no report was attached to that message.',
  ['When was the expert report served?', 'Which record establishes report delivery to the parties?', 'When did opposing counsel receive the written opinion?']),
 ('memory', 'Nolan testified that he could not recall executing the release.',
  'Nolan denied executing the release in his earlier email.',
  ['What did Nolan testify he could not recall?', 'Which account expresses a memory limitation about the release?', 'Did the testimony describe uncertainty of recollection?']),
 ('reimbursement', 'Lena agreed to advance the fee because she expected the earlier funds to be returned.',
  'Lena agreed to advance the fee and confirmed the amount in a text message.',
  ['Why did Lena agree to advance the fee?', 'Which account describes expected reimbursement?', 'What understanding accompanied her decision to provide the money?']),
 ('first_learning', 'Oren first learned the designation had lapsed at the October 28 meeting.',
  'Oren signed the original agreement in February before the October 28 meeting.',
  ['When did Oren first learn the designation had lapsed?', 'Which record dates discovery of the designation problem?', 'When did awareness of the expired status begin?']),
 ('unseen_lab', 'The selector scored 41 of 80 on unseen repair tickets written by another mechanic.',
  'The selector scored 79 of 80 on its own development repair tickets.',
  ['How did the selector perform on unseen repair tickets?', 'Which result tests transfer to another mechanic?', 'How well did the helper generalize beyond its practice examples?']),
 ('baseline_lab', 'The frequency baseline correctly routed 62 of 90 diagnostic requests.',
  'The neural router correctly routed 58 of 90 diagnostic requests.',
  ['What was the frequency baseline result?', 'Which result belongs to the simple frequency comparison?', 'How did the reference counting method perform?']),
 ('version', 'Workbook revision R9 increased the door allowance from 110 to 145 without changing completed work.',
  'Workbook revision R2 listed a door allowance of 110 and completed work of zero.',
  ['Which workbook revision increased the allowance?', 'Where is the later door budget change recorded?', 'Which update changed the planned amount while work stayed the same?']),
 ('authority', 'The sender forwarded the draw packet; authorization remained with a different officer.',
  'The bank officer authorized funding after reviewing the forwarded draw packet.',
  ['Which record explicitly assigns authorization to somebody other than the sender?', 'Whose stated role was limited to forwarding the packet?', 'Which sentence says the transmitter lacked approval authority?']),
 ('refund', 'The merchant returned the disputed charge to the original card and the credit posted.',
  'The merchant promised a refund of the disputed charge but supplied no settlement entry.',
  ['Which record shows the refund posted?', 'Was the merchant repayment actually credited to the card?', 'Did the promised reimbursement reach the original payment account?']),
 ('source_family', 'The dashboard repeats the witness transcript and cites that same transcript as its only origin.',
  'The bank statement independently records the cleared transfer described in the witness transcript.',
  ['Which account repeats the witness transcript?', 'Which summary shares the original testimony source?', 'Is the dashboard a derivative account rather than a separate observer?'])]


def loom():
    from loom_research import indexed as I,identity
    for family,target,decoy,questions in RETRIEVAL:
        for variant,q in enumerate(questions):
            def run(target=target,decoy=decoy,q=q,variant=variant):
                texts=[('target',target),('decoy',decoy)]
                random.Random(81000+variant).shuffle(texts)
                tmp,s=graph(texts)
                try:
                    r=I.search(s,q,top=1)
                    return {'first_id':r['hits'][0]['id'] if r['hits'] else None}
                finally:tmp.cleanup()
            add('retrieval-'+family+'-'+str(variant),'raw_source_selection',
                dict(target=target,decoy=decoy,question=q),dict(first_id='target'),run)

    for distractors in [4,8,16,32]:
        for budget in [2,distractors+2]:
            def scoped(distractors=distractors,budget=budget):
                texts=[('other-'+str(i),'settlement credit payment') for i in range(distractors)]
                texts.append(('wanted','An extensive reconciliation note about the settlement credit payment '+('additional context '*150)))
                meta={ident:dict(loan='other') for ident,_ in texts};meta['wanted']=dict(loan='requested-loan')
                tmp,s=graph(texts,meta)
                try:
                    r=I.search(s,'settlement credit payment',top=1,candidates=budget,where=dict(loan='requested-loan'))
                    return dict(ids=[h['id'] for h in r['hits']],truncation_disclosed=r['candidate_limit_reached'])
                finally:tmp.cleanup()
            add('candidate-pressure-'+str(distractors)+'-'+str(budget),'scoped_candidate_recall',
                dict(distractors=distractors,candidate_budget=budget,scope='requested-loan'),dict(ids=['wanted'],truncation_disclosed=budget<distractors+1),scoped)

    for n in range(12):
        same=n%3==0;left_id='000'+str(710+n);right_id=left_id if same else str(710+n)
        def identities(left_id=left_id,right_id=right_id,same=same):
            def node(ident,value):return dict(id=ident,type='entity',label='Avery Record',
                identifiers=[dict(kind='registration',namespace='issuer-A',value=value,unique=True)],data=dict(entity_type='company'))
            r=identity.compare(node('left',left_id),node('right',right_id))
            return dict(state=r['state'])
        add('leading-zero-identity-'+str(n),'transaction_identity',dict(left=left_id,right=right_id),
            dict(state='EXACT_DECLARED_KEY' if same else 'IDENTIFIER_CONFLICT'),identities)

    from loom_research.store import GraphStore
    for n in range(8):
        end_day=10+n;cutoff=14;expected=end_day<=cutoff
        def clocks(end_day=end_day):
            with tempfile.TemporaryDirectory() as tmp:
                s=GraphStore(Path(tmp)/'g',create=True);clock={'receipt':{'owner':['2043-06-01','2043-06-'+str(end_day).zfill(2)]}}
                s.apply(dict(schema='loom.graph.batch.v1',batch_id='seed',nodes=[
                    dict(id='s',type='source',origin='synthetic:new-clock',locator='fixture',clocks=clock),
                    dict(id='p',type='passage',text='Retained notice.',source_ids=['s'],clocks=clock)]))
                return dict(known='p' in {x['id'] for x in s.snapshot(actor='owner',receipt_before='2043-06-14')['nodes']})
        add('receipt-interval-'+str(n),'knowledge_cutoff',dict(interval_end=end_day,cutoff_day=cutoff),dict(known=expected),clocks)


def tally():
    import tally as T
    def m(n):return ('-$' if n<0 else '$')+str(abs(n)//100)+'.'+str(abs(n)%100).zfill(2)
    for seed in range(64):
        rng=random.Random(2026110400+seed);opening=rng.randrange(10000,10**9);charge=rng.randrange(10000)
        pay=rng.randrange(opening);credit=rng.randrange(opening-pay+1);r1=rng.randrange(pay+1);r2=rng.randrange(pay-r1+1)
        amounts=dict(opening=opening,charge=charge,payment=pay,credit=credit,reversal_one=r1,reversal_two=r2)
        events=[]
        values=[('charge','charge',charge,'invoice-X','2043-02-01',None),
                ('payment','payment_applied',pay,'invoice-X','2043-02-02',None),
                ('credit','credit_applied',credit,'invoice-X','2043-02-02',None),
                ('reverse-a','payment_reversal',r1,'invoice-X','2043-02-03','payment'),
                ('reverse-b','payment_reversal',r2,'invoice-X','2043-02-04','payment'),
                ('other','payment_applied',876543,'other-invoice','2043-02-03',None),
                ('sent','payment_sent',987654,'invoice-X','2043-02-02',None),
                ('received','payment_received',654321,'invoice-X','2043-02-03',None)]
        rng.shuffle(values)
        for ident,stage,value,scope,day,reverse in values:
            events.append('{id:'+json.dumps(ident)+',stage:'+json.dumps(stage)+',amount:'+m(value)+',scope:'+json.dumps(scope)+',day:@'+day+((',reverses:'+json.dumps(reverse)) if reverse else '')+'}')
        closing=opening+charge-pay-credit+r1+r2
        expr='receivable_rollforward('+m(opening)+',['+','.join(events)+'],'+m(closing)+',"invoice-X")'
        def account(expr=expr):
            r=T.to_json(T.Interp(out=io.StringIO()).run(expr))
            closing_cents=int(Decimal(r['calculated_closing'].replace('$','').replace(',',''))*100)
            return dict(closing_cents=closing_cents,clean=r['clean'],included=len(r['included']),excluded=len(r['excluded']))
        add('mixed-ledger-'+str(seed),'mixed_financial_lifecycle',dict(amounts=amounts,ordered_events=values),
            dict(closing_cents=closing,clean=True,included=5,excluded=3),account)


def weave():
    from reasoning_layer.examples import rules_packet
    from reasoning_layer.core import validate_program
    from reasoning_layer.contracts import digest,signature
    for n in range(12):
        for kind in ['source_revision','question_revision']:
            def stale(n=n,kind=kind):
                x=rules_packet();t,p=x['task'],x['program']
                if kind=='source_revision':t['context']+='\nSource revision '+str(900+n)+' records the exception.'
                else:
                    t['question']='Did party '+str(900+n)+' approve only the original version?'
                    t['question_sha256']=digest(t['question']);t['query_signature']=signature(t['question'])
                r=validate_program(t,p)
                return dict(valid=r['valid'])
            add('bound-program-'+kind+'-'+str(n),'cached_answer_identity',
                dict(change=kind,fixture=900+n),dict(valid=False),stale)


def tell():
    import tell as T
    header='tier order: native > derived > synthetic.\nanchor A "fresh fixture".\n'
    for bits in itertools.product([False,True],repeat=4):
        invoice=['project_x','account_x','instrument_x','57.43'];payment=invoice.copy()
        for i,change in enumerate(bits):
            if change:payment[i]=['project_y','account_y','instrument_y','57.44'][i]
        src=header+'fact invoice('+','.join(invoice)+') @A tier native.\nfact payment('+','.join(payment)+') @A tier native.\n'
        src+='rule joined: matched(P,A,I,M) :- invoice(P,A,I,M), payment(P,A,I,M).\n'
        def join(src=src):
            p=T.parse(src);T.fixpoint(p)
            return dict(matches=sum(key[0]=='matched' for key in p.facts))
        add('payment-identity-'+''.join(str(int(b)) for b in bits),'cross_record_join',
            dict(invoice=invoice,payment=payment),dict(matches=0 if any(bits) else 1),join)


def vein():
    import vein as V
    schema=V.compile('endian be\nroot record\ntype record {\n revision: u16\n cents: u32\n}\n')
    for n in range(8):
        for change in ['tail_only','decoded_value']:
            def compare(n=n,change=change):
                prefix=(300+n).to_bytes(2,'big');amount=(7721+n).to_bytes(4,'big')
                before=prefix+amount+b'first metadata';after=(prefix+(7722+n).to_bytes(4,'big')+b'first metadata') if change=='decoded_value' else prefix+amount+b'revised metadata'
                with tempfile.TemporaryDirectory() as tmp:
                    a,b=Path(tmp)/'a',Path(tmp)/'b';a.write_bytes(before);b.write_bytes(after)
                    r=V.compare_files(schema,a,b)
                    return dict(hashes_differ=r['before']['sha256']!=r['after']['sha256'],changed_fields=[c['path'] for c in r['changes']])
            add('binary-provenance-'+change+'-'+str(n),'binary_vs_decoded_identity',dict(kind=change,record=n),
                dict(hashes_differ=True,changed_fields=[['cents']] if change=='decoded_value' else []),compare)


def bootlang():
    from bootlang import permutation_test
    vocabulary=['scope','notice','version','credit','owner','review']
    def divergence(left,right):
        a,b=Counter(' '.join(left).split()),Counter(' '.join(right).split());na,nb=sum(a.values()),sum(b.values())
        terms=set(a)|set(b);p={t:a[t]/na for t in terms};q={t:b[t]/nb for t in terms};mix={t:(p[t]+q[t])/2 for t in terms}
        return (sum(p[t]*math.log2(p[t]/mix[t]) for t in terms if p[t])+sum(q[t]*math.log2(q[t]/mix[t]) for t in terms if q[t]))/2
    for n in range(12):
        rng=random.Random(63000+n);utterances=[' '.join(rng.choices(vocabulary,k=rng.randrange(1,8))) for _ in range(6)]
        observed=divergence(utterances[:3],utterances[3:]);parts=list(itertools.combinations(range(6),3));extreme=0
        for part in parts:
            left=[t for i,t in enumerate(utterances) if i in part];right=[t for i,t in enumerate(utterances) if i not in part]
            extreme+=divergence(left,right)>=observed-1e-12
        rows=[dict(speaker='speaker',period='before' if i<3 else 'after',text=t) for i,t in enumerate(utterances)]
        def permutation(rows=rows):
            r=permutation_test(rows,'speaker','before','after',budget=1000)
            return dict(method=r['method'],evaluated=r['evaluated'],extreme=r['extreme'],p_value=r['p_value'])
        add('utterance-permutation-'+str(n),'whole_utterance_statistic',dict(utterances=utterances),
            dict(method='exact',evaluated=20,extreme=extreme,p_value=extreme/20),permutation)


def analytics(repo):
    if repo=='olaps':
        from olaps import analyze
        for seed in range(12):
            rng=random.Random(77500+seed)
            rows=[dict(project=rng.choice(['A','B']),stage=rng.choice(['requested','applied','credited']),cents=rng.randrange(-3000,9000)) for _ in range(35)]
            selected=[(i,r['cents']) for i,r in enumerate(rows) if r['project']=='A' and r['stage']=='applied']
            def cube(rows=rows):
                r=analyze(rows,['project','stage'],['cents'],where=dict(project='A',stage='applied'),drill=True)
                grand=next((g for g in r if not g['keys']),None)
                return dict(total=grand['measures']['cents']['total'] if grand else 0,rows=grand['row_indices'] if grand else [])
            add('scoped-ledger-rollup-'+str(seed),'scoped_aggregation',dict(rows=rows),dict(total=sum(v for _,v in selected),rows=[i for i,_ in selected]),cube)
    else:
        if repo=='qulaps':from qulaps import solve
        else:from analytics import solve
        for seed in range(12):
            rng=random.Random(88200+seed);domains=dict(owner=[-2,0,3],builder=[-1,1,4],vendor=[0,2]);weights={k:rng.randrange(-2,3) for k in domains};metric={k:rng.randrange(-3,4) for k in domains}
            values=list(itertools.product(*domains.values()));valid=[]
            for v in values:
                state=dict(zip(domains,v));lhs=sum(weights[k]*state[k] for k in weights)
                if -2<=lhs<=5:valid.append(sum(metric[k]*state[k] for k in metric))
            model=dict(domains=domains,constraints=[dict(weights=weights,min=-2,max=5)],metric=metric)
            def solve_case(model=model):
                r=solve(model,compressed=True) if repo=='qulaps' else solve(model)
                return dict(count=r['feasible'],low=r['minimum'],high=r['maximum'])
            add('signed-alternative-model-'+str(seed),'signed_alternatives',model,
                dict(count=len(valid),low=min(valid) if valid else None,high=max(valid) if valid else None),solve_case)


def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--target',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(a.target.resolve()));sys.path.insert(0,str((a.target/'runtime').resolve()))
    os.environ['SURD_USAGE']='0';os.environ['TALLY_NO_EXPERIMENT_LOG']='1'
    funcs={'loom-public':loom,'tally-public':tally,'weave-public':weave,'tell':tell,'vein':vein,'bootlang':bootlang}
    if a.repo in funcs:funcs[a.repo]()
    else:analytics(a.repo)
    a.out.mkdir(parents=True,exist_ok=True)
    frozen=[{k:v for k,v in case.items() if k!='execute'} for case in PLAN]
    raw=json.dumps(frozen,sort_keys=True,indent=2);(a.out/'frozen_plan.json').write_text(raw)
    results=[]
    for case in PLAN:
        row={k:v for k,v in case.items() if k!='execute'};start=time.monotonic()
        try:
            row['observed']=case['execute']();row['outcome']='pass' if row['observed']==row['expected'] else 'fail'
        except Exception as e:row.update(outcome='error',error=type(e).__name__+': '+str(e),traceback=traceback.format_exc(limit=3))
        row['seconds']=time.monotonic()-start;results.append(row)
    counts=Counter(r['outcome'] for r in results);categories={c:dict(Counter(r['outcome'] for r in results if r['category']==c)) for c in sorted({r['category'] for r in results})}
    report=dict(schema='fresh-development-eval.v2',repo=a.repo,total=len(results),counts=dict(counts),categories=categories,
                plan_sha256=hashlib.sha256(raw.encode()).hexdigest(),test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                scope='New authored development cases. No held-out model, semantic encoder, hosted inference or private evidence. Retrieval gold denotes the selected relevant source, not final answer correctness.',results=results)
    (a.out/'results.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ['repo','total','counts','categories','plan_sha256']},indent=2))
    return int(any(r['outcome']!='pass' for r in results))


if __name__=='__main__':raise SystemExit(main())
