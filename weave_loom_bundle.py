"""Explicit single-read projection of a preserved native Loom search/read bundle."""
import copy
import json
from pathlib import Path
import weave_loom
from weave_verify import digest_json, file_digest, verify


def projected(root):
    """Reconstruct the projection from checked saved inputs, without native calls."""
    root=Path(root); native=root/'native'
    load=lambda path:json.loads(path.read_text())
    program=weave_loom.validate(load(root/'program.json'))
    if (root/'program.json').read_bytes()!=(native/'program.json').read_bytes():
        raise ValueError('Loom projection program changed')
    request=load(native/'request.json');catalog=load(native/'catalog.json');receipts=load(native/'receipts.json')
    if len(receipts)!=2 or [r['op'] for r in receipts]!=['search','read']:
        raise ValueError('Expected complete native search/read bundle')
    report=verify(request,catalog,receipts,native,now=catalog['observed_at'])
    if not report['passed']:raise ValueError('Nested Loom verification failed')
    selected=weave_loom.validate_native(program,load(native/'native-search.json'),load(native/'native-read.json'))
    result=load(native/'read-result.json')
    expected={'document_ids':selected,'documents':load(native/'native-read.json'),
              'independent_origins':len({d['metadata']['origin_id'] for d in result['documents']}),
              'origin_ids':sorted({d['metadata']['origin_id'] for d in result['documents']})}
    if digest_json(result)!=digest_json(expected):raise ValueError('Nested read normalization changed')
    if (root/'result.json').read_bytes()!=(native/'read-result.json').read_bytes():
        raise ValueError('Projected read result changed')
    step={'id':'selected','op':'read','inputs':[],'args':{'program_ref':'loom/corpus-read-v1'}}
    plan={'version':'weave.v1','steps':[step]}
    sources=[{'id':d['id'],'origin_id':d['origin_id'],'path':'native/'+d['id']+'.source.json',
              'sha256':file_digest(native/(d['id']+'.source.json'))} for d in program['documents']]
    for doc,source in zip(program['documents'],sources):
        if digest_json(load(root/source['path']))!=digest_json(doc):raise ValueError('Nested corpus source changed')
    checks=[{'kind':'equals','step':'selected','pointer':'','value':result}]
    outer_request={'version':'weave.request.v1','plan':plan,'sources':sources,
                   'required_sources':{'selected':[s['id'] for s in sources]},'checks':checks}
    cap=copy.deepcopy(catalog['operations']['read'])
    cap['programs']={'loom/corpus-read-v1':{'sha256':file_digest(root/'program.json'),'available':True}}
    outer_catalog={'version':'weave.capabilities.v1','data_class':'synthetic','observed_at':catalog['observed_at'],
                   'registry':{'mode':'native-bundle-read-projection'},'operations':{'read':cap}}
    receipt=copy.deepcopy(receipts[1])
    receipt.update(step_id='selected',plan_sha256=digest_json(plan),args_sha256=digest_json(step['args']),
        input_hashes={},result_path='result.json',result_sha256=file_digest(root/'result.json'),
        nested_receipts_sha256=file_digest(native/'receipts.json'),
        nested_request_sha256=file_digest(native/'request.json'),
        nested_catalog_sha256=file_digest(native/'catalog.json'),
        nested_receipt_digests=[digest_json(r) for r in receipts],
        result_units={'/independent_origins':'count'},
        projection='read result from preserved native search/read bundle')
    return outer_request,outer_catalog,[receipt]


def audit(root):
    root=Path(root)
    expected=projected(root)
    for name,value in zip(['request.json','catalog.json','receipts.json'],expected):
        if digest_json(json.loads((root/name).read_text()))!=digest_json(value):
            raise ValueError('Loom projection artifact changed: '+name)
    request,catalog,receipts=expected
    report=verify(request,catalog,receipts,root,now=catalog['observed_at'])
    if not report['passed']:raise ValueError('Loom projection verification failed')
    return report


def run(program_path,runtime,output):
    program_path,output=Path(program_path),Path(output)
    raw=program_path.read_bytes();weave_loom.validate(json.loads(raw))
    output.mkdir(exist_ok=False)
    (output/'program.json').write_bytes(raw)
    report=weave_loom.run(output/'program.json',Path(runtime),output/'native')
    if not report['passed']:raise ValueError('Native Loom bundle failed')
    (output/'result.json').write_bytes((output/'native/read-result.json').read_bytes())
    for name,value in zip(['request.json','catalog.json','receipts.json'],projected(output)):
        with (output/name).open('xb') as stream:stream.write(json.dumps(value,indent=2).encode())
    report=audit(output)
    with (output/'verification.json').open('xb') as stream:stream.write(json.dumps(report,indent=2).encode())
    return report
