import copy
import unittest
from weave_checks import validate_check,evaluate_check,changed_paths,pointer


class ExactCheckTests(unittest.TestCase):
    def setUp(self):
        self.outputs={'a':{'x':'0.1','n':2,'object':{'total':12000,'fixed':4500}},'b':{'x':'0.2','n':3,'object':{'total':10200,'fixed':4500}},
                      'out':{'sum':'0.3','difference':-1,'product':6,'set':['b','a'],'flag':True}}
        self.receipts={k:{'source_ids':['s1','s2'],'native_status':'COMPLETE','result_units':{'/x':'cents','/sum':'cents'}} for k in self.outputs}
        self.sources={'s1':{'origin_id':'A'},'s2':{'origin_id':'A'}}
    def run_check(self,c):
        validate_check(c,set(self.outputs));return evaluate_check(c,self.outputs,self.receipts,self.sources)
    def test_exact_arithmetic_and_unit_declarations(self):
        for c in [
            {'kind':'sum','step':'out','pointer':'/sum','terms':[{'step':'a','pointer':'/x'},{'step':'b','pointer':'/x'}],'unit':'cents'},
            {'kind':'difference','step':'out','pointer':'/difference','left':{'step':'a','pointer':'/n'},'right':{'step':'b','pointer':'/n'}},
            {'kind':'product','step':'out','pointer':'/product','terms':[{'step':'a','pointer':'/n'},{'step':'b','pointer':'/n'}]},
        ]:
            self.assertTrue(self.run_check(c)['passed'])
        self.receipts['b']['result_units']['/x']='dollars'
        self.assertEqual(self.run_check({'kind':'sum','step':'out','pointer':'/sum','terms':[{'step':'a','pointer':'/x'},{'step':'b','pointer':'/x'}],'unit':'cents'})['reason'],'UNIT_MISMATCH')
    def test_range_boundaries_are_exact(self):
        c={'kind':'range','step':'out','pointer':'/sum','minimum':'0.3','maximum':'0.3'}
        self.assertTrue(self.run_check(c)['passed']);c['maximum_inclusive']=False
        self.assertFalse(self.run_check(c)['passed'])
    def test_sets_reject_duplicate_results(self):
        c={'kind':'set_equals','step':'out','pointer':'/set','values':['a','b']}
        self.assertTrue(self.run_check(c)['passed']);self.outputs['out']['set'].append('b')
        self.assertFalse(self.run_check(c)['passed'])
    def test_exact_change_set_preserves_independent_fields(self):
        c={'kind':'field_changes','step':'b','pointer':'/object','baseline_step':'a','baseline_pointer':'/object','paths':['/total']}
        self.assertTrue(self.run_check(c)['passed']);self.outputs['b']['object']['fixed']+=1
        result=self.run_check(c);self.assertFalse(result['passed']);self.assertEqual(result['changed_paths'],['/fixed','/total'])
    def test_native_status_and_normalized_completion_are_separate(self):
        self.receipts['out'].update(native_status='INCONSISTENT_MODEL',completion_state='COMPLETE')
        self.assertTrue(self.run_check({'kind':'receipt_status','step':'out','value':'INCONSISTENT_MODEL','completion_state':'COMPLETE'})['passed'])
    def test_unknown_input_is_unresolved_not_wrong(self):
        del self.receipts['out']
        self.assertEqual(self.run_check({'kind':'equals','step':'out','pointer':'/flag','value':True})['status'],'NOT_EVALUATED')
    def test_typed_changes_and_escaped_paths(self):
        self.assertEqual(changed_paths({'a/b':True},{'a/b':1}),['/a~1b'])
        self.assertEqual(changed_paths({'x':[1]},{'x':[1,2]}),['/x'])
        with self.assertRaises(ValueError):pointer({'~x':1},'/~x')
    def test_array_indices_use_ascii_digits_but_object_keys_are_literal(self):
        self.assertEqual(pointer(["first", "second"], "/1"), "second")
        self.assertEqual(pointer({"١": "literal"}, "/١"), "literal")
        for index in ("١", "０１"):
            with self.subTest(index=index), self.assertRaises(ValueError):
                pointer(["first", "second"], "/" + index)

    def test_malformed_checks_are_rejected_before_execution(self):
        cases=[{'kind':'sum','step':'out','pointer':'/sum','terms':[]},
               {'kind':'range','step':'out','pointer':'/sum','minimum':2,'maximum':1},
               {'kind':'equals','step':'missing','pointer':'','value':1},
               {'kind':'equals','step':'out','pointer':'/~2','value':1},
               {'kind':'equals','step':'out','pointer':'/flag','value':True,'extra':'ignored'},
               {'kind':'set_equals','step':'out','pointer':'/set','values':['a','a']}]
        for case in cases:
            with self.subTest(case=case),self.assertRaises(ValueError):validate_check(case,set(self.outputs))



class DotProductTests(unittest.TestCase):
    def test_exact_cancellation_and_validation(self):
        ref = lambda k: {'step': k, 'pointer': ''}
        check = {'kind': 'dot_product', 'step': 'out', 'pointer': '',
                 'pairs': [[ref('a'),ref('b')],[ref('c'),ref('d')]]}
        outputs = {'a': 10**50+1, 'b': '0.1', 'c': -(10**50), 'd': '0.1', 'out': '0.1'}
        receipts = {key: {} for key in outputs}
        validate_check(check, set(outputs))
        self.assertTrue(evaluate_check(check, outputs, receipts, {})['passed'])
        outputs['out'] = 0
        self.assertFalse(evaluate_check(check, outputs, receipts, {})['passed'])
        del receipts['d']
        self.assertEqual(evaluate_check(check, outputs, receipts, {})['status'], 'NOT_EVALUATED')
        for invalid in [[], [[ref('unknown'),ref('a')]], [[ref('a')]], 'wrong']:
            with self.assertRaises(ValueError):
                validate_check({**check, 'pairs': invalid}, set(outputs))


if __name__ == "__main__":
    unittest.main()
