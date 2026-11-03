"""Independent source-retention and input contract tests for Loom adapter."""
import copy
import unittest
from weave_loom import validate,validate_native,expected_document


def fixture():
    return {'version':'weave.loom.corpus.v1','documents':[
        {'id':'d01','title':'Valve check','text':'Valve pressure inspection passed.','origin_id':'a'},
        {'id':'d02','title':'Valve check copy','text':'Valve pressure inspection passed.','origin_id':'a'}],
        'query':'pressure inspection','top_k':5,'ranker':'hybrid'}


def response():
    p=fixture();docs=[expected_document(d) for d in p['documents']]
    hits=[{'id':d['id'],'rank':i,'content_hash':d['content_hash'],'metadata':d['metadata'],
           'locator':d['locator'],'title':d['title'],'snippet':{'start':0,'end':len(d['text']),'text':d['text']}} for i,d in enumerate(docs,1)]
    return p,{'schema':'surd.search.results.v1','query':p['query'],'mode':'hybrid','k':5,'status':'ok','hits':hits,'matched_documents':2},docs


class LoomTests(unittest.TestCase):
    def test_valid_source_snapshots_and_duplicate_origin(self):
        p,n,d=response();self.assertEqual(validate_native(p,n,d),['d01','d02'])
        self.assertEqual(len({x['metadata']['origin_id'] for x in d}),1)

    def test_unicode_source_hashing(self):
        p,n,d=response();p['documents'][0]['text']='Válvula Δ'
        fresh=expected_document(p['documents'][0]);d[0]=fresh
        n['hits'][0].update(content_hash=fresh['content_hash'],snippet={'start':0,'end':len(fresh['text']),'text':fresh['text']})
        self.assertEqual(validate_native(p,n,d),['d01','d02'])

    def test_reject_bad_input_shapes(self):
        for kind in ['duplicate','path','bool','ranker','text','empty','extra']:
            p=fixture()
            if kind=='duplicate':p['documents'][1]['id']='d01'
            if kind=='path':p['documents'][0]['id']='../outside'
            if kind=='bool':p['top_k']=True
            if kind=='ranker':p['ranker']='semantic'
            if kind=='text':p['documents'][0]['text']='x'*4097
            if kind=='empty':p['documents']=[]
            if kind=='extra':p['source_path']='/private'
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate(p)

    def test_changed_content_origin_snippet_and_rank_are_rejected(self):
        for kind in ['content','origin','snippet','rank','duplicate','status','query','coverage']:
            p,n,d=response()
            if kind=='content':d[0]['text']='changed'
            if kind=='origin':n['hits'][0]['metadata']['origin_id']='invented'
            if kind=='snippet':n['hits'][0]['snippet']['text']='invented'
            if kind=='rank':n['hits'][0]['rank']=2
            if kind=='duplicate':n['hits'][1]=copy.deepcopy(n['hits'][0])
            if kind=='status':n['status']='no_match'
            if kind=='query':n['query']='different'
            if kind=='coverage':n['matched_documents']=0
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_native(p,n,d)

    def test_valid_empty_matches(self):
        p,n,d=response();n.update(hits=[],matched_documents=0,status='no_match')
        self.assertEqual(validate_native(p,n,[]),[])


if __name__=='__main__':unittest.main()
