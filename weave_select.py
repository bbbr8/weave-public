"""Compare candidate execution bundles under one frozen Weave request.

Model generation is external. Candidates pass the existing verifier before their
declared observations are compared. Duplicate outcomes have one vote-free class.
Disagreement produces a distinguishing observation request, never a majority answer.
This checks supplied artifacts; it neither executes code nor attests execution.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from weave_checks import canonical, pointer, pointer_parts
from weave_verify import digest_json, file_digest, inside, verify


def _next_projection(groups, observations, lookahead):
    # Encode each projection once, keeping JSON types and declared units distinct.
    keys = [[canonical(value) for value in group['observations']] for group in groups]
    options = []
    for index in range(len(observations)):
        buckets = {}
        for row, values in enumerate(keys):
            buckets.setdefault(values[index], []).append(row)
        if len(buckets) == 1:
            continue
        worst = max(map(len, buckets.values()))
        plan = None
        if lookahead == 2:
            branches = []
            for members in buckets.values():
                best = (len(members), 0, None)
                for column in range(len(observations)):
                    if column == index:
                        continue
                    counts = Counter(keys[row][column] for row in members)
                    if len(counts) > 1:
                        best = min(best, (max(counts.values()), -len(counts), column))
                remaining, _, column = best
                branches.append({'answer': groups[members[0]]['observations'][index],
                                 'follow_up': observations[column] if column is not None else None,
                                 'class_count': len(members), 'largest_remaining_class_count': remaining})
            plan = {'branches': branches, 'largest_after_two': max(
                branch['largest_remaining_class_count'] for branch in branches)}
        score = (plan['largest_after_two'] if plan else worst, worst, -len(buckets), index)
        options.append((score, plan))
    (_, worst, _, index), plan = min(options, key=lambda option: option[0])
    choice = {**observations[index], 'largest_remaining_class_count': worst,
              'current_class_count': len(groups),
              'predictions': [{'class_id': g['class_id'], **g['observations'][index]} for g in groups],
              'action': 'Obtain an independently grounded expected value and add a request check.'}
    if plan is not None:
        choice['conditional_plan'] = plan
    return choice


def select(request, catalog, candidates, observations, root=Path('.'), now=None, *, lookahead=1):
    """Return classes and an exact minimax next observation over those classes.

    Candidate shape: {id, directory, receipts}. Observation: {step, pointer}.
    All directories must be below root; all candidates share request/catalog.
    Equivalence is limited to the explicitly declared projections.
    """
    if type(lookahead) is not int or lookahead not in (1, 2):
        raise ValueError('lookahead must be 1 or 2')
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 32:
        raise ValueError('Supply 1..32 candidate bundles')
    if not isinstance(observations, list) or not 1 <= len(observations) <= 32:
        raise ValueError('Supply 1..32 observable projections')
    for spec in observations:
        if not isinstance(spec, dict) or set(spec) != {'step', 'pointer'} or not isinstance(spec['step'], str):
            raise ValueError('Observation needs step and pointer')
        pointer_parts(spec['pointer'])
    if len({canonical(x) for x in observations}) != len(observations):
        raise ValueError('Observations must be distinct')
    seen=set(); accepted=[]; rejected=[]; classes={}
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) != {'id','directory','receipts'}:
            raise ValueError('Candidate needs id, directory, receipts')
        ident=candidate['id']
        if not isinstance(ident,str) or not ident or ident in seen:
            raise ValueError('Candidate IDs must be unique nonempty text')
        seen.add(ident)
        try:
            directory=inside(Path(root), candidate['directory'])
            report=verify(request,catalog,candidate['receipts'],directory,now=now)
            if not report['passed']:
                rejected.append({'id':ident,'issues':report['issues']});continue
            receipts={r['step_id']:r for r in candidate['receipts']}
            values=[]
            for spec in observations:
                receipt=receipts[spec['step']]
                path=inside(directory,receipt['result_path'])
                payload=path.read_bytes()
                # Bind the bytes actually projected, not a subsequent reread.
                import hashlib
                if hashlib.sha256(payload).hexdigest()!=receipt['result_sha256']:
                    raise ValueError('Result changed after verification')
                value=pointer(json.loads(payload),spec['pointer'])
                values.append({'value':value,'unit':receipt.get('result_units',{}).get(spec['pointer'])})
            signature=digest_json(values)
            bucket=classes.setdefault(signature,{'class_id':signature,'candidates':[],'observations':values})
            bucket['candidates'].append(ident)
            accepted.append(ident)
        except (ValueError,KeyError,IndexError,TypeError,OSError) as exc:
            rejected.append({'id':ident,'issues':[{'code':'OBSERVATION_INVALID','message':str(exc)}]})
    groups=sorted(classes.values(),key=lambda x:x['class_id'])
    result={'schema':'weave.selection.v1','request_sha256':digest_json(request),
            'catalog_sha256':digest_json(catalog),'observations':observations,
            'accepted':accepted,'rejected':rejected,'classes':groups,
            'selected':None,'next_observation':None,'engine_execution_proven':False,
            'scope':'supplied checks, artifact bindings and declared observations only'}
    if not groups:
        result['state']='NO_VERIFIED_CANDIDATE'
    elif len(groups)==1:
        result['state']='AGREEMENT_UNDER_CHECKS'
        result['selected']=min(accepted)
    else:
        result['state']='DISAGREEMENT'
        result['next_observation'] = _next_projection(groups, observations, lookahead)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packet',type=Path)
    args=parser.parse_args()
    try:
        packet=json.loads(args.packet.read_text())
        result=select(packet['request'],packet['catalog'],packet['candidates'],packet['observations'],args.packet.parent,
                      lookahead=packet.get('lookahead', 1))
    except (ValueError,KeyError,TypeError,OSError) as exc:
        parser.exit(2,str(exc)+'\n')
    print(json.dumps(result,indent=2))
    return 0 if result['state']=='AGREEMENT_UNDER_CHECKS' else 1


if __name__=='__main__':
    raise SystemExit(main())
