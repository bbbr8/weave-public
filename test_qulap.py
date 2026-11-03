"""QULAP adapter contract and independent-oracle regression tests."""
import copy
import unittest
from weave_qulap import validate, native_model, reference, validate_native
from weave_verify import digest_json


def fixture():
    return {'version':'weave.qulap.integer.v1','variables':[{'id':'x','domain':[1,2,3]},
            {'id':'y','domain':[0,1]}],
            'constraints':[{'id':'bound','coefficients':{'x':1,'y':1},'relation':'<=','bound':3}],
            'metrics':[{'id':'total','coefficients':{'x':1,'y':1},'constant':0}]}


def response(program):
    oracle=reference(program);model=native_model(program,'0'*64)
    return model,oracle,{'schema':'qulap.result.v1','backend':'reference','search_mode':'enumerate',
        'model_sha256':digest_json(model),'sources':model['sources'],'candidate_states':oracle['candidate_states'],
        'complete':True,'state':'COMPLETE' if oracle['feasible_states'] else 'INCONSISTENT_MODEL',
        'feasible_states':oracle['feasible_states'],'worlds':oracle['worlds'],'worlds_truncated':False,
        'metrics':oracle['metrics'],'cutoff':None}


class QulapTests(unittest.TestCase):
    def test_oracle_and_compiler(self):
        p=fixture();o=reference(p)
        self.assertEqual(o['feasible_states'],5)
        self.assertEqual(o['metrics']['total'],{'min':1,'max':3,'unit':'integer'})
        m=native_model(p,'a'*64)
        self.assertEqual(m['sources'][0]['lineage_id'],'finite-input')
        self.assertIn('a'*64,m['sources'][0]['locator'])

    def test_signed_metrics_and_empty_coefficients(self):
        p=fixture();p['metrics'][0].update(coefficients={'x':-2,'y':1},constant=-3)
        self.assertEqual(reference(p)['metrics']['total'],{'min':-9,'max':-4,'unit':'integer'})
        p['metrics'][0].update(coefficients={},constant=7)
        self.assertEqual(reference(p)['metrics']['total']['min'],7)

    def test_reject_malformed_inputs_and_domain_explosion(self):
        for kind in ['bool','float','duplicate','code','unknown','large','explosion','relation','extra']:
            p=fixture()
            if kind=='bool':p['variables'][0]['domain']=[True]
            if kind=='float':p['variables'][0]['domain']=[1.0]
            if kind=='duplicate':p['variables'][0]['domain']=[1,1]
            if kind=='code':p['variables'][0]['id']='x;import os'
            if kind=='unknown':p['metrics'][0]['coefficients']={'z':1}
            if kind=='large':p['variables'][0]['domain']=[10**7]
            if kind=='explosion':p['variables']=[{'id':'x'+str(i),'domain':list(range(8))} for i in range(6)]
            if kind=='relation':p['constraints'][0]['relation']='eval'
            if kind=='extra':p['shell']='anything'
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate(p)

    def test_complete_and_inconsistent_contracts(self):
        for bound,count in [(3,5),(-1,0)]:
            p=fixture();p['constraints'][0]['bound']=bound
            m,o,n=response(p);r=validate_native(n,0,m,o)
            self.assertEqual(r['global_feasible_states'],count)
            self.assertTrue(r['complete'])

    def test_reject_wrong_bounds_sources_domain_worlds_and_identity(self):
        for kind in ['bounds','source','domain','world','duplicate','identity','status','exit','truncated']:
            m,o,n=response(fixture());n=copy.deepcopy(n)
            if kind=='bounds':n['metrics']['total']['max']=4
            if kind=='source':n['sources']=[]
            if kind=='domain':n['candidate_states']=7
            if kind=='world':n['worlds'][0]['x']=99
            if kind=='duplicate':n['worlds'][-1]=n['worlds'][0]
            if kind=='identity':n['model_sha256']='f'*64
            if kind=='status':n['state']='INCOMPLETE'
            if kind=='truncated':n['worlds_truncated']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_native(n,3 if kind=='exit' else 0,m,o)

    def test_incomplete_keeps_global_unknowns_and_cutoff(self):
        m,o,n=response(fixture());n.update(complete=False,state='INCOMPLETE',cutoff='node_limit',feasible_states=0,worlds=[])
        n['metrics']={'total':{'min':None,'max':None,'unit':'integer'}}
        r=validate_native(n,3,m,o)
        self.assertIsNone(r['global_feasible_states']);self.assertFalse(r['complete'])
        n['metrics']['total']['max']=3
        with self.assertRaises(ValueError):validate_native(n,3,m,o)


if __name__=='__main__':unittest.main()
