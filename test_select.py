import copy
import json
from pathlib import Path
import tempfile
import unittest

from weave_demo import create_fixture
from weave_verify import file_digest
from weave_select import select


class CandidateSelection(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.request,self.catalog,receipts=create_fixture(self.root/'a')
        self.candidates=[dict(id='a',directory='a',receipts=receipts)]
        self.obs=[dict(step='total',pointer='/total_cents')]

    def add(self,ident,amount=None):
        _,_,receipts=create_fixture(self.root/ident)
        if amount is not None:
            path=self.root/ident/'total-result.json';data=json.loads(path.read_text());data['total_cents']=amount
            path.write_text(json.dumps(data));receipts[-1]['result_sha256']=file_digest(path)
        self.candidates.append(dict(id=ident,directory=ident,receipts=receipts))

    def run_selection(self):
        return select(self.request,self.catalog,self.candidates,self.obs,self.root)

    def test_verified_agreement_and_bad_result_rejection(self):
        self.add('b');self.add('wrong',22201)
        result=self.run_selection()
        self.assertEqual(result['state'],'AGREEMENT_UNDER_CHECKS')
        self.assertEqual(result['accepted'],['a','b'])
        self.assertEqual([x['id'] for x in result['rejected']],['wrong'])
        self.assertFalse(result['engine_execution_proven'])

    def weak_request(self):
        # Range is deliberately insufficient to identify the right total.
        self.request['checks']=[dict(kind='range',step='total',pointer='/total_cents',minimum=0,maximum=30000,unit='cents')]

    def test_disagreement_exposes_missing_oracle(self):
        self.weak_request();self.add('wrong',22201)
        result=self.run_selection()
        self.assertEqual(result['state'],'DISAGREEMENT')
        self.assertIsNone(result['selected'])
        self.assertEqual(result['next_observation']['pointer'],'/total_cents')
        self.assertEqual(result['next_observation']['largest_remaining_class_count'],1)

    def test_copies_cannot_outvote_other_outcome(self):
        self.weak_request();self.add('wrong',22201)
        for i in range(8):
            candidate=copy.deepcopy(self.candidates[-1]);candidate['id']='copy'+str(i);self.candidates.append(candidate)
        result=self.run_selection()
        self.assertEqual((result['state'],len(result['classes'])),('DISAGREEMENT',2))

    def test_independent_sum_check_resolves_ambiguity(self):
        self.weak_request();self.add('wrong',22201)
        self.request['checks'].append(dict(kind='sum',step='total',pointer='/total_cents',unit='cents',terms=[dict(step='input',pointer='/amounts/0'),dict(step='input',pointer='/amounts/1')]))
        result=self.run_selection()
        self.assertEqual(result['accepted'],['a'])
        self.assertEqual(result['state'],'AGREEMENT_UNDER_CHECKS')

    def test_paths_bounds_and_duplicate_ids(self):
        for bad in ([],self.candidates*2):
            with self.assertRaises(ValueError):select(self.request,self.catalog,bad,self.obs,self.root)
        self.candidates[0]['directory']='../outside'
        self.assertEqual(self.run_selection()['state'],'NO_VERIFIED_CANDIDATE')

    def test_stale_catalog_and_unavailable_projection_rejected(self):
        self.catalog['observed_at']=0
        self.assertEqual(self.run_selection()['state'],'NO_VERIFIED_CANDIDATE')

    def test_boolean_and_integer_are_distinct_outcomes(self):
        self.weak_request();self.add('b')
        self.obs=[dict(step='total',pointer='/extra')]
        for candidate,value in zip(self.candidates,[True,1]):
            path=self.root/candidate['directory']/'total-result.json';data=json.loads(path.read_text());data['extra']=value
            path.write_text(json.dumps(data));candidate['receipts'][-1]['result_sha256']=file_digest(path)
        self.assertEqual(len(self.run_selection()['classes']),2)

    def test_two_observations_can_favor_a_worse_immediate_split(self):
        self.weak_request()
        rows = [(0,0,0,2), (0,0,1,2), (0,2,1,1), (2,0,1,2),
                (1,1,1,1), (0,1,1,2), (2,0,0,1), (0,0,0,0)]
        self.obs = [dict(step='total', pointer=f'/extra/{i}') for i in range(4)]
        for index, row in enumerate(rows):
            if index:
                self.add(f'candidate-{index}')
            candidate = self.candidates[-1]
            path = self.root / candidate['directory'] / 'total-result.json'
            data = json.loads(path.read_text())
            data['extra'] = row
            path.write_text(json.dumps(data))
            candidate['receipts'][-1]['result_sha256'] = file_digest(path)
        self.assertEqual(self.run_selection()['next_observation']['pointer'], '/extra/3')
        result = select(self.request, self.catalog, self.candidates, self.obs, self.root, lookahead=2)
        next_obs = result['next_observation']
        self.assertEqual(next_obs['pointer'], '/extra/2')
        self.assertEqual(next_obs['largest_remaining_class_count'], 5)
        plan = next_obs['conditional_plan']
        self.assertEqual(plan['largest_after_two'], 2)
        for branch in plan['branches']:
            subset = [r for r in rows if r[2] == branch['answer']['value']]
            second = int(branch['follow_up']['pointer'].split('/')[-1])
            self.assertEqual(branch['largest_remaining_class_count'],
                             max(sum(r[second] == v for r in subset) for v in range(3)))
