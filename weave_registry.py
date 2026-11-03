"""Read and verify a local, explicitly configured capability catalog."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

def fetch_catalog(timeout=50, path=None):
    source = Path(path or os.environ.get('WEAVE_CATALOG') or Path(__file__).with_name('weave-capabilities.json')).resolve()
    raw = source.read_bytes()
    if len(raw) > 1048576:
        raise ValueError('Capability catalog exceeds size limit')
    catalog = json.loads(raw)
    if not isinstance(catalog, dict) or catalog.get('version') != 'weave.capabilities.v1' or not isinstance(catalog.get('operations'), dict):
        raise ValueError('Invalid capability catalog')
    for capability in catalog['operations'].values():
        if not isinstance(capability, dict):
            raise ValueError('Invalid capability entry')
        entry = capability.get('runtime_path')
        runtime = Path(entry) if entry else None
        if runtime and not runtime.is_absolute():
            runtime = source.parent / runtime
        actual = hashlib.sha256(runtime.read_bytes()).hexdigest() if runtime and runtime.is_file() else None
        capability['installed'] = actual is not None
        capability['runtime_sha256'] = actual
        capability['runtime_qualified'] = actual is not None and actual == capability.get('qualified_runtime_sha256')
        programs = capability.get('programs', {})
        if not isinstance(programs, dict):
            raise ValueError('Invalid program catalog')
        for program in programs.values():
            if not isinstance(program, dict):
                raise ValueError('Invalid program entry')
            entry = program.get('path')
            target = Path(entry) if entry else None
            if target and not target.is_absolute():
                target = source.parent / target
            observed = hashlib.sha256(target.read_bytes()).hexdigest() if target and target.is_file() else None
            program['observed_sha256'] = observed
            program['available'] = observed is not None and observed == program.get('sha256')
        capability['available'] = capability['runtime_qualified'] and capability.get('adapter_ready') is True
    catalog['observed_at'] = time.time()
    catalog['registry'] = {'mode':'local', 'source_sha256':hashlib.sha256(raw).hexdigest()}
    return catalog

def summarize_catalog(catalog):
    return {'version':catalog['version'],'registry':catalog.get('registry',{}),'operations':{
        op:{'engine':c.get('engine'),'installed':c.get('installed',False),'adapter_ready':c.get('adapter_ready',False),
            'runtime_qualified':c.get('runtime_qualified',False),'available':c.get('available',False),
            'registered_programs':len(c.get('programs',{}))} for op,c in catalog['operations'].items()}}



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--summary', action='store_true')
    args = parser.parse_args()
    try:
        catalog = fetch_catalog(path=args.catalog)
        print(json.dumps(summarize_catalog(catalog) if args.summary else catalog, indent=2))
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, str(exc)+'\n')

if __name__ == '__main__':
    main()
