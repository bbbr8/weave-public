import copy
import json
from pathlib import Path
import tempfile
import unittest
from weave_demo import create_fixture
from weave_verify import file_digest
from weave_refine import refine


class Refinement(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.request,self.catalog,good=create_fixture(self.root/'good')
        _,_,bad=create_fixture(self.root/'bad');p=self.root/'bad/total-result.json'
        result=json.loads(p.read_text());result['total_cents']+=1;p.write_text(json.dumps(result));bad[-1]['result_sha256']=file_digest(p)
        self.candidates=[{'id':'good','directory':'good','receipts':good},{'id':'bad','directory':'bad','receipts':bad}]
        self.request['checks']=[dict(kind='range',step='total',pointer='/total_cents',minimum=0,maximum=30000,unit='cents')]
        self.obs=[dict(step='total',pointer='/total_cents')]

    def oracle(self,q,h):
        return {'value':22200,'basis':'independent integer sum of supplied source values',
                'sources':[{'id':x['id'],'sha256':x['sha256']} for x in self.request['sources'] if x['id'] in ['a','b']]}

    def test_feedback_refines_request_and_preserves_inputs(self):
        before=copy.deepcopy(self.request)
        r=refine(self.request,self.catalog,self.candidates,self.obs,self.root,oracle=self.oracle)
        self.assertEqual((r['state'],r['selected']),('CONVERGED_UNDER_CHECKS','good'))
        self.assertEqual(len(r['rounds']),2);self.assertEqual(self.request,before)
        self.assertIn('oracle',r['rounds'][0]);self.assertNotEqual(r['initial_request_sha256'],r['final_request_sha256'])

    def test_oracle_gap_and_budget_are_distinct(self):
        self.assertEqual(refine(self.request,self.catalog,self.candidates,self.obs,self.root)['state'],'NEEDS_ORACLE')
        r=refine(self.request,self.catalog,self.candidates,self.obs,self.root,oracle=self.oracle,max_rounds=1)
        self.assertEqual(r['state'],'BUDGET_EXHAUSTED');self.assertIsNone(r['selected'])

    def test_unbound_oracle_is_rejected(self):
        def bad(q,h):
            answer=self.oracle(q,h);answer['sources'][0]['sha256']='0'*64;return answer
        with self.assertRaises(ValueError):refine(self.request,self.catalog,self.candidates,self.obs,self.root,oracle=bad)

    def test_copies_do_not_outvote_and_callbacks_get_copies(self):
        for i in range(8):
            row=copy.deepcopy(self.candidates[1]);row['id']='copy'+str(i);self.candidates.append(row)
        def oracle(query,history):
            answer=self.oracle(query,history)
            history['request']['checks'].clear();query['pointer']='/mutated'
            return answer
        r=refine(self.request,self.catalog,self.candidates,self.obs,self.root,oracle=oracle)
        self.assertEqual(r['selected'],'good')
        self.assertEqual(len(r['final_request']['checks']),2)

    def test_recovery_proposer_budget_and_generation(self):
        strong=copy.deepcopy(self.request);strong['checks'][0]={'kind':'equals','step':'total','pointer':'/total_cents','value':22200}
        calls=[]
        def proposer(history,budget):
            calls.append(budget);return [self.candidates[0]]
        r=refine(strong,self.catalog,[self.candidates[1]],self.obs,self.root,proposer=proposer)
        self.assertEqual(r['selected'],'good');self.assertEqual(calls,[31])
