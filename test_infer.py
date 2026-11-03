"""Independent sourced-rule closure, strict types and native graph normalization."""
import copy
import unittest
from weave_infer import validate,reference,render,normalize


def fixture():
    return {'version':'weave.tally.rules.v1','atoms':['ready','approved','released'],
        'sources':[{'id':'record','origin_id':'record_origin'},{'id':'policy','origin_id':'policy_origin'}],
        'facts':[],'observations':[{'id':'threshold','atom':'ready','value':2,'minimum':2,'unit':'count','source_id':'record'}],
        'rules':[{'id':'permission','premises':['ready'],'conclusion':'approved','source_id':'policy'},
                 {'id':'release','premises':['ready','approved'],'conclusion':'released','source_id':'policy'}],
        'goal':'released','max_nodes':512}


def pipeline(a=1,b=1):
    p=fixture();p['observations'][0]['value']=0
    return {'version':'weave.pipeline.v1','data_class':'synthetic','plan':{'version':'weave.v1','steps':[
        {'id':'measured','op':'calculate','inputs':[],'args':{'program_ref':'measurement'}},
        {'id':'applied','op':'infer','inputs':['measured'],'args':{'program_ref':'rules'}},
        {'id':'counted','op':'calculate','inputs':['applied'],'args':{'program_ref':'count'}}]},
        'programs':{'measurement':{'version':'weave.tally.integer.v1','operation':'sum','terms':[a,b],'unit':'count'},
                    'rules':p,'count':{'version':'weave.tally.integer.v1','operation':'sum','terms':[0,7],'unit':'count'}},
        'bindings':[{'step':'applied','target':'/observations/0/value','source_step':'measured','pointer':'/value','unit':'count'},
                    {'step':'counted','target':'/terms/0','source_step':'applied','pointer':'/support_origin_count','unit':'count'}],
        'checks':[{'kind':'equals','step':'counted','pointer':'/value','value':9 if a+b>=2 else 7}],'node_options':{}}


class InferTests(unittest.TestCase):
    def test_pipeline_observation_units_and_target_availability(self):
        from weave_run import validate as validate_pipeline
        self.assertEqual(len(validate_pipeline(pipeline())),3)
        for kind in ['unit','target']:
            p=pipeline()
            if kind=='unit':p['programs']['rules']['observations'][0]['unit']='cents'
            else:p['bindings'][0]['target']='/observations/99/value'
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_pipeline(p)

    def test_exact_threshold_and_joint_closure(self):
        p=fixture();self.assertEqual(reference(p),{'status':'true','support_source_ids':['policy','record']})
        p['observations'][0]['value']=1
        self.assertEqual(reference(p),{'status':'unknown','support_source_ids':[]})
        self.assertIn('v >= (2)',render(p))

    def test_alternative_sources_union_without_extra_origins(self):
        p=fixture();p['sources'].append({'id':'copy','origin_id':'record_origin'});p['observations']=[]
        p['facts']=[{'atom':'ready','source_id':'record'},{'atom':'ready','source_id':'copy'}]
        self.assertEqual(reference(p)['support_source_ids'],['copy','policy','record'])
        self.assertEqual(len({s['origin_id'] for s in p['sources']}),2)

    def test_asserted_atom_takes_provenance_precedence(self):
        p=fixture();p['sources'].append({'id':'copy','origin_id':'record_origin'});p['facts'].append({'atom':'ready','source_id':'copy'})
        self.assertEqual(reference(p)['support_source_ids'],['copy','policy'])

    def test_reject_code_cycles_unknown_sources_and_inexact_values(self):
        for kind in ['code','cycle','source','float','bool','duplicate','extra']:
            p=fixture()
            if kind=='code':p['atoms'][0]='ready;print(1)'
            if kind=='cycle':p['rules'][0]['premises']=['released']
            if kind=='source':p['rules'][0]['source_id']='missing'
            if kind=='float':p['observations'][0]['value']=1.5
            if kind=='bool':p['observations'][0]['value']=True
            if kind=='duplicate':p['sources'].append(copy.deepcopy(p['sources'][0]))
            if kind=='extra':p['code']='print(1)'
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate(p)

    def test_truncation_preserves_status_and_unknown_counts(self):
        p=fixture();graph={'schema':'tally.proof_graph.v1','root':'P_released("item")','status':'true','nodes':[],
            'edges':[],'max_nodes':512,'truncated':True}
        result=normalize(p,graph)
        self.assertFalse(result['complete']);self.assertIsNone(result['supported_goals']);self.assertEqual(result['status'],'true')


if __name__=='__main__':unittest.main()
