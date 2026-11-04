import copy
import json
from pathlib import Path
import tempfile
import unittest

from reasoning_layer.contracts import make_task
from reasoning_layer.examples import rules_packet, arithmetic_packet
from reasoning_layer.native import ReferenceBackend
from reasoning_layer.pipeline import ReasoningLayer, execute_packets
from reasoning_layer.source_audit import FACETS, audit_source, source_units, reasoning_trace


def tracked_packet():
    x = rules_packet()
    units = source_units(x['task'])
    x['program']['source_ledger'] = [
        dict(unit_id=units[0]['id'], disposition='represented', reason='The recorded fact supplies p1.', targets=['node:p1']),
        dict(unit_id=units[1]['id'], disposition='represented', reason='This source rule supplies the implication.', targets=['rule:0']),
    ]
    return x


def review_for(task):
    return dict(unit_reviews=[dict(unit_id=u['id'], agrees=True, reason='Fixture review explicitly checks this unit.') for u in source_units(task)],
                query_checks=[dict(facet=f, preserved=True, reason='Fixture checks ' + f) for f in FACETS])


class Model:
    def __init__(self, initial, final, review):
        self.initial, self.final, self.review = initial, final, review
        self.calls = []

    def respond(self, prompt, schema, folder):
        self.calls.append(prompt)
        if len(self.calls) == 1:
            return {'programs': [self.initial]}
        return {'reviews': [dict(id=self.final['task_id'], accepted=True, issues=[], program=self.final, source_review=self.review)]}


class SourceAudit(unittest.TestCase):
    def setUp(self):
        self.x = tracked_packet()
        self.t, self.p = self.x['task'], self.x['program']

    def codes(self, review=None):
        return {d['code'] for d in audit_source(self.t, self.p, review)['diagnostics']}

    def test_every_nonspace_character_is_accounted_once(self):
        context = ' § 1. Alpha: 12.34; unless β.\n\nDate 2030-01-02. ' + ('長' * 2301) + ' trailing  '
        t = make_task('unicode', context, 'What follows?', ['True', 'False', 'Unknown'], data_class='synthetic')
        units = source_units(t)
        covered = [i for u in units for i in range(u['start'], u['end']) if not context[i].isspace()]
        self.assertEqual(covered, [i for i, c in enumerate(context) if not c.isspace()])
        self.assertTrue(all(context[u['start']:u['end']] == u['text'] and len(u['text']) <= 1000 for u in units))

    def test_units_are_stable_and_source_bound(self):
        self.assertEqual(source_units(self.t), source_units(self.t))
        t = make_task('new', 'Prefix.\n' + self.t['context'], self.t['question'], self.t['labels'], data_class='synthetic')
        self.assertTrue(set(u['id'] for u in source_units(t)).isdisjoint(u['id'] for u in source_units(self.t)))

    def test_valid_ledger_is_not_semantic_certification(self):
        a = audit_source(self.t, self.p)
        self.assertTrue(a['valid'])
        self.assertFalse(a['semantic_review_recorded'])
        self.assertIn('not semantic certification', a['interpretation'])

    def test_legacy_packet_is_explicitly_untracked(self):
        del self.p['source_ledger']
        self.assertEqual(audit_source(self.t, self.p)['status'], 'legacy_untracked')

    def test_omitted_decisive_unit_is_detected(self):
        self.p['source_ledger'].pop()
        self.assertIn('source_units_unaccounted', self.codes())
        self.assertIn('rule_unlinked_to_source_ledger', self.codes())

    def test_duplicate_unit_cannot_inflate_coverage(self):
        self.p['source_ledger'].append(copy.deepcopy(self.p['source_ledger'][0]))
        self.assertIn('source_unit_identity', self.codes())

    def test_wrong_unit_quote_link_is_detected(self):
        self.p['source_ledger'][1]['targets'].append('node:p1')
        self.assertIn('source_target_span_mismatch', self.codes())

    def test_nonexistent_target_is_detected(self):
        self.p['source_ledger'][0]['targets'] = ['node:p99']
        self.assertIn('source_target_unknown_or_duplicate', self.codes())

    def test_represented_requires_reference(self):
        self.p['source_ledger'][0]['targets'] = []
        self.assertIn('represented_without_target', self.codes())

    def test_unresolved_carries_a_specific_state(self):
        self.p['source_ledger'][0].update(disposition='unresolved', targets=[])
        self.assertIn('source_interpretation_unresolved', self.codes())

    def test_irrelevant_condition_is_exposed_for_review(self):
        self.p['source_ledger'][1].update(disposition='irrelevant', targets=[], reason='Model says unrelated.')
        self.assertEqual(audit_source(self.t, self.p)['warnings'][0]['code'], 'risk_cue_marked_irrelevant')

    def test_semantic_misreading_remains_model_judgment(self):
        self.p['nodes'][0]['text'] = 'File K is a defendant.'
        self.assertTrue(audit_source(self.t, self.p)['valid'])
        # Matching source links cannot automatically establish the meaning of prose.

    def test_external_rules_are_visible(self):
        self.p['source_ledger'][1].update(disposition='irrelevant', targets=[], reason='Fixture testing an external rule.')
        self.p['rules'][0]['basis'] = 'External: declared general rule.'
        self.assertTrue(audit_source(self.t, self.p)['valid'])
        self.assertIn('external_rule', {w['code'] for w in audit_source(self.t, self.p)['warnings']})

    def test_review_must_cover_every_unit(self):
        r = review_for(self.t)
        r['unit_reviews'].pop()
        self.assertIn('unit_reviews_incomplete', self.codes(r))

    def test_duplicate_query_facet_cannot_replace_another(self):
        r = review_for(self.t)
        r['query_checks'][-1] = r['query_checks'][0]
        self.assertIn('query_checks_incomplete', self.codes(r))

    def test_reviewer_rejection_is_preserved(self):
        r = review_for(self.t)
        r['unit_reviews'][0]['agrees'] = False
        self.assertIn('unit_review_unresolved', self.codes(r))

    def test_query_scope_defect_is_preserved(self):
        r = review_for(self.t)
        r['query_checks'][-1]['preserved'] = False
        self.assertIn('query_facet_unresolved', self.codes(r))

    def test_review_shape_errors_do_not_crash(self):
        self.assertIn('source_review_shape', self.codes([]))
        r = review_for(self.t)
        r['unit_reviews'] = 'all reviewed'
        self.assertIn('unit_reviews_incomplete', self.codes(r))

    def test_trace_has_actual_reached_and_underived_goals(self):
        trace = reasoning_trace(self.t, self.p)
        self.assertEqual([g['reached'] for g in trace['goals']], [True, False])
        step = next(s for s in trace['steps'] if s['node'] == 'p2')
        self.assertEqual(step['premises'], ['p1'])
        self.assertEqual(step['source_units'], [source_units(self.t)[1]['id']])

    def test_cycles_terminate_without_inventing_support(self):
        self.p['facts'] = []
        self.p['rules'].append({'if': ['p2'], 'then': 'p1', 'basis': 'Cycle fixture'})
        trace = reasoning_trace(self.t, self.p)
        self.assertEqual(trace['known'], [])

    def test_arithmetic_tracks_used_and_unused_operands(self):
        x = arithmetic_packet()
        p, t = x['program'], x['task']
        p['source_ledger'] = []
        for u, o in zip(source_units(t), p['calculation']['operands']):
            p['source_ledger'].append(dict(unit_id=u['id'], disposition='represented', reason='Operand and calculation source.', targets=['operand:' + o['name'], 'calculation:formula']))
        self.assertTrue(audit_source(t, p)['valid'])
        p['calculation']['formula'] = 'fee_a - credit'
        trace = reasoning_trace(t, p)
        self.assertEqual(trace['used_operands'], ['credit', 'fee_a'])
        self.assertFalse(next(o for o in trace['operands'] if o['name'] == 'fee_b')['used'])

    def test_upgraded_pipeline_repairs_omitted_unit_in_two_passes(self):
        bad = copy.deepcopy(self.p)
        bad['source_ledger'].pop()
        m = Model(bad, self.p, review_for(self.t))
        with tempfile.TemporaryDirectory() as d:
            r = ReasoningLayer(m, ReferenceBackend()).run([self.t], d)[self.t['id']]
            self.assertEqual(r['answer'], 'True')
            self.assertTrue(r['source_audit']['semantic_review_recorded'])
            self.assertIn('source_units_unaccounted', m.calls[1])
            self.assertTrue((Path(d) / 'source-units.json').exists())
            initial = json.loads((Path(d) / 'initial-programs.json').read_text())
            self.assertEqual(len(initial[self.t['id']]['source_ledger']), 1)
        self.assertEqual(len(m.calls), 2)

    def test_acceptance_cannot_bypass_missing_source_ledger(self):
        del self.p['source_ledger']
        m = Model(self.p, self.p, review_for(self.t))
        with tempfile.TemporaryDirectory() as d:
            r = ReasoningLayer(m, ReferenceBackend()).run([self.t], d)[self.t['id']]
            self.assertEqual(r['answer'], 'ABSTAIN')
            self.assertEqual(r['execution']['answer'], 'True')
            self.assertEqual(r['review_status'], 'source_review_required')

    def test_unknown_policy_cannot_bypass_missing_review(self):
        self.p['facts'] = []
        with tempfile.TemporaryDirectory() as d:
            r = execute_packets([(self.t, self.p)], ReferenceBackend(), d, accepted={self.t['id']: False}, uncertainty_only={self.t['id']: True}, require_source_ledger=True)[self.t['id']]
            self.assertEqual(r['answer'], 'ABSTAIN')
            self.assertEqual(r['execution']['answer'], 'Unknown')

    def test_replay_rejects_changed_source_units_file(self):
        m = Model(self.p, self.p, review_for(self.t))
        with tempfile.TemporaryDirectory() as d:
            layer = ReasoningLayer(m, ReferenceBackend())
            layer.run([self.t], d)
            (Path(d) / 'source-units.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError, 'artifact changed'):
                layer.run([self.t], d)
        self.assertEqual(len(m.calls), 2)


if __name__ == '__main__':
    unittest.main()
