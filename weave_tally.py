"""Run a bounded integer arithmetic program through native Tally and verify it.

Run with an explicitly configured Tally runtime. Programs contain literal integers, never executable
Tally source. Each invocation preserves native JSON and a snapshot catalog.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import time
from weave_verify import digest_json, file_digest, verify


def expression(program):
    if not isinstance(program, dict) or set(program) != {'version', 'operation', 'terms', 'unit'}:
        raise ValueError('Expected version, operation, terms and unit')
    if program['version'] != 'weave.tally.integer.v1':
        raise ValueError('Unsupported program version')
    terms = program['terms']
    if not isinstance(terms, list) or not 2 <= len(terms) <= 16:
        raise ValueError('Expected 2..16 integer terms')
    if any(type(x) is not int or abs(x) > 10**12 for x in terms):
        raise ValueError('Literal integers bounded to 10^12 required')
    if not isinstance(program['unit'], str) or not 1 <= len(program['unit']) <= 64:
        raise ValueError('Unit required')
    op = program['operation']
    if op == 'sum': symbol, expected = '+', sum(terms)
    elif op == 'difference' and len(terms) == 2: symbol, expected = '-', terms[0] - terms[1]
    elif op == 'product': symbol, expected = '*', math.prod(terms)
    else: raise ValueError('Supported operations: sum, two-term difference, product')
    return symbol.join('(' + str(x) + ')' for x in terms), expected


def invoke(runtime, expr):
    result = subprocess.run([str(runtime), 'eval', expr, '--json', '--max-steps', '1000'],
                            capture_output=True, text=True, timeout=10, check=False)
    if result.returncode or len(result.stdout) > 1024*1024:
        raise ValueError('Native Tally failed or exceeded output bound')
    value = json.loads(result.stdout)
    if value.get('schema') != 'tally.eval.v1' or value.get('ok') is not True or value.get('expr') != expr:
        raise ValueError('Native Tally response contract failed')
    if type(value.get('value')) is not int or value.get('error') is not None:
        raise ValueError('Native integer result required')
    return value


def fingerprint(runtime, native):
    interpreter = native.get('interpreter', {})
    hashes = interpreter.get('sha256', {})
    if interpreter.get('version') != '0.28' or not isinstance(hashes, dict) or 'tally.py' not in hashes:
        raise ValueError('Tally 0.28 interpreter fingerprint required')
    folder = runtime.resolve().parent
    for name, sha in hashes.items():
        if Path(name).name != name or not name.endswith('.py') or file_digest(folder/name) != sha:
            raise ValueError('Native interpreter file hash mismatch')
    return digest_json({'launcher_sha256': file_digest(runtime), 'interpreter': interpreter})


def run(program_path, runtime, output):
    program_path, runtime, output = Path(program_path), Path(runtime), Path(output)
    raw = program_path.read_bytes()
    if len(raw) > 4096: raise ValueError('Program exceeds 4096 bytes')
    program = json.loads(raw)
    expr, expected = expression(program)
    output.mkdir(exist_ok=False)
    def save(name, value):
        with (output/name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
    (output/'program.json').write_bytes(raw)
    probe = invoke(runtime, '0')
    pin = fingerprint(runtime, probe)
    started = time.perf_counter()
    native = invoke(runtime, expr)
    elapsed = (time.perf_counter()-started)*1000
    save('native.json', native)
    if fingerprint(runtime, native) != pin or program_path.read_bytes() != raw:
        raise ValueError('Runtime or program changed during execution')
    save('result.json', {'value': native['value']})
    source_sha = file_digest(output/'program.json')
    plan = {'version':'weave.v1','steps':[{'id':'arithmetic','op':'calculate','inputs':[],
                                         'args':{'program_ref':'tally/integer-v1'}}]}
    request = {'version':'weave.request.v1','plan':plan,'sources':[
        {'id':'program','origin_id':'integer-input','path':'program.json','sha256':source_sha}],
        'required_sources':{'arithmetic':['program']},'checks':[
            {'kind':'equals','step':'arithmetic','pointer':'/value','value':expected},
            {'kind':'receipt_status','step':'arithmetic','value':'ok=true','completion_state':'COMPLETE'}]}
    catalog = {'version':'weave.capabilities.v1','data_class':'synthetic','observed_at':time.time(),
               'registry':{'mode':'native-adapter-snapshot'},'operations':{'calculate':{
                   'engine':'tally','installed':True,'available':True,'adapter_ready':True,
                   'runtime_sha256':pin,'qualified_runtime_sha256':pin,
                   'programs':{'tally/integer-v1':{'sha256':source_sha,'available':True}}}}}
    receipts = [{'step_id':'arithmetic','engine':'tally','op':'calculate','executed':True,
                 'native_status':'ok=true','completion_state':'COMPLETE','incomplete':False,
                 'elapsed_ms':elapsed,'coverage':{'literal_terms':len(program['terms'])},
                 'plan_sha256':digest_json(plan),'args_sha256':digest_json(plan['steps'][0]['args']),
                 'runtime_sha256':pin,'program_sha256':source_sha,'source_ids':['program'],
                 'origin_ids':['integer-input'],'input_hashes':{},'result_path':'result.json',
                 'result_sha256':file_digest(output/'result.json'),
                 'native_result_path':'native.json','native_result_sha256':file_digest(output/'native.json'),
                 'result_units':{'/value':program['unit']}}]
    report = verify(request,catalog,receipts,output)
    for name,value in [('probe.json',probe),('request.json',request),('catalog.json',catalog),
                       ('receipts.json',receipts),('verification.json',report)]: save(name,value)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('program',type=Path)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    try:
        report=run(args.program,args.runtime,args.out)
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),
                          'receipt_directory':str(args.out),'scope':'Native integer arithmetic adapter'}))
        return 0 if report['passed'] else 1
    except (ValueError,OSError,subprocess.SubprocessError) as exc: parser.exit(2,str(exc)+'\n')


if __name__ == '__main__': raise SystemExit(main())
