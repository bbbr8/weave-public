import copy
import json
from pathlib import Path
import tempfile
import unittest
from weave_demo import create_fixture
from weave_verify import verify,append_memory
from weave_feedback import summarize


class EnhancementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'fixture';self.q,self.c,self.r=create_fixture(self.root)
    def test_preflight_is_not_result_verification(self):
        report=verify(self.q,self.c,root=self.root,plan_only=True)
        self.assertTrue(report['passed']);self.assertEqual(report['status'],'PREFLIGHT_READY')
        self.assertFalse(report['results_verified']);self.assertEqual(report['checks'],[])
        self.assertEqual(report['planned_checks'],10)
    def test_unavailable_preflight_has_targeted_actions(self):
        self.c['operations']['calculate']['available']=False
        report=verify(self.q,self.c,root=self.root,plan_only=True)
        self.assertEqual(report['status'],'PREFLIGHT_BLOCKED')
        self.assertIn('ADAPTER_UNAVAILABLE',{a['code'] for a in report['actions']})
        self.assertNotIn('RECEIPTS_REQUIRED',{a['code'] for a in report['actions']})
    def test_ready_checkbox_does_not_qualify_changed_runtime(self):
        self.c['operations']['calculate']['qualified_runtime_sha256']='0'*64
        report=verify(self.q,self.c,self.r,self.root)
        self.assertFalse(report['passed']);self.assertIn('ADAPTER_RUNTIME_UNQUALIFIED',{i['code'] for i in report['issues']})
    def test_raw_native_status_is_preserved(self):
        self.r[-1].update(native_status='INCONSISTENT_MODEL',completion_state='COMPLETE')
        self.q['checks'][-1]={'kind':'receipt_status','step':'total','value':'INCONSISTENT_MODEL','completion_state':'COMPLETE'}
        report=verify(self.q,self.c,self.r,self.root)
        self.assertTrue(report['passed']);self.assertEqual(report['native_states']['total'],'INCONSISTENT_MODEL')
        self.assertEqual(report['completion_states']['total'],'COMPLETE')
    def test_explicit_partial_policy_is_visible(self):
        self.r[-1].update(native_status='INCOMPLETE',incomplete=True)
        self.q['require_complete']=False
        self.q['checks'][-1].update(value='INCOMPLETE',completion_state='INCOMPLETE')
        report=verify(self.q,self.c,self.r,self.root)
        self.assertTrue(report['passed']);self.assertEqual(report['completion_states']['total'],'INCOMPLETE')
    def test_partial_policy_does_not_override_explicit_native_check(self):
        self.r[-1].update(native_status='INCOMPLETE',incomplete=True);self.q['require_complete']=False
        self.assertFalse(verify(self.q,self.c,self.r,self.root)['passed'])
    def test_completion_mapping_cannot_hide_failed_native_state(self):
        self.q['checks']=self.q['checks'][:-1]
        self.r[-1].update(native_status='FAILED',completion_state='COMPLETE')
        self.assertFalse(verify(self.q,self.c,self.r,self.root)['passed'])
    def test_preflight_checks_declared_source_availability(self):
        self.q['required_sources']['total'].append('unregistered_source')
        report=verify(self.q,self.c,root=self.root,plan_only=True)
        self.assertEqual(report['status'],'PREFLIGHT_BLOCKED');self.assertEqual(report['counts']['ready_steps'],0)
    def test_invalid_source_hash_blocks_preflight(self):
        self.q['sources'][0]['sha256']='0'*64
        report=verify(self.q,self.c,root=self.root,plan_only=True)
        self.assertFalse(report['passed']);self.assertEqual(report['counts']['ready_steps'],0)
    def test_unknown_native_state_needs_completion_mapping(self):
        self.r[-1]['native_status']='MODEL_STATE'
        self.assertFalse(verify(self.q,self.c,self.r,self.root)['passed'])
    def test_all_check_schemas_validate_during_preflight(self):
        self.q['checks'][0]['step']='unknown'
        report=verify(self.q,self.c,root=self.root,plan_only=True)
        self.assertFalse(report['passed']);self.assertIn('INVALID_REQUEST',{i['code'] for i in report['issues']})
    def test_feedback_separates_readiness_and_result_failures(self):
        log=self.root/'feedback.jsonl'
        pre=verify(self.q,self.c,root=self.root,plan_only=True);append_memory(log,pre)
        self.q['checks'][0]['value']+=1
        failed=verify(self.q,self.c,self.r,self.root);append_memory(log,failed);append_memory(log,failed)
        with log.open('a') as f:f.write('bad-json\n')
        summary=summarize(log)
        self.assertEqual(summary['counts']['preflight_passed'],1)
        self.assertEqual(summary['counts']['results_failed'],1)
        self.assertEqual(summary['counts']['duplicate_reports'],1)
        self.assertEqual(summary['counts']['invalid_rows'],1)
        self.assertEqual(summary['training_candidates'][0]['kind'],'equals')
        self.assertFalse(summary['active_training_started'])


if __name__=='__main__':unittest.main()
