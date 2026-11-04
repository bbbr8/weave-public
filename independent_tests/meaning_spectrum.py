"""Synthetic cross-domain behavior tests; no private evidence or model calls.

Contract tests check documented mechanics. Capability probes test additional
semantic expectations and report unmet capabilities separately from defects.
Reviewed annotations are supplied explicitly and are never called raw-language
understanding. Every individual scenario has a retained oracle and result.
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
import os
from pathlib import Path
import random
import sys
import tempfile
import time
import traceback

ROWS = []


def equal(actual, expected):
    if actual != expected:
        raise AssertionError('expected ' + repr(expected) + '; observed ' + repr(actual))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def rejects(fn, exceptions=(ValueError, TypeError, SystemExit)):
    try:
        fn()
    except exceptions:
        return
    raise AssertionError('invalid input was accepted')


def check(ident, dimension, oracle, fn, kind='contract', input_mode='declared_structured_inputs'):
    started = time.monotonic()
    row = dict(id=ident, dimension=dimension, kind=kind, input_mode=input_mode,
               oracle_basis=oracle, data_class='synthetic')
    try:
        fn()
        row['outcome'] = 'pass'
    except Exception as exc:
        row.update(outcome='fail', error=type(exc).__name__ + ': ' + str(exc),
                   traceback=traceback.format_exc(limit=4))
    row['seconds'] = time.monotonic() - started
    ROWS.append(row)


def loom_checks():
    from loom_research.store import GraphStore
    from loom_research import casework as C, evidence as E, indexed as I
    from loom_research.learning import clean_node
    axes = dict(property='project-A', loan='loan-A', scope='scope-A', obligation='invoice-A',
                version='v1', basis_clock='event', money_stage='applied',
                actor='owner-A', account='account-A', instrument='check-A')

    def store_with(tmp, texts):
        s = GraphStore(Path(tmp)/'graph.sqlite', create=True)
        nodes = [dict(id='source-'+str(i), type='source', origin='synthetic:family-'+str(i),
                      locator='synthetic record '+str(i)) for i in range(len(texts))]
        nodes += [dict(id='p'+str(i), type='passage', text=t, source_ids=['source-'+str(i)],
                       locator='synthetic paragraph '+str(i)) for i, t in enumerate(texts)]
        s.apply(dict(schema='loom.graph.batch.v1', batch_id='seed', nodes=nodes))
        return s

    def mapping(i, text, context=None, **kw):
        return dict(id=str(i), episode='synthetic-case', kind='statement',
                    evidence=[dict(node_id='p'+str(i), start=0, end=len(text), quote=text)],
                    context=copy.deepcopy(context or axes), **kw)

    def put(s, mappings):
        return C.map_records(s, dict(batch_id='map-'+str(s.head()[0]), reviewer='synthetic test author',
                                    mappings=mappings, expected_revision=s.head()[0]))

    def coordinate(axis=None):
        with tempfile.TemporaryDirectory() as tmp:
            texts=['The selected transaction was applied.', 'The selected transaction was not applied.']
            s=store_with(tmp,texts); other=copy.deepcopy(axes)
            if axis: other[axis]='different-'+axis
            put(s,[mapping(0,texts[0],claim=dict(key='this-transaction-applied',stance='support')),
                   mapping(1,texts[1],context=other,claim=dict(key='this-transaction-applied',stance='oppose'))])
            r=C.compare(s,dict(left='case:0',right='case:1'))
            equal(r['state'],'OPEN_COORDINATE_COMPARISON' if axis else 'SUPPORTED_COLLISION')
            if axis: equal(r['differing_axes'],[axis])

    check('loom-aligned-conflict','contradictions','Aligned opposing annotations collide',coordinate)
    for axis in C.ALIGN:
        check('loom-scope-'+axis,'scope_alignment','Changing one aligned axis must prevent a direct collision',lambda a=axis:coordinate(a))
    for axis in ['instrument','account']:
        check('loom-additional-scope-'+axis,'scope_alignment',
              'A transaction-specific comparison should disclose a changed '+axis,
              lambda a=axis:coordinate(a),kind='capability_probe')

    def knowledge(state):
        with tempfile.TemporaryDirectory() as tmp:
            t='Advisor sent a draft. Owner later described learning its significance.'
            s=store_with(tmp,[t]); k=dict(actor='owner-A',state=state)
            if state=='scoped_approval': k.update(scope='scope-A',version='v1')
            put(s,[mapping(0,t,knowledge=[k],clocks=dict(event=['2042-01-02']*2,statement=['2042-02-02']*2))])
            r=C.episode(s,'synthetic-case')
            equal(r['knowledge'][0]['state'],state)
            equal({x['clock'] for x in r['timeline']},{'event','statement'})
            equal(r['sentences'][0]['quotes'][0]['quote'],t)
    for state in sorted(C.KNOWLEDGE):
        check('loom-knowledge-'+state,'knowledge_vs_authorization',
              'A supplied knowledge state survives without inventing a receipt clock',lambda st=state:knowledge(st))

    def cutoff(known_at, cutoff_day, expected):
        with tempfile.TemporaryDirectory() as tmp:
            s=GraphStore(Path(tmp)/'g',create=True)
            s.apply(dict(schema='loom.graph.batch.v1',batch_id='seed',nodes=[
                dict(id='s',type='source',origin='synthetic:knowledge',locator='SYN',clocks=dict(receipt={'owner-A':known_at})),
                dict(id='p',type='passage',text='Expert status report.',source_ids=['s'],clocks=dict(receipt={'owner-A':known_at}))]))
            ids={n['id'] for n in s.snapshot(actor='owner-A',receipt_before=cutoff_day)['nodes']}
            equal('p' in ids,expected)
    for known,day,expected,label in [(['2042-10-30']*2,'2042-10-29',False,'later-knowledge'),
                                   (['2042-10-30']*2,'2042-10-30',True,'same-day-known'),
                                   (['2042-10-01','2042-10-31'],'2042-10-15',False,'interval-straddles'),
                                   (['2042-10-01','2042-10-31'],'2042-11-01',True,'interval-completed')]:
        check('loom-clock-'+label,'knowledge_timing','Only fully received intervals qualify at an actor cutoff',
              lambda k=known,d=day,e=expected:cutoff(k,d,e))

    def stages():
        with tempfile.TemporaryDirectory() as tmp:
            ts=['A record describes stage '+st+'.' for st in C.STAGES]
            s=store_with(tmp,ts)
            ms=[]
            for i,(t,stage) in enumerate(zip(ts,C.STAGES)):
                m=mapping(i,t,context={k:v for k,v in axes.items() if k!='money_stage'},
                          money=dict(event_id='event-'+stage,stage=stage,value='50.00',unit='USD'))
                m['kind']='money';ms.append(m)
            put(s,ms);r=C.lifecycle(s,'synthetic-case');equal(len(r['lanes']),1)
            equal(set(r['lanes'][0]['stages']),set(C.STAGES));equal(r['lanes'][0]['open_stages'],[])
            equal(r['lanes'][0]['aggregation'],'STAGE_SEPARATE; explicit aligned model required for totals')
    check('loom-lifecycle-nine-stages','money_lifecycle','Nine observations of one amount are stage-separated, never nine payments',stages)

    def source_revision():
        with tempfile.TemporaryDirectory() as tmp:
            t='Vendor applied USD 50.00.';s=store_with(tmp,[t]);put(s,[mapping(0,t)])
            before=C.episode(s,'synthetic-case');equal(len(before['sentences']),1)
            n=clean_node(next(n for n in s.snapshot()['nodes'] if n['id']=='p0'))
            n.update(revision=n['revision']+1,text='Vendor reversed the application.')
            s.apply(dict(schema='loom.graph.batch.v1',batch_id='revision',nodes=[n]))
            after=C.episode(s,'synthetic-case');equal(after['sentences'],[]);equal(after['stale_annotations'],['case:0'])
            require(s.verify()['ok'],'journal replay failed')
    check('loom-source-revision','source_change','Changed source stales the old explanation and preserves a valid journal',source_revision)

    def source_families():
        with tempfile.TemporaryDirectory() as tmp:
            s=GraphStore(Path(tmp)/'g',create=True)
            s.apply(dict(schema='loom.graph.batch.v1',batch_id='seed',nodes=[
                dict(id='s1',type='source',origin='synthetic:shared',locator='copy 1'),
                dict(id='s2',type='source',origin='synthetic:shared',locator='copy 2'),
                dict(id='s3',type='source',origin='synthetic:independent',locator='bank row'),
                dict(id='p1',type='passage',text='A credit account summary.',source_ids=['s1']),
                dict(id='p2',type='passage',text='A credit account summary copy.',source_ids=['s2']),
                dict(id='p3',type='passage',text='Independent bank credit record.',source_ids=['s3'])]))
            equal(E.explain(s,'credit',top=3)['source_origin_count'],2)
            s.withdraw('synthetic:shared','withdraw-family')
            r=E.explain(s,'credit',top=3)
            equal([c['id'] for c in r['cards']],['p3']);equal(r['source_origin_count'],1)
    check('loom-source-families','independent_support','Two copies count as one origin; withdrawing their family leaves an independent bank record',source_families)

    def multi_question():
        with tempfile.TemporaryDirectory() as tmp:
            t='Owner received version v2 and reported learning the expert status later.'
            s=store_with(tmp,[t]);put(s,[mapping(0,t,knowledge=[dict(actor='owner-A',state='later_discovery')])])
            questions=['Who knew what?', 'Which version was received?', 'Was the scope approved?',
                       'What remained unpaid?', 'Did a lab helper improve?', 'Which record should be checked next?']
            for question in questions:
                r=E.explain(s,question,episode='synthetic-case')
                equal(r['sentences'][0]['quotes'][0]['quote'],t)
                equal(r['knowledge'][0]['state'],'later_discovery')
                equal(r['comprehension_state'],'OPEN_INDEPENDENT_READER_EVALUATION')
    check('loom-episode-question-preservation','question_transfer','Episode inspection preserves evidence under six questions and keeps reader evaluation open',multi_question)

    def wrong_paraphrase():
        with tempfile.TemporaryDirectory() as tmp:
            t='Owner received the attachment but did not approve the revised scope.'
            s=store_with(tmp,[t]);m=mapping(0,t,summary='Owner approved the revised scope.')
            put(s,[m]);r=C.episode(s,'synthetic-case')
            require(not any(x['text']=='Owner approved the revised scope.' for x in r['sentences']),
                    'Exact source anchoring accepted a meaning-reversing reviewer summary')
    check('loom-paraphrase-entailment','source_meaning',
          'Approval cannot be paraphrased from an explicit denial of approval',wrong_paraphrase,
          kind='capability_probe',input_mode='raw_quote_plus_reviewer_summary')

    texts=[('credit','The vendor posted the credit against invoice INV-042.'),
           ('knowledge','The owner learned the expert designation status on October 30.'),
           ('authority','The borrower acknowledged receipt of the attachment but did not authorize construction.'),
           ('memory','The witness said: I do not remember signing that draw.'),
           ('lab','The adapter improved on development tickets and failed on unseen repair requests.')]
    questions=[('credit','credit invoice INV-042','literal-control'),
               ('credit','Did the adjustment reduce what remained owed?','paraphrase'),
               ('knowledge','owner learned expert designation status','literal-control'),
               ('knowledge','When did the client first discover who could testify?','paraphrase'),
               ('authority','borrower acknowledge attachment authorize construction','literal-control'),
               ('authority','Did receiving the revised file amount to consent?','paraphrase'),
               ('memory','witness remember signing draw','literal-control'),
               ('memory','Did the person deny having executed the funding form?','paraphrase'),
               ('lab','adapter development tickets unseen repair requests','literal-control'),
               ('lab','Will the trained helper generalize to a different mechanic?','paraphrase')]
    for desired,q,label in questions:
        def retrieval(desired=desired,q=q):
            with tempfile.TemporaryDirectory() as tmp:
                s=store_with(tmp,[t for _,t in texts]);r=I.search(s,q,top=1)
                actual=[texts[int(h['id'][1:])][0] for h in r['hits']]
                equal(actual,[desired])
        check('loom-retrieval-'+desired+'-'+label,'question_transfer',
              'Retrieve the manually designated relevant paragraph for this question',retrieval,
              kind='contract' if label=='literal-control' else 'capability_probe',input_mode='raw_text_to_default_lexical_retrieval')


def tally_checks():
    import tally as T
    def evaluate(code):return T.to_json(T.Interp(out=io.StringIO()).run(code))
    def money(cents):return ('$' if cents>=0 else '-$')+str(abs(cents)//100)+'.'+str(abs(cents)%100).zfill(2)
    def event(ident,stage,cents=3000,scope='invoice-A',day='2042-01-02',reverses=None):
        return '{id: '+json.dumps(ident)+', scope: '+json.dumps(scope)+', day: @'+day+', stage: '+json.dumps(stage)+', amount: '+money(cents)+((', reverses: '+json.dumps(reverses)) if reverses else '')+'}'
    def roll(events,closing=10000):
        return evaluate('receivable_rollforward($100.00, ['+', '.join(events)+'], '+money(closing)+', "invoice-A")')
    effects={'charge':3000,'payment_applied':-3000,'credit_applied':-3000,
             'payment_sent':0,'payment_received':0,'receipt_reported':0,'credit_promised':0,
             'refund_expected':0,'refund_sent':0,'requested':0,'approved':0}
    for stage,effect in effects.items():
        def one(st=stage,effect=effect):
            r=roll([event('E1',st)],10000+effect);equal(r['calculated_closing'],money(10000+effect));equal(r['gap'],'$0.00')
            equal(len(r['included']),int(effect!=0));equal(len(r['excluded']),int(effect==0))
        check('tally-stage-'+stage,'money_lifecycle','Opening balance changes only at the explicitly supplied applied/charge stage',one)
    for original,reversal,expected in [('charge','charge_reversal',10000),('payment_applied','payment_reversal',10000),('credit_applied','credit_reversal',10000)]:
        def reverse(orig=original,rev=reversal,expected=expected):
            r=roll([event('E1',orig),event('E2',rev,reverses='E1')],expected)
            equal(r['calculated_closing'],money(expected));equal(r['clean'],True)
        check('tally-reversal-'+original,'reversals','A linked full reversal exactly cancels the original applied effect',reverse)
    for seed in range(12):
        def shuffle(seed=seed):
            events=[event('C','charge',1500),event('P','payment_applied',4000),event('K','credit_applied',500),
                    event('S','payment_sent',999999),event('D','payment_applied',5000,scope='different-invoice')]
            random.Random(seed).shuffle(events);r=roll(events,7000)
            equal(r['calculated_closing'],'$70.00');equal(r['clean'],True)
        check('tally-permutation-'+str(seed),'order_and_scope','100 + 15 - 40 - 5 = 70; sent money and another invoice do not alter this balance',shuffle)
    def over_reversal():
        r=roll([event('P','payment_applied',3000),event('R1','payment_reversal',2000,reverses='P'),
                event('R2','payment_reversal',2000,reverses='P')],7000)
        equal(r['calculated_closing'],'$70.00');equal(len(r['diagnostics']),2);equal(r['clean'],False)
    check('tally-overfull-same-day-reversals','reversals','Overfull same-day reversal batch is held without picking a winner',over_reversal)
    check('tally-duplicate-id','identity','Duplicate event identity is rejected',lambda:rejects(lambda:roll([event('E','charge'),event('E','charge')]),(T.TallyError,)))
    def sources():
        r=T.Interp(out=io.StringIO()).run('receivable_rollforward($100.00 from "OPEN", [{id: "P", scope: "invoice-A", day: @2042-01-02, stage: "payment_applied", amount: $30.00 from "PAY"}], $70.00 from "CLOSE", "invoice-A")')
        equal(set(T.all_sources(T.strip(r)['gap'])),{'OPEN','PAY','CLOSE'})
    check('tally-source-lineage','independent_support','The balance gap retains opening, payment and closing source labels',sources)

    def budget_row(scope,amount):
        return '{id: "line-A", scope: '+json.dumps(scope)+', scheduled: '+money(amount)+', change: $0.00, revised: '+money(amount)+', completed: $0.00, deposits: $0.00, total: $0.00, balance: '+money(amount)+'}'
    for delta in [0,1,100,5000]:
        def bridge(delta=delta):
            r=evaluate('budget_bridge(['+budget_row('project-A',10000)+'], ['+budget_row('project-A',10000+delta)+'])')
            equal(r['clean'],True);equal(r['rows'][0]['delta']['balance'],money(delta))
            equal(r['rows'][0]['scope_driven_balance_change'],delta!=0)
        check('tally-budget-version-'+str(delta),'document_versions','A changed budget with unchanged work changes the stated balance through scope alone',bridge)
    def project_bridge():
        r=evaluate('budget_bridge(['+budget_row('project-A',10000)+'], ['+budget_row('project-B',10000)+'])')
        equal(r['complete_comparison'],False);equal(r['rows'],[]);equal(len(r['added']),1);equal(len(r['removed']),1)
    check('tally-budget-project-change','scope_alignment','Matching line IDs and amounts on different projects do not become a version bridge',project_bridge)
    def export_precision():
        raw=T.Interp(out=io.StringIO()).run('0.123456789012345678901')
        exported=json.loads(json.dumps(T.to_json(raw)),parse_float=Decimal)
        equal(exported,Decimal('0.123456789012345678901'))
    check('tally-nonmoney-json-precision','numeric_export','An exact non-money decimal should survive JSON serialization exactly',export_precision,kind='capability_probe')


def weave_checks():
    from reasoning_layer.contracts import make_task,signature,digest
    from reasoning_layer.core import resolve,validate_program,calculate
    from reasoning_layer.examples import rules_packet
    for domain in ['construction','lending','testimony','case-handling','lab-generalization','document-versions']:
        for known,expected in [(set(),'Unknown'),({'p2'},'True'),({'p3'},'False'),({'p2','p3'},'ABSTAIN')]:
            def state(known=known,expected=expected,domain=domain):
                x=rules_packet();t=x['task'];p=x['program']
                t['question']='Is the declared '+domain+' proposition supported?'
                # Resolve evaluates the declared policy; it does not parse the new sentence.
                equal(resolve(t,p,known)['answer'],expected)
            check('weave-state-'+domain+'-'+expected,'four_state_answers','Support, refutation, unknown and conflict remain four distinct outcomes',state)
    for question in ['Was the payment applied?','Was the payment not applied?','Must the payment be applied?','Was every payment applied?']:
        def drift(question=question):
            x=rules_packet();x['task']['question']=question;x['task']['question_sha256']=digest(question)
            x['task']['query_signature']=signature(question)
            equal(validate_program(x['task'],x['program'])['valid'],False)
        check('weave-question-drift-'+hashlib.sha256(question.encode()).hexdigest()[:8], 'question_identity',
              'A program bound to the old question cannot silently answer a different one',drift)
    for question in ["Wasn't the payment applied?",'Was the invoice left without a credit?']:
        check('weave-negation-'+hashlib.sha256(question.encode()).hexdigest()[:8], 'source_meaning',
              'A semantic polarity analysis should preserve contractions and without',lambda q=question:equal(signature(q)['polarity'],'negative'),
              kind='capability_probe',input_mode='raw_question_lexical_signature')
    for literal,expected in [('0.10000000000000001 - 0.1','0.00000000000000001'),('1.0000000000000001 - 1','0.0000000000000001')]:
        check('weave-literal-'+expected,'exact_arithmetic','Exact decimal subtraction oracle',
              lambda f=literal,e=expected:equal(calculate(dict(operands=[],formula=f)),Decimal(e)))


def tell_checks():
    import tell as T
    header='tier order: native > derived > synthetic.\nanchor A "synthetic sources".\n'
    predicates=['sent','received','understood','authorized','applied','credited']
    for count in range(7):
        def roles(count=count):
            src=header+'\n'.join('fact '+p+' @A tier native.' for p in predicates[:count])
            src+='\nrule closed: settled :- applied, credited.\n'
            p=T.parse(src);T.fixpoint(p)
            equal(('settled',()) in p.facts,count==6)
            for missing in predicates[count:]:equal((missing,()) in p.facts,False)
        check('tell-stage-prefix-'+str(count),'knowledge_vs_authorization','No explicit rule converts one stage into the next',roles)
    for learned,cutoff,expected in [('2042-10-30','2042-10-29',False),('2042-10-30','2042-10-30',True),('2042-10-30','2042-11-01',True)]:
        def clock(learned=learned,cutoff=cutoff,expected=expected):
            src=header+'fact learned(owner, '+learned+') @A tier native.\nrule prior: knew(A) :- learned(A,D), D <= '+cutoff+'.\n'
            p=T.parse(src);T.fixpoint(p);equal(('knew',('owner',)) in p.facts,expected)
        check('tell-clock-'+cutoff,'knowledge_timing','Date comparison prevents later knowledge from entering an earlier cutoff',clock)
    for subset in itertools.product([False,True],repeat=3):
        def support(subset=subset):
            src=header+'\n'.join('fact '+p+' @A tier native.' for p,active in zip(['instrument_match','payment','credit_match'],subset) if active)
            src+='\nrule complete: reconciled :- instrument_match, payment, credit_match.\n'
            p=T.parse(src);T.fixpoint(p);equal(('reconciled',()) in p.facts,all(subset))
        check('tell-withdraw-'+''.join(map(lambda x:str(int(x)),subset)),'premise_withdrawal','All three declared bridge premises are necessary for this reconciliation rule',support)
    expert_axes=['retained','designated','report_served','admissible_scope','available']
    for subset in itertools.product([False,True],repeat=5):
        def experts(subset=subset):
            src=header+'\n'.join('fact '+axis+'(expert_a) @A tier native.' for axis,on in zip(expert_axes,subset) if on)
            src+='\nrule ready: ready(E) :- retained(E), designated(E), report_served(E), admissible_scope(E), available(E).\n'
            p=T.parse(src);T.fixpoint(p);equal(('ready',('expert_a',)) in p.facts,all(subset))
            for axis,on in zip(expert_axes,subset):equal((axis,('expert_a',)) in p.facts,on)
        check('tell-expert-axes-'+''.join(str(int(v)) for v in subset),'expert_status',
              'Retention, designation, service, scope and availability remain separate supplied facts',experts)
    for state in ['does_not_remember','does_not_know','denies','admits','believes']:
        def epistemic(state=state):
            src=header+'fact '+state+'(witness_a, signed_draw) @A tier native.\n'
            p=T.parse(src);T.fixpoint(p)
            equal((state,('witness_a','signed_draw')) in p.facts,True)
            equal(('signed',('witness_a',)) in p.facts,False)
            equal(('did_not_sign',('witness_a',)) in p.facts,False)
        check('tell-epistemic-'+state,'testimony_scope','A reported epistemic state alone does not establish the act or its negation',epistemic)


def bootlang_checks():
    from bootlang import terms
    pairs=[('I do not remember signing this.','I remember signing this.'),
           ('Owner paid vendor.','Vendor paid owner.'),
           ('The borrower approved only the pool.','Only the pool approved the borrower.')]
    for i,(a,b) in enumerate(pairs):
        def vocabulary(i=i,a=a,b=b):
            rows=[dict(speaker='S',period='a',text=a),dict(speaker='S',period='b',text=b)]
            r=terms(rows,'S','a','b');require(0<=r['js_divergence_bits']<=1,'divergence outside bounds')
        check('bootlang-vocabulary-'+str(i),'language_measurement','Vocabulary divergence remains bounded for meaning-sensitive examples',vocabulary,input_mode='raw_text')
    def role_probe():
        r=terms([dict(speaker='S',period='a',text='Owner paid vendor.'),dict(speaker='S',period='b',text='Vendor paid owner.')],'S','a','b')
        require(r['js_divergence_bits']>0,'Role reversal has identical token distribution; vocabulary score cannot detect agency')
    check('bootlang-agency-probe','actor_roles','A semantic agency comparison must distinguish payer from recipient',role_probe,kind='capability_probe',input_mode='raw_text')


def vein_checks():
    import vein as V
    schema=V.compile('endian be\nroot packet\ntype packet {\n version: u16\n cents: u32\n}\n')
    for i in range(16):
        def version(i=i):
            with tempfile.TemporaryDirectory() as tmp:
                before=Path(tmp)/'old';after=Path(tmp)/'new'
                a=(1).to_bytes(2,'big')+(50000+i).to_bytes(4,'big')
                b=(2).to_bytes(2,'big')+(50001+i).to_bytes(4,'big')
                before.write_bytes(a);after.write_bytes(b);r=V.compare_files(schema,before,after)
                equal(r['before']['sha256'],hashlib.sha256(a).hexdigest());equal(r['after']['sha256'],hashlib.sha256(b).hexdigest())
                equal({tuple(c['path']) for c in r['changes']},{('version',),('cents',)})
                change=next(c for c in r['changes'] if c['path']==['cents'])
                equal((change['before']['offset'],change['after']['offset']),(2,2))
                equal(change['after']['value']-change['before']['value'],1)
        check('vein-version-'+str(i),'document_versions','One-cent change and version change retain both hashes and byte locators',version,input_mode='synthetic_binary')


def analytics_checks(project):
    if project=='olaps':
        import olaps as O
        rows=[dict(project=p,stage=st,cents=amount) for p in ['A','B'] for st,amount in [('sent',10000),('applied',7000),('credited',3000)]]
        for project in ['A','B']:
            for stage,amount in [('sent',10000),('applied',7000),('credited',3000)]:
                def aggregate(project=project,stage=stage,amount=amount):
                    r=O.analyze(rows,['project','stage'],['cents'],where=dict(project=project,stage=stage),drill=True)
                    equal(next(g for g in r if not g['keys'])['measures']['cents']['total'],amount)
                    ids=next(g for g in r if not g['keys'])['row_indices'];equal(len(ids),1)
                    equal((rows[ids[0]]['project'],rows[ids[0]]['stage']),(project,stage))
                check('olaps-'+project+'-'+stage,'scope_and_drilldown','Explicit project/stage filter agrees with its original row',aggregate)
    else:
        if project=='qulaps': from qulaps import solve
        else: from analytics import solve
        from contradiction import explain
        for total in [0,1,3,7,12]:
            model=dict(domains=dict(applied=list(range(total+1)),refunded=list(range(total+1))),
                       constraints=[dict(weights=dict(applied=1,refunded=1),min=0,max=total)],
                       metric=dict(applied=1,refunded=1))
            def scenarios(model=model,total=total):
                r=solve(model);equal(r['feasible'],(total+1)*(total+2)//2);equal(r['minimum'],0);equal(r['maximum'],total)
                if project=='qulaps':
                    compressed=solve(model,compressed=True)
                    for key in ['feasible','minimum','maximum','additional_states_if_constraint_removed']:equal(compressed[key],r[key])
            check(project+'-credit-alternatives-'+str(total),'alternative_explanations','Count all nonnegative application/refund pairs whose sum is at most the credit',scenarios)
        model=dict(domains=dict(x=[0,1,2]),constraints=[dict(weights=dict(x=1),min=0,max=0),dict(weights=dict(x=1),min=1,max=2),dict(weights=dict(x=1),min=0,max=2)],metric=dict(x=1))
        def core():
            r=explain(model);equal(r['status'],'inconsistent');equal(set(r['constraint_indices']),{0,1})
            for i in r['constraint_indices']:
                equal(solve(dict(model,constraints=[rule for j,rule in enumerate(model['constraints']) if j in set(r['constraint_indices'])-{i}]))['feasible']>0,True)
        check(project+'-contradiction-core','contradictions','Each retained incompatible rule is necessary within the reduced core',core)


def integration_checks(companion):
    """Reviewed source spans -> lifecycle -> accounting -> changed-source invalidation."""
    sys.path.insert(0,str(companion.resolve()))
    import tally as T
    from loom_research.store import GraphStore
    from loom_research import casework as C
    from loom_research.learning import clean_node
    def money(n):return '$'+str(n//100)+'.'+str(n%100).zfill(2)
    for seed in range(12):
        def pipeline(seed=seed):
            rng=random.Random(seed);opening=10000+rng.randrange(10000);paid=rng.randrange(opening);credit=rng.randrange(opening-paid+1)
            values=[('paid',paid),('applied',paid),('credited',credit)]
            with tempfile.TemporaryDirectory() as tmp:
                s=GraphStore(Path(tmp)/'g',create=True);nodes=[];mappings=[]
                for i,(stage,cents) in enumerate(values):
                    text='Synthetic invoice-A '+stage+' amount '+money(cents)+'.'
                    nodes.extend([dict(id='s'+str(i),type='source',origin='synthetic:instrument-'+str(i),locator='synthetic row '+str(i)),
                                  dict(id='p'+str(i),type='passage',text=text,source_ids=['s'+str(i)])])
                    mappings.append(dict(id=str(i),episode='reconciliation',kind='money',context=dict(property='P',loan='L',scope='S',obligation='invoice-A',instrument='I'+str(i)),
                                         evidence=[dict(node_id='p'+str(i),start=0,end=len(text),quote=text)],
                                         money=dict(event_id='event'+str(i),stage=stage,value=str(Decimal(cents)/100),unit='USD')))
                s.apply(dict(schema='loom.graph.batch.v1',batch_id='raw',nodes=nodes))
                C.map_records(s,dict(batch_id='map',reviewer='synthetic test author',mappings=mappings,expected_revision=s.head()[0]))
                e=C.episode(s,'reconciliation');equal(len(e['sentences']),3)
                lane=e['lifecycle']['lanes'][0];equal(set(lane['stages']),{'paid','applied','credited'})
                events=[]
                for obs in lane['observations']:
                    if obs['stage'] not in ('applied','credited'):continue
                    stage='payment_applied' if obs['stage']=='applied' else 'credit_applied'
                    events.append('{id: '+json.dumps(obs['event_id'])+', scope: "invoice-A", day: @2042-01-02, stage: '+json.dumps(stage)+', amount: '+money(int(Decimal(obs['value'])*100))+'}')
                code='receivable_rollforward('+money(opening)+', ['+', '.join(events)+'], '+money(opening-paid-credit)+', "invoice-A")'
                result=T.to_json(T.Interp(out=io.StringIO()).run(code));equal(result['clean'],True);equal(result['calculated_closing'],money(opening-paid-credit))
                equal(sum(len(x['quotes']) for x in e['sentences']),3)
                p=clean_node(next(n for n in s.snapshot()['nodes'] if n['id']=='p1'));p['revision']+=1;p['text']='Synthetic application was reversed.'
                s.apply(dict(schema='loom.graph.batch.v1',batch_id='corrected-source',nodes=[p]))
                e2=C.episode(s,'reconciliation');equal(e2['stale_annotations'],['case:1']);equal(len(e2['sentences']),2)
                require('applied' not in e2['lifecycle']['lanes'][0]['stages'],'superseded application remained usable')
        check('integration-payment-credit-'+str(seed),'cross_engine_workflow',
              'Closing = opening - applied payment - applied credit; paid observation is not counted twice; source change invalidates application',
              pipeline,kind='integration',input_mode='raw_synthetic_records_plus_explicit_reviewed_annotations')


def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--target',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--companion',type=Path)
    p.add_argument('--integration-only',action='store_true')
    a=p.parse_args();sys.path.insert(0,str(a.target.resolve()));sys.path.insert(0,str((a.target/'runtime').resolve()))
    os.environ['SURD_USAGE']='0';os.environ['TALLY_NO_EXPERIMENT_LOG']='1'
    fn={'loom-public':loom_checks,'tally-public':tally_checks,'weave-public':weave_checks,
        'tell':tell_checks,'bootlang':bootlang_checks,'vein':vein_checks}.get(a.repo)
    if not a.integration_only:
        if fn:fn()
        else:analytics_checks(a.repo)
    elif a.repo!='loom-public' or not a.companion:
        p.error('--integration-only requires loom-public and a Tally companion')
    if a.repo=='loom-public' and a.companion:integration_checks(a.companion)
    summary=dict(Counter(r['kind']+':'+r['outcome'] for r in ROWS))
    result=dict(schema='meaning-spectrum-results.v1',repo=a.repo,scenario_count=len(ROWS),summary=summary,scenarios=ROWS,
                scope='Synthetic authored behavior checks; no hosted model inference, blind cohort, real-case truth adjudication or general reader-comprehension measurement',
                current_source_sha256={str(f.relative_to(a.target)):hashlib.sha256(f.read_bytes()).hexdigest() for f in a.target.glob('*.py')})
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(repo=a.repo,scenario_count=len(ROWS),summary=summary,failures=[{k:r[k] for k in ['id','kind','error']} for r in ROWS if r['outcome']=='fail']),indent=2))
    return int(any(r['outcome']=='fail' for r in ROWS))


if __name__=='__main__':raise SystemExit(main())
