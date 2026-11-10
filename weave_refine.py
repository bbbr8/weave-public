"""Bounded counterexample-guided refinement around Weave's existing verifier.

Generators return already-executed candidate bundles; oracles return explicit
expected values with source bindings. This module calls no provider implicitly,
executes no proposed code, and preserves every request revision and diagnostic.
"""
import argparse
import copy
import json
from pathlib import Path
import re

from weave_checks import canonical
from weave_select import select
from weave_verify import digest_json


def refine(request,catalog,candidates,observations,root=Path('.'),oracle=None,
           proposer=None,max_rounds=4,max_candidates=32,now=None):
    if type(max_rounds) is not int or not 1<=max_rounds<=8:raise ValueError('max_rounds must be 1..8')
    if type(max_candidates) is not int or not 1<=max_candidates<=32:raise ValueError('max_candidates must be 1..32')
    current=copy.deepcopy(request);pool=copy.deepcopy(candidates);history=[];seen_oracles=set()
    catalog=copy.deepcopy(catalog);observations=copy.deepcopy(observations)
    initial_hash=digest_json(current);catalog_hash=digest_json(catalog)
    if not isinstance(pool,list) or not 1<=len(pool)<=max_candidates:raise ValueError('Candidate budget exceeded')
    state='BUDGET_EXHAUSTED';selection=None
    for index in range(max_rounds):
        selection=select(current,catalog,pool,observations,root,now)
        row={'round':index,'request_sha256':digest_json(current),'request':copy.deepcopy(current),
             'selection':selection,'candidate_count':len(pool)}
        history.append(row)
        if selection['state']=='AGREEMENT_UNDER_CHECKS':
            state='CONVERGED_UNDER_CHECKS';break
        if index+1==max_rounds:break
        if selection['state']=='DISAGREEMENT':
            if len(current['checks'])>=128:
                state='CHECK_BUDGET_EXHAUSTED';break
            query=copy.deepcopy(selection['next_observation'])
            answer=oracle(copy.deepcopy(query),copy.deepcopy(row)) if oracle else None
            if answer is None:
                state='NEEDS_ORACLE';break
            if not isinstance(answer,dict) or set(answer)-{'value','basis','sources','unit'} or not {'value','basis','sources'}<=set(answer):raise ValueError('Oracle needs value, basis and bound sources')
            if not isinstance(answer['basis'],str) or not answer['basis'].strip():raise ValueError('Oracle basis is required')
            supplied=answer['sources'];sources={s['id']:s['sha256'] for s in current.get('sources',[])}
            if not isinstance(supplied,list) or not supplied or len(supplied)>128:raise ValueError('Oracle needs declared sources')
            if any(not isinstance(s,dict) or set(s)!={'id','sha256'} or not isinstance(s.get('id'),str) or s.get('id') not in sources or s.get('sha256')!=sources[s['id']] for s in supplied):raise ValueError('Oracle source binding mismatch')
            if len({s['id'] for s in supplied})!=len(supplied):raise ValueError('Duplicate oracle source IDs')
            check={'kind':'equals','step':query['step'],'pointer':query['pointer'],'value':answer['value']}
            units={p['unit'] for p in query['predictions']}
            unit=answer.get('unit',next(iter(units)) if len(units)==1 else None)
            if len(units)>1 and unit is None:raise ValueError('Oracle unit required for mixed observed units')
            if unit is not None:
                if not isinstance(unit,str) or not unit:raise ValueError('Oracle unit must be text')
                if len(units)==1 and next(iter(units)) is not None and unit not in units:raise ValueError('Oracle unit disagrees with observed unit')
                check['unit']=unit
            key=canonical(check)
            if key in seen_oracles or key in {canonical(c) for c in current['checks']}:
                state='NO_PROGRESS';break
            seen_oracles.add(key);row['oracle']={**copy.deepcopy(answer),'observation':query,'added_check':check}
            current['checks'].append(check)
        elif proposer:
            additions=proposer(copy.deepcopy(row),max_candidates-len(pool))
            if not isinstance(additions,list) or len(additions)>max_candidates-len(pool):raise ValueError('Proposer exceeded candidate budget')
            if not additions:
                state='NO_VERIFIED_CANDIDATE';break
            existing={c['id'] for c in pool}
            for c in additions:
                if not isinstance(c,dict) or not isinstance(c.get('id'),str) or not c['id'] or c['id'] in existing:raise ValueError('Proposer must supply fresh candidate IDs')
                existing.add(c['id'])
            pool.extend(copy.deepcopy(additions));row['proposed_ids']=[c['id'] for c in additions]
        else:
            state='NO_VERIFIED_CANDIDATE';break
    return {'schema':'weave.refinement.v1','state':state,'initial_request_sha256':initial_hash,
            'catalog_sha256':catalog_hash,'observations_sha256':digest_json(observations),
            'final_request':current,'final_request_sha256':digest_json(current),'rounds':history,
            'selection':selection,'selected':selection['selected'] if state=='CONVERGED_UNDER_CHECKS' else None,
            'max_rounds':max_rounds,'max_candidates':max_candidates,
            'oracle_semantics_independently_verified':False,
            'scope':'bounded supplied verifier checks, explicit oracle assertions and hash-bound artifacts'}


def demonstration():
    """Run a synthetic disagreement -> source-sum oracle -> re-verification loop."""
    import tempfile
    from weave_demo import create_fixture
    from weave_verify import file_digest
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);request,catalog,good=create_fixture(root/'good')
        _,_,bad=create_fixture(root/'bad');path=root/'bad/total-result.json'
        value=json.loads(path.read_text());value['total_cents']+=1;path.write_text(json.dumps(value));bad[-1]['result_sha256']=file_digest(path)
        request['checks']=[{'kind':'range','step':'total','pointer':'/total_cents','minimum':0,'maximum':30000,'unit':'cents'}]
        candidates=[{'id':'correct','directory':'good','receipts':good},{'id':'wrong','directory':'bad','receipts':bad}]
        for i in range(8):
            candidate=copy.deepcopy(candidates[1]);candidate['id']='wrong-copy-'+str(i);candidates.append(candidate)
        def oracle(query,history):
            total=sum(json.loads((root/'good'/name).read_text())['cents'] for name in ('source-a.json','source-b.json'))
            return {'value':total,'basis':'independent integer sum of two synthetic input records',
                    'sources':[{'id':s['id'],'sha256':s['sha256']} for s in request['sources'] if s['id'] in ('a','b')]}
        return refine(request,catalog,candidates,[{'step':'total','pointer':'/total_cents'}],root,oracle=oracle)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('packet',type=Path,nargs='?');parser.add_argument('--demo',action='store_true');a=parser.parse_args()
    if bool(a.packet)==a.demo:parser.error('Supply a packet or --demo')
    try:
        if a.demo:
            result=demonstration();print(json.dumps(result,indent=2));return 0 if result['state']=='CONVERGED_UNDER_CHECKS' else 1
        packet=json.loads(a.packet.read_text())
        if not isinstance(packet,dict):raise ValueError('Refinement packet must be an object')
        answers=packet.get('oracle_answers',[])
        def oracle(query,history):
            return next((x['answer'] for x in answers if x['step']==query['step'] and x['pointer']==query['pointer']),None)
        result=refine(packet['request'],packet['catalog'],packet['candidates'],packet['observations'],a.packet.parent,
                      oracle=oracle,max_rounds=packet.get('max_rounds',4))
    except (ValueError,KeyError,TypeError,OSError) as exc:parser.exit(2,str(exc)+'\n')
    print(json.dumps(result,indent=2));return 0 if result['state']=='CONVERGED_UNDER_CHECKS' else 1


if __name__=='__main__':raise SystemExit(main())
