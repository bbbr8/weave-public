"""Weave v0.1: validate a tiny model's engine-neutral plan. No execution."""
import argparse
import json
from pathlib import Path

OPERATIONS = {
    'search': 'loom', 'read': 'loom', 'aggregate': 'olap',
    'calculate': 'tally', 'infer': 'tally', 'solve': 'qulap',
}


def compile_plan(packet):
    if set(packet) != {'version', 'steps'} or packet['version'] != 'weave.v1':
        raise ValueError('Expected weave.v1 and steps')
    steps = packet['steps']
    if not isinstance(steps, list) or not 1 <= len(steps) <= 16:
        raise ValueError('Expected 1..16 steps')
    seen = set()
    compiled = []
    for step in steps:
        if not isinstance(step, dict) or set(step) != {'id', 'op', 'inputs', 'args'}:
            raise ValueError('Each step needs id, op, inputs, args')
        ident, op, inputs, args = (step[k] for k in ('id', 'op', 'inputs', 'args'))
        if not isinstance(ident, str) or not ident.isidentifier() or ident in seen:
            raise ValueError('Step IDs must be unique identifiers')
        if not isinstance(op, str) or op not in OPERATIONS:
            raise ValueError('Unknown operation')
        if not isinstance(inputs, list) or any(not isinstance(x, str) or x not in seen for x in inputs):
            raise ValueError('Inputs must reference earlier steps')
        if not isinstance(args, dict):
            raise ValueError('args must be an object')
        if op == 'search':
            if set(args) != {'query', 'modes', 'top_k'}:
                raise ValueError('Search requires query, modes, top_k')
            if not isinstance(args['query'], str) or not args['query'].strip():
                raise ValueError('Search query must contain text')
            modes = args['modes']
            if not isinstance(modes, list) or not modes or any(x not in ('exact', 'semantic', 'structured') for x in modes):
                raise ValueError('Invalid search modes')
            if type(args['top_k']) is not int or not 1 <= args['top_k'] <= 50:
                raise ValueError('top_k must be 1..50')
        else:
            # Native syntax stays native. A runtime adapter must validate it.
            if set(args) != {'program_ref'} or not isinstance(args['program_ref'], str) or not args['program_ref'].strip():
                raise ValueError('Native operations require a program_ref')
        compiled.append({**step, 'engine': OPERATIONS[op], 'status': 'ADAPTER_REQUIRED'})
        seen.add(ident)
    return {'version': 'weave.plan.v1', 'status': 'VALIDATED_PLAN',
            'executed': False, 'steps': compiled,
            'result_contract': ['source_ids', 'origin_ids', 'native_status', 'coverage',
                                'incomplete', 'runtime_hash', 'elapsed_ms']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packet', type=Path)
    args = parser.parse_args()
    try:
        result = compile_plan(json.loads(args.packet.read_text(encoding='utf-8')))
    except (ValueError, TypeError) as error:
        parser.exit(2, str(error) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
