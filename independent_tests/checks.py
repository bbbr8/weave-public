"""Independent synthetic checks. Run against an explicitly selected source tree.

These checks do not use hosted models, private data, or external runtimes.
Failures are retained as failures; no expected-failure masking is used.
"""
import copy
from decimal import Decimal
from fractions import Fraction
import itertools
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest

TARGET = Path(sys.argv.pop(1)).resolve()
PROJECT = sys.argv.pop(1)
sys.path.insert(0, str(TARGET))
sys.path.insert(0, str(TARGET / 'runtime'))


class WeaveChecks(unittest.TestCase):
    def test_decimal_literal_original(self):
        from reasoning_layer.core import calculate
        result = calculate({'operands': [], 'formula': '0.10000000000000001 - 0.1'})
        self.assertEqual(result, Decimal('0.00000000000000001'))

    def test_decimal_literal_distinct_transfer(self):
        from reasoning_layer.core import calculate
        result = calculate({'operands': [], 'formula': '1.0000000000000001 - 1'})
        self.assertEqual(result, Decimal('0.0000000000000001'))

    def test_decimal_string_operand_control(self):
        from reasoning_layer.core import calculate
        result = calculate({'operands': [{'name': 'a', 'value': '0.10000000000000001'},
                                         {'name': 'b', 'value': '0.1'}], 'formula': 'a-b'})
        self.assertEqual(result, Decimal('0.00000000000000001'))

    def test_wide_conjunction_against_truth_table(self):
        from reasoning_layer.core import closure, lower
        names = ['p' + str(i) for i in range(1, 11)]
        for bits in itertools.product([False, True], repeat=10):
            p = {'nodes': [{'id': n, 'text': n} for n in names + ['p9999']],
                 'facts': [n for n, b in zip(names, bits) if b],
                 'rules': [{'if': names, 'then': 'p9999', 'basis': 'synthetic all-input requirement'}]}
            before = copy.deepcopy(p)
            self.assertEqual('p9999' in closure(lower(p))[0], all(bits))
            self.assertEqual(p, before)


class BootlangChecks(unittest.TestCase):
    def rows(self):
        return [dict(speaker='s', period=p, text=t) for p, t in
                [('a', 'credit applied credit'), ('a', 'owner paid'),
                 ('b', 'credit refunded'), ('b', 'owner paid balance')]]

    def test_period_swap_and_row_order(self):
        from bootlang import terms, permutation_test
        rows = self.rows()
        first = terms(rows, 's', 'a', 'b')
        other = terms(list(reversed(rows)), 's', 'b', 'a')
        self.assertAlmostEqual(first['js_divergence_bits'], other['js_divergence_bits'])
        self.assertEqual(permutation_test(rows, 's', 'a', 'b')['p_value'],
                         permutation_test(rows, 's', 'b', 'a')['p_value'])

    def test_unselected_speaker_does_not_change_result(self):
        from bootlang import terms
        rows = self.rows()
        self.assertEqual(terms(rows, 's', 'a', 'b'),
                         terms(rows + [dict(speaker='other', period='a', text='irrelevant ' * 1000)], 's', 'a', 'b'))

    def test_frequency_scaling_preserves_divergence(self):
        from bootlang import terms
        rows = self.rows()
        self.assertAlmostEqual(terms(rows, 's', 'a', 'b')['js_divergence_bits'],
                               terms(rows * 7, 's', 'a', 'b')['js_divergence_bits'])


class LoomChecks(unittest.TestCase):
    def packet(self, limit):
        return dict(schema='qulap.model.v1', source_tier='synthetic',
                    variables=[dict(id=n, domain=list(range(6)), unit='integer') for n in ['x', 'y']],
                    constraints=[dict(id='capacity', expr='x+y <= ' + str(limit))],
                    metrics=[dict(id='difference', expr='x-y', unit='integer')],
                    propositions=[dict(id='positive', expr='x>y')])

    def test_finite_models_against_cartesian_oracle(self):
        from loom_qulap.model import solve
        for limit in range(-1, 12):
            expected = [(x, y) for x, y in itertools.product(range(6), repeat=2) if x+y <= limit]
            r = solve(self.packet(limit))
            self.assertTrue(r['complete'])
            self.assertEqual(r['feasible_states'], len(expected))
            if expected:
                self.assertEqual(r['metrics']['difference']['min'], min(x-y for x, y in expected))
                self.assertEqual(r['metrics']['difference']['max'], max(x-y for x, y in expected))
            else:
                self.assertEqual(r['state'], 'INCONSISTENT_MODEL')

    def test_cutoff_cannot_certify_global_bounds(self):
        from loom_qulap.model import solve
        r = solve(self.packet(6), max_nodes=1)
        self.assertFalse(r['complete'])
        self.assertEqual(r['metric_scope'], 'observed bounds only')
        self.assertEqual(r['propositions']['positive']['status'], 'UNRESOLVED_INCOMPLETE')

    def test_money_roundtrip_without_float_oracle(self):
        from loom_research.normalization import normalize
        rng = random.Random(6041)
        for cents in [0, 1, -1, 9007199254740993, -9007199254740993] + [rng.randrange(-10**15, 10**15) for _ in range(200)]:
            raw = 'USD ' + ('-' if cents < 0 else '') + str(abs(cents)//100) + '.' + str(abs(cents)%100).zfill(2)
            r = normalize('money', raw)
            self.assertEqual(r['minor_units'], cents)
            self.assertEqual(r['raw'], raw)


class TallyChecks(unittest.TestCase):
    def test_large_money_cancellation_over_json_protocol(self):
        rng = random.Random(771)
        rows = []
        expected = []
        for i in range(100):
            cents = rng.randrange(10**15, 10**17)
            amount = str(cents//100) + '.' + str(cents%100).zfill(2)
            rows.append(json.dumps(dict(id=i, op='eval', code='($' + amount + ' + $0.01) - $' + amount)))
            expected.append('$0.01')
        p = subprocess.run([sys.executable, '-B', 'tally.py', 'serve'], cwd=TARGET,
                           input='\n'.join(rows)+'\n', text=True, capture_output=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        messages = [json.loads(line) for line in p.stdout.splitlines()]
        self.assertEqual(messages[0]['op'], 'hello')
        result = messages[1:]
        self.assertEqual(len(result), 100)
        for i, (r, value) in enumerate(zip(result, expected)):
            self.assertEqual(r['id'], i)
            self.assertTrue(r['ok'], r)
            self.assertEqual(r['value'], value)


class TellChecks(unittest.TestCase):
    def test_exact_literals_and_cancellation(self):
        import tell
        rng = random.Random(432)
        for _ in range(200):
            n = rng.randrange(10**15, 10**19)
            literal = str(n) + '.00000000000000001'
            self.assertEqual(tell.parse_term(literal), Fraction(n) + Fraction(1, 10**17))
            result = tell.eval_expr(tell.expression_text('(' + literal + ' - ' + str(n) + ') * 100000000000000000'), {})
            self.assertEqual(result, Fraction(1))


class VeinChecks(unittest.TestCase):
    def test_byte_orders_offsets_and_truncation(self):
        import vein
        rng = random.Random(876)
        for order, byteorder in [('be', 'big'), ('le', 'little')]:
            schema = vein.compile('endian ' + order + '\nroot packet\ntype packet {\n first: u16\n second: u32\n}\n')
            for _ in range(100):
                a, b = rng.randrange(2**16), rng.randrange(2**32)
                raw = a.to_bytes(2, byteorder) + b.to_bytes(4, byteorder)
                fields = json.loads(vein.to_json(schema.parse(raw)))['fields']
                self.assertEqual((fields['first']['value'], fields['second']['value']), (a, b))
                self.assertEqual((fields['second']['offset'], fields['second']['size']), (2, 4))
            for length in range(6):
                with self.assertRaises(vein.ParseError):
                    schema.parse(bytes(length))


if __name__ == '__main__':
    classes = {'weave-public': WeaveChecks, 'loom-public': LoomChecks, 'tally-public': TallyChecks,
               'tell': TellChecks, 'bootlang': BootlangChecks, 'vein': VeinChecks}
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(classes[PROJECT])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
