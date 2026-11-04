import copy
import json
from pathlib import Path
import random
import tempfile
import unittest
from reasoning_layer.contracts import digest,make_task,policy_for,route,validate_task
from reasoning_layer.core import closure,resolve,reference_execute,validate_program
from reasoning_layer.curriculum import qualify
from reasoning_layer.examples import rules_packet,arithmetic_packet
from reasoning_layer.native import ReferenceBackend,MacBackend
from reasoning_layer.pipeline import ReasoningLayer,execute_packets

class Contracts(unittest.TestCase):
    def setUp(self):
        x=rules_packet();self.t=x['task'];self.p=x['program']
    def codes(self,p=None,t=None):return {x['code'] for x in validate_program(t or self.t,p or self.p)['diagnostics']}
    def test_sourced_rule_executes(self):
        self.assertTrue(validate_program(self.t,self.p)['valid']);self.assertEqual(reference_execute(self.t,self.p)['answer'],'True')
    def test_unknown_is_not_false(self):self.assertEqual(resolve(self.t,self.p,set())['answer'],'Unknown')
    def test_explicit_refutation(self):self.assertEqual(resolve(self.t,self.p,{'p3'})['answer'],'False')
    def test_both_states_are_distinct(self):
        r=resolve(self.t,self.p,{'p2','p3'});self.assertEqual((r['state'],r['answer']),('inconsistent','ABSTAIN'))
    def test_binary_open_world_abstains(self):
        self.t['labels']=['yes','no'];self.t['policy']=policy_for(self.t['labels']);self.assertEqual(resolve(self.t,self.p,set())['answer'],'ABSTAIN')
    def test_nonentailment_requires_explicit_semantics(self):
        t=make_task('b','No facts.','Does the claim follow?',['Entailment','Contradiction']);t['policy']['undetermined']='Contradiction';self.assertTrue(validate_task(t))
        t['policy']=policy_for(t['labels'],negative_semantics='non_entailment');self.assertEqual(validate_task(t),[]);self.assertEqual(resolve(t,self.p,set())['answer'],'Contradiction')
    def test_incomplete_state_policy(self):
        del self.t['policy']['refuted'];self.assertIn('policy omits state: refuted',validate_task(self.t))
    def test_policy_cannot_turn_conflict_into_true(self):
        self.t['policy']['inconsistent']='True';self.assertTrue(validate_task(self.t))
    def test_context_mutation_detected(self):
        self.t['context']+='new';self.assertIn('context hash differs',validate_task(self.t))
    def test_invalid_labels_do_not_crash(self):
        self.t['labels']=[{}];self.assertTrue(validate_task(self.t))
    def test_question_hash_changed(self):
        self.p['question_sha256']='wrong';self.assertIn('question_changed',self.codes())
    def test_signature_changed(self):
        self.p['query_signature']=dict(self.p['query_signature'],modality='required');self.assertIn('query_signature_changed',self.codes())
    def test_goal_hash_changed(self):
        self.p['goals'][0]['question_sha256']='wrong';self.assertIn('goal_question_changed',self.codes())
    def test_missing_negative_goal(self):
        self.p['goals']=self.p['goals'][:1];self.assertIn('answer_coverage_incomplete',self.codes())
    def test_goal_collision(self):
        self.p['goals'][1]['node']='p2';self.assertIn('answer_goal_collision',self.codes())
    def test_wrong_label(self):
        self.p['goals'][0]['label']='False';self.assertIn('goal_label_changed',self.codes())
    def test_bad_quote(self):
        self.p['nodes'][0]['quotes'][0]['quote']='File K is a defendant.';self.assertIn('program_structure',self.codes())
    def test_fact_without_quote(self):
        self.p['nodes'][0]['quotes']=[];self.assertIn('unsourced_fact',self.codes())
    def test_quote_match_is_not_semantic_certification(self):
        self.p['nodes'][0]['text']='File K is a defendant.'
        r=validate_program(self.t,self.p);self.assertTrue(r['valid']);self.assertIn('source entailment requires review',r['semantic_assurance'])
    def test_copied_tags_do_not_hide_modality_cue(self):
        self.p['nodes'][1]['text']='File K must be approved.';self.assertIn('possible_modality_strengthening',self.codes())
    def test_query_used_as_fact_source_rejected(self):
        self.p['nodes'][0]['quotes'][0]['source_id']='question';self.assertIn('program_structure',self.codes())
    def test_duplicate_node(self):
        self.p['nodes'].append(copy.deepcopy(self.p['nodes'][0]));self.assertIn('program_structure',self.codes())
    def test_rule_undeclared_node(self):
        self.p['rules'][0]['then']='p99';self.assertIn('program_structure',self.codes())
    def test_explicitly_sourced_goal_can_be_fact(self):
        self.p['goals'][0]['node']='p1';self.assertTrue(validate_program(self.t,self.p)['valid'])
    def test_choice_coverage_and_conflict(self):
        self.t['labels']=['0','1'];self.t['policy']=policy_for(self.t['labels'])
        self.p['goals']=[dict(g,role='choice',label=str(i)) for i,g in enumerate(self.p['goals'])]
        self.assertTrue(validate_program(self.t,self.p)['valid']);self.assertEqual(resolve(self.t,self.p,{'p2','p3'})['state'],'conflicting')
    def test_derived_nodes_need_no_quote(self):self.assertTrue(validate_program(self.t,self.p)['valid'])
    def test_reference_is_labeled(self):self.assertFalse(reference_execute(self.t,self.p)['native'])
    def test_auto_route_uses_observable_source(self):
        self.t['operation']='auto';self.assertEqual(route(self.t)['operation'],'rules')
        self.t=make_task('r','A short plain passage.','What follows?',['yes','no'],operation='auto');self.assertEqual(route(self.t)['operation'],'direct')
    def test_random_closures_against_reachability_oracle(self):
        rng=random.Random(19)
        for _ in range(100):
            nodes=['p'+str(i) for i in range(12)];facts=rng.sample(nodes,3)
            edges=[(rng.choice(nodes),rng.choice(nodes)) for _ in range(22)]
            p=dict(facts=facts,rules=[{'if':[a],'then':b,'basis':'test'} for a,b in edges])
            expected=set(facts);queue=list(facts)
            while queue:
                x=queue.pop()
                for a,b in edges:
                    if a==x and b not in expected:expected.add(b);queue.append(b)
            self.assertEqual(closure(p)[0],expected)

class Arithmetic(unittest.TestCase):
    def setUp(self):x=arithmetic_packet();self.t=x['task'];self.p=x['program']
    def test_exact_money(self):
        self.assertTrue(validate_program(self.t,self.p)['valid']);self.assertEqual(reference_execute(self.t,self.p)['answer'],'$341.00')
    def test_injection(self):
        self.p['calculation']['formula']='__import__("os").system("anything")';self.assertFalse(validate_program(self.t,self.p)['valid'])
    def test_unsourced_value(self):
        self.p['calculation']['operands'][0]['value']='999.00';self.assertFalse(validate_program(self.t,self.p)['valid'])
    def test_division_zero(self):
        self.p['calculation']['formula']='fee_a / 0';self.assertFalse(validate_program(self.t,self.p)['valid'])
    def test_units(self):
        self.p['calculation']['formula']='fee_a + 2';self.assertFalse(validate_program(self.t,self.p)['valid'])
    def test_overprecision_money(self):
        self.p['calculation']['operands'][0]['value']='148.350';self.assertFalse(validate_program(self.t,self.p)['valid'])
    def test_arithmetic_route(self):
        self.t['operation']='auto';self.assertEqual(route(self.t)['operation'],'arithmetic')

class FakeModel:
    def __init__(self,answers):self.answers=list(answers);self.calls=[]
    def respond(self,prompt,schema,folder):self.calls.append(prompt);return self.answers.pop(0)

class Pipeline(unittest.TestCase):
    def test_one_bounded_repair_preserves_first_program(self):
        x=rules_packet();bad=copy.deepcopy(x['program']);bad['goals']=bad['goals'][:1]
        model=FakeModel([{'programs':[bad]},{'reviews':[dict(id=x['task']['id'],accepted=True,issues=['Missing negative route repaired'],program=x['program'])]}])
        with tempfile.TemporaryDirectory() as d:
            r=ReasoningLayer(model,ReferenceBackend(),source_accounting=False).run([x['task']],d)
            self.assertEqual(r[x['task']['id']]['answer'],'True');self.assertEqual(len(model.calls),2)
            original=json.loads((Path(d)/'initial-programs.json').read_text());self.assertEqual(len(original[x['task']['id']]['goals']),1)
            self.assertIn('answer_coverage_incomplete',model.calls[1])
    def test_review_can_decline_without_forcing_answer(self):
        x=rules_packet();m=FakeModel([{'programs':[x['program']]},{'reviews':[dict(id=x['task']['id'],accepted=False,issues=['unsupported meaning'],program=x['program'])]}])
        with tempfile.TemporaryDirectory() as d:self.assertEqual(ReasoningLayer(m,ReferenceBackend(),source_accounting=False).run([x['task']],d)[x['task']['id']]['answer'],'ABSTAIN')
    def test_private_input_never_reaches_hosted_model(self):
        x=rules_packet();x['task']['data_class']='case_private';m=FakeModel([])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):ReasoningLayer(m,ReferenceBackend(),source_accounting=False).run([x['task']],d)
        self.assertEqual(m.calls,[])
    def test_gold_field_never_reaches_model(self):
        x=rules_packet();x['task']['gold']='True';m=FakeModel([])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):ReasoningLayer(m,ReferenceBackend(),source_accounting=False).run([x['task']],d)
        self.assertEqual(m.calls,[])
    def test_unknown_native_run_not_duplicated(self):
        x=rules_packet()
        with tempfile.TemporaryDirectory() as d:
            from reasoning_layer.core import lower
            req={'items':[dict(id=x['task']['id'],operation='rules',program=lower(x['program']),calculation=None)]}
            (Path(d)/'request.json').write_text(json.dumps(req))
            with self.assertRaisesRegex(RuntimeError,'pinned'):MacBackend().run_many([(x['task'],x['program'])],d)
    def test_training_export_needs_native_review_and_signoff(self):
        x=rules_packet();t=x['task'];t['exposure']='development';p=x['program']
        result=dict(review_status='accepted_by_model',answer='True',program_digest=digest(p),execution=dict(native=True))
        approval=dict(reviewer='unit-test-fixture',status='approved',source_fidelity=True,query_preserved=True,label_policy_reviewed=True)
        self.assertEqual(qualify(t,p,result,approval,'True')['training_status'],'exported_candidate_only')
        for field in ['source_fidelity','query_preserved','label_policy_reviewed']:
            bad=dict(approval);bad[field]=False
            with self.assertRaises(ValueError):qualify(t,p,result,bad,'True')
        t['exposure']='sealed_test'
        with self.assertRaises(ValueError):qualify(t,p,result,approval,'True')

if __name__=='__main__':unittest.main()
