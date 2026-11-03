import copy
import json
import unittest
from pathlib import Path
from weave import compile_plan


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.packet = json.loads(Path(__file__).with_name('example.json').read_text())

    def test_engine_routing_and_execution_status(self):
        result = compile_plan(self.packet)
        self.assertEqual([x['engine'] for x in result['steps']], ['loom', 'olap', 'tally', 'qulap'])
        self.assertFalse(result['executed'])
        self.assertIn('incomplete', result['result_contract'])

    def test_rejects_invalid_model_proposals(self):
        for mutation in ('cycle', 'unknown', 'duplicate', 'unbounded', 'extra', 'native'):
            with self.subTest(mutation=mutation):
                packet = copy.deepcopy(self.packet)
                if mutation == 'cycle': packet['steps'][0]['inputs'] = ['alternatives']
                if mutation == 'unknown': packet['steps'][0]['op'] = 'shell'
                if mutation == 'duplicate': packet['steps'][1]['id'] = 'hits'
                if mutation == 'unbounded': packet['steps'][0]['args']['top_k'] = 1000000
                if mutation == 'extra': packet['steps'][0]['shell'] = 'anything'
                if mutation == 'native': packet['steps'][1]['args'] = {'sql': 'unregistered'}
                with self.assertRaises(ValueError): compile_plan(packet)


if __name__ == '__main__':
    unittest.main()
