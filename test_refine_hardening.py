import copy
import contextlib
import io
import sys
import unittest
from unittest.mock import patch
import test_refine
from weave_refine import refine
from weave_refine import main


class RefinementHardening(unittest.TestCase):
    setUp=test_refine.Refinement.setUp
    oracle=test_refine.Refinement.oracle
    def test_catalog_and_observations_frozen_against_callback_closure(self):
        original=copy.deepcopy(self.catalog)
        def oracle(q,h):
            answer=self.oracle(q,h);self.catalog.clear();self.obs[0]['pointer']='/gone'
            self.request['checks'].clear()
            return answer
        before=copy.deepcopy(self.request)
        r=refine(self.request,self.catalog,self.candidates,self.obs,self.root,oracle=oracle)
        self.assertEqual(r['selected'],'good')
        from weave_verify import digest_json
        self.assertEqual(r['catalog_sha256'],digest_json(original))
        self.assertEqual(r['initial_request_sha256'],digest_json(before))

    def test_unhashable_oracle_id_is_input_error(self):
        def oracle(q,h):
            a=self.oracle(q,h);a['sources'][0]['id']=[];return a
        with self.assertRaises(ValueError):refine(self.request,self.catalog,self.candidates,self.obs,self.root,oracle=oracle)

    def test_oracle_unit_must_match_observed_unit(self):
        def oracle(q,h):
            a=self.oracle(q,h);a['unit']='dollars';return a
        with self.assertRaises(ValueError):refine(self.request,self.catalog,self.candidates,self.obs,self.root,oracle=oracle)

    def test_check_budget_stops_before_oracle_side_effect(self):
        self.request['checks']*=128;calls=[]
        r=refine(self.request,self.catalog,self.candidates,self.obs,self.root,oracle=lambda *a:calls.append(1))
        self.assertEqual(r['state'],'CHECK_BUDGET_EXHAUSTED');self.assertEqual(calls,[])

    def test_duplicate_proposals_rejected_before_reverification(self):
        strong=copy.deepcopy(self.request);strong['checks']=[dict(kind='equals',step='total',pointer='/total_cents',value=22200)]
        def propose(h,b):return [self.candidates[0],self.candidates[0]]
        with self.assertRaisesRegex(ValueError,'fresh candidate IDs'):
            refine(strong,self.catalog,[self.candidates[1]],self.obs,self.root,proposer=propose)

    def test_cli_rejects_nonobject_roots_without_traceback(self):
        for raw in ['null','[]','true','"text"']:
            path=self.root/'malformed.json';path.write_text(raw)
            with self.subTest(raw=raw),patch.object(sys,'argv',['weave_refine.py',str(path)]),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code,2)
