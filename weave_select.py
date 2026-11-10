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


def select(request, catalog, candidates, observations, root=Path('.'), now=None):
    """Return classes and an exact minimax next observation over those classes.

    Candidate shape: {id, directory, receipts}. Observation: {step, pointer}.
    All directories must be below root; all candidates share request/catalog.
    Equivalence is limited to the explicitly declared projections.
    """
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
        options=[]
        for index,spec in enumerate(observations):
            partitions=Counter(canonical(g['observations'][index]) for g in groups)
            if len(partitions)>1:
                options.append((max(partitions.values()),-len(partitions),index))
        worst,_,index=min(options)
        result['next_observation']={**observations[index],
            'largest_remaining_class_count':worst,'current_class_count':len(groups),
            'predictions':[{'class_id':g['class_id'],**g['observations'][index]} for g in groups],
            'action':'Obtain an independently grounded expected value and add a request check.'}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packet',type=Path)
    args=parser.parse_args()
    try:
        packet=json.loads(args.packet.read_text())
        result=select(packet['request'],packet['catalog'],packet['candidates'],packet['observations'],args.packet.parent)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        parser.exit(2,str(exc)+'\n')
    print(json.dumps(result,indent=2))
    return 0 if result['state']=='AGREEMENT_UNDER_CHECKS' else 1


if __name__=='__main__':
    raise SystemExit(main())
