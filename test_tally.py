"""Bounded input and native-contract regression tests; Mac fixtures run separately."""
import unittest
from unittest.mock import patch
from pathlib import Path
import subprocess
from weave_tally import expression, invoke


class TallyTests(unittest.TestCase):
    def program(self,op,terms):
        return {'version':'weave.tally.integer.v1','operation':op,'terms':terms,'unit':'cents'}

    def test_exact_integer_contract(self):
        for op,terms,want in [('sum',[12000,10200],22200),('difference',[-4,3],-7),('product',[3,4],12)]:
            self.assertEqual(expression(self.program(op,terms))[1],want)

    def test_reject_code_float_bool_and_unbounded_terms(self):
        for terms in [[True,2],[1.2,2],['read("secret")',2],[10**13,1],[1]*17]:
            with self.assertRaises(ValueError):expression(self.program('sum',terms))

    def test_reject_ambiguous_difference(self):
        with self.assertRaises(ValueError):expression(self.program('difference',[1,2,3]))

    def test_native_response_validation(self):
        for raw in ['{"schema":"tally.eval.v1","ok":false}',
                    '{"schema":"tally.eval.v1","ok":true,"expr":"0","value":1.5}']:
            with patch('weave_tally.subprocess.run',return_value=subprocess.CompletedProcess([],0,raw,'')):
                with self.assertRaises(ValueError):invoke(Path('/runtime'),'0')


if __name__=='__main__':unittest.main()
