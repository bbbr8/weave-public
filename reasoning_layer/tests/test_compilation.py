import copy
import itertools
import tempfile
import unittest
from unittest.mock import patch

from reasoning_layer.contracts import runtime_recipe
from reasoning_layer.core import lower, closure
from reasoning_layer.native import ReferenceBackend
from reasoning_layer.pipeline import ReasoningLayer
from reasoning_layer.tests.test_source_audit import tracked_packet, review_for, Model


class Compilation(unittest.TestCase):
    def program(self):
        return dict(nodes=[dict(id='p'+str(i),text='Atom '+str(i)) for i in range(1,11)], facts=[],
                    rules=[{'if':['p'+str(i) for i in range(1,9)],'then':'p9','basis':'All eight are required'},
                           {'if':['p9'],'then':'p10','basis':'Follow-on rule'}])

    def test_all_256_premise_combinations_preserve_original_closure(self):
        p=self.program()
        for truth in itertools.product([False,True],repeat=8):
            p['facts']=['p'+str(i+1) for i,x in enumerate(truth) if x]
            compiled=lower(p)
            known,_=closure(compiled)
            self.assertEqual(known & {n['id'] for n in p['nodes']},closure(p)[0])
            self.assertTrue(all(len(r['if'])<=6 for r in compiled['rules']))
            self.assertEqual('p9' in known,all(truth))

    def test_compilation_preserves_input_and_avoids_collisions(self):
        p=self.program();p['nodes'].append(dict(id='p9999',text='A real source symbol'));before=copy.deepcopy(p)
        compiled=lower(p)
        self.assertEqual(p,before)
        self.assertNotEqual(compiled['compilation']['steps'][0]['auxiliary'],'p9999')

    def test_single_premise_and_six_premise_rules_need_no_auxiliaries(self):
        p=self.program();p['rules'][0]['if']=p['rules'][0]['if'][:6]
        self.assertEqual(lower(p)['compilation']['steps'],[])

    def test_runtime_recipe_is_deterministic(self):
        self.assertEqual(runtime_recipe(),runtime_recipe())
        self.assertEqual(len(runtime_recipe()),64)

    def test_cache_rejects_a_different_source_recipe(self):
        x=tracked_packet();m=Model(x['program'],x['program'],review_for(x['task']))
        with tempfile.TemporaryDirectory() as d:
            layer=ReasoningLayer(m,ReferenceBackend());layer.run([x['task']],d)
            with patch('reasoning_layer.pipeline.runtime_recipe',return_value='changed'):
                with self.assertRaisesRegex(ValueError,'different package source'):layer.run([x['task']],d)
        self.assertEqual(len(m.calls),2)

    def test_source_change_during_run_preserves_attempts_without_completion(self):
        from pathlib import Path
        x=tracked_packet();m=Model(x['program'],x['program'],review_for(x['task']))
        with tempfile.TemporaryDirectory() as d:
            with patch('reasoning_layer.pipeline.runtime_recipe',side_effect=['before','after']):
                with self.assertRaisesRegex(RuntimeError,'source changed during run'):
                    ReasoningLayer(m,ReferenceBackend()).run([x['task']],d)
            self.assertTrue((Path(d)/'initial-programs.json').exists())
            self.assertFalse((Path(d)/'run.json').exists())


if __name__=='__main__':unittest.main()
