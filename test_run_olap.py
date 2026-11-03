"""Typed OLAP dependency fixtures and independent scalar transfer regressions."""
import copy
import tempfile
import unittest
from pathlib import Path
from weave_run import validate, resolve
from weave_verify import file_digest


def fixture(values=(120, -20), *, count=False):
    parent = {'version': 'weave.olap.integer.v1', 'records': [
        {'entry_id': 'e'+str(i), 'bucket': 'selected', 'amount_units': value,
         'source_id': 's'+str(i), 'origin_id': 'o'+str(i)} for i, value in enumerate(values)],
        'dimensions': [], 'filters': [], 'max_rows': 100, 'unit': 'integer'}
    child = {'version': 'weave.olap.integer.v1', 'records': [
        {'entry_id': 'transferred', 'bucket': 'result', 'amount_units': 0, 'source_id': 'derived', 'origin_id': 'pipeline'},
        {'entry_id': 'offset', 'bucket': 'result', 'amount_units': 7, 'source_id': 'offset', 'origin_id': 'pipeline'}],
        'dimensions': [], 'filters': [], 'max_rows': 100, 'unit': 'count' if count else 'integer'}
    scalar = len(values) if count else sum(v for v in values if v is not None)
    return {'version': 'weave.pipeline.v1', 'data_class': 'synthetic',
        'plan': {'version': 'weave.v1', 'steps': [
            {'id': 'grouped', 'op': 'aggregate', 'inputs': [], 'args': {'program_ref': 'group_program'}},
            {'id': 'adjusted', 'op': 'aggregate', 'inputs': ['grouped'], 'args': {'program_ref': 'adjust_program'}}]},
        'programs': {'group_program': parent, 'adjust_program': child},
        'bindings': [{'step': 'adjusted', 'target': '/records/0/amount_units', 'source_step': 'grouped',
                      'pointer': '/groups/0/row_count' if count else '/groups/0/amount_sum', 'unit': child['unit']}],
        'checks': [{'kind': 'equals', 'step': 'adjusted', 'pointer': '/groups/0/amount_sum', 'value': scalar+7}],
        'node_options': {}}


class OlapPipelineTests(unittest.TestCase):
    def test_amount_and_count_have_separate_contracts(self):
        validate(fixture())
        validate(fixture(count=True))
        packet = fixture(count=True)
        packet['bindings'][0]['unit'] = 'integer'
        with self.assertRaises(ValueError): validate(packet)

    def test_parent_null_does_not_become_zero(self):
        packet = fixture(); step = validate(packet)[1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'result.json'
            path.write_bytes(b'{"groups":[{"amount_sum":null}]}')
            parents = {'grouped': {'path': path, 'sha256': file_digest(path),
                                  'result': {'groups': [{'amount_sum': None}]}}}
            with self.assertRaises(ValueError): resolve(packet, step, parents, packet['programs'])

    def test_empty_result_is_a_controlled_binding_failure(self):
        packet = fixture(); step = validate(packet)[1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'result.json'; path.write_bytes(b'{"groups":[]}')
            parents = {'grouped': {'path': path, 'sha256': file_digest(path), 'result': {'groups': []}}}
            with self.assertRaisesRegex(ValueError, 'Binding source pointer unavailable'):
                resolve(packet, step, parents, packet['programs'])

    def test_signed_and_zero_values_survive_without_mutating_template(self):
        for value in [-20, 0, 100]:
            packet = fixture(); original = copy.deepcopy(packet); step = validate(packet)[1]
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'result.json'
                path.write_bytes(('{"groups":[{"amount_sum":'+str(value)+'}]}').encode())
                parents = {'grouped': {'path': path, 'sha256': file_digest(path),
                                      'result': {'groups': [{'amount_sum': value}]}}}
                program, ledger = resolve(packet, step, parents, packet['programs'])
                self.assertEqual(program['records'][0]['amount_units'], value)
                self.assertEqual(ledger[0]['value'], value)
                self.assertEqual(packet, original)


if __name__ == '__main__': unittest.main()
