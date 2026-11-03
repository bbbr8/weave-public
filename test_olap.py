"""Exact grouping and typed OLAP adapter input regressions."""
import copy
import unittest
from weave_olap import validate,reference,matches


def fixture():
    return {'version':'weave.olap.integer.v1','records':[
        {'entry_id':'e1','bucket':'alpha','amount_units':120,'source_id':'s1','origin_id':'o1'},
        {'entry_id':'e2','bucket':'alpha','amount_units':-20,'source_id':'s2','origin_id':'o2'},
        {'entry_id':'e3','bucket':'beta','amount_units':None,'source_id':'s3','origin_id':'o3'}],
        'dimensions':['bucket'],'filters':[],'max_rows':100,'unit':'units'}


class OlapTests(unittest.TestCase):
    def test_signed_groups_and_unknown_sum(self):
        rows=reference(fixture())
        self.assertEqual(rows[0],{'bucket':'alpha','row_count':2,'amount_sum':100,'amount_min':-20,'amount_max':120})
        self.assertIsNone(rows[1]['amount_sum'])

    def test_zero_and_null_are_distinct(self):
        p=fixture();p['records'][2]['amount_units']=0
        self.assertEqual(reference(p)[1]['amount_sum'],0)

    def test_sql_null_filter_semantics(self):
        r=fixture()['records'][2]
        for op in ['eq','ne','gte','lte','in']:
            f={'column':'amount_units','op':op,'value':[0] if op=='in' else 0}
            self.assertFalse(matches(r,[f]))
        self.assertTrue(matches(r,[{'column':'amount_units','op':'is_null','value':None}]))

    def test_empty_grouping_and_empty_scalar_aggregate(self):
        p=fixture();p['filters']=[{'column':'bucket','op':'eq','value':'missing'}]
        self.assertEqual(reference(p),[])
        p['dimensions']=[]
        self.assertEqual(reference(p),[{'row_count':0,'amount_sum':None,'amount_min':None,'amount_max':None}])

    def test_reject_invalid_inputs(self):
        for kind in ['bool','float','huge','duplicate','origin','rawsql','column','none','limit']:
            p=fixture()
            if kind=='bool':p['records'][0]['amount_units']=True
            if kind=='float':p['records'][0]['amount_units']=1.5
            if kind=='huge':p['records'][0]['amount_units']=10**10
            if kind=='duplicate':p['records'][1]['entry_id']='e1'
            if kind=='origin':p['records'][1]['source_id']='s1'
            if kind=='rawsql':p['sql']='DELETE FROM entries'
            if kind=='column':p['dimensions']=['bucket;DROP TABLE entries']
            if kind=='none':p['filters']=[{'column':'amount_units','op':'eq','value':None}]
            if kind=='limit':p['max_rows']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate(p)


if __name__=='__main__':unittest.main()
