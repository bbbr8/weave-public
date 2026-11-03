"""Pipeline binding, exact unit and immutable request regressions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from weave_run import validate,resolve,unit_for,set_integer
from weave_verify import file_digest


def fixture(a=1,b=2):
    return {'version':'weave.pipeline.v1','data_class':'synthetic',
        'plan':{'version':'weave.v1','steps':[
            {'id':'total','op':'calculate','inputs':[],'args':{'program_ref':'total_program'}},
            {'id':'worlds','op':'solve','inputs':['total'],'args':{'program_ref':'finite_program'}}]},
        'programs':{'total_program':{'version':'weave.tally.integer.v1','operation':'sum','terms':[a,b],'unit':'integer'},
            'finite_program':{'version':'weave.qulap.integer.v1','variables':[{'id':'x','domain':[-2,-1,0,1,2,3,4]}],
                'constraints':[{'id':'cap','coefficients':{'x':1},'relation':'<=','bound':0}],
                'metrics':[{'id':'value','coefficients':{'x':1},'constant':0}]}},
        'bindings':[{'step':'worlds','target':'/constraints/0/bound','source_step':'total','pointer':'/value','unit':'integer'}],
        'checks':[{'kind':'equals','step':'total','pointer':'/value','value':a+b},
                  {'kind':'equals','step':'worlds','pointer':'/global_feasible_states','value':sum(x<=a+b for x in [-2,-1,0,1,2,3,4])}],
        'node_options':{}}


class RunTests(unittest.TestCase):
    def test_bound_program_depends_on_checked_parent(self):
        p=fixture();step=validate(p)[1]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'result.json';path.write_text('{"value":3}')
            parents={'total':{'path':path,'sha256':file_digest(path),'result':{'value':3}}}
            program,ledger=resolve(p,step,parents,p['programs'])
            self.assertEqual(program['constraints'][0]['bound'],3)
            self.assertEqual(ledger[0]['source_result_sha256'],file_digest(path))
            self.assertEqual(p['programs']['finite_program']['constraints'][0]['bound'],0)
            path.write_text('{"value":4}')
            with self.assertRaises(ValueError):resolve(p,step,parents,p['programs'])

    def test_reject_untyped_or_noncausal_bindings(self):
        for kind in ['unit','unknown','self','overlap','unused','shared_ref','unsupported','classification']:
            p=fixture()
            if kind=='unit':p['programs']['total_program']['unit']='cents'
            if kind=='unknown':p['bindings'][0]['pointer']='/invented'
            if kind=='self':p['bindings'][0]['source_step']='worlds'
            if kind=='overlap':p['bindings'].append(copy.deepcopy(p['bindings'][0]))
            if kind=='unused':p['bindings']=[]
            if kind=='shared_ref':p['plan']['steps'][1]['args']['program_ref']='total_program'
            if kind=='unsupported':p['plan']['steps'][1]['op']='infer'
            if kind=='classification':p['data_class']='case_private'
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate(p)

    def test_integer_bindings_preserve_unknown_and_boolean_distinctions(self):
        for value in [None,True,1.5,'3']:
            p={'terms':[0]}
            with self.assertRaises(ValueError):set_integer(p,'/terms/0',value)
        p={'terms':[0]};set_integer(p,'/terms/0',-4);self.assertEqual(p['terms'],[-4])

    def test_count_and_integer_units_are_distinct(self):
        p=fixture()['programs']['finite_program']
        self.assertEqual(unit_for('solve',p,'/global_feasible_states'),'count')
        self.assertEqual(unit_for('solve',p,'/constraints/0/bound',True),'integer')


if __name__=='__main__':unittest.main()
