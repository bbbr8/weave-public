import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from weave_demo import create_fixture
from weave_verify import verify,append_memory,file_digest,exact_number,pointer


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'fixture'
        self.request,self.catalog,self.receipts=create_fixture(self.root)

    def check(self,request=None,catalog=None,receipts=None):
        return verify(self.request if request is None else request,self.catalog if catalog is None else catalog,self.receipts if receipts is None else receipts,self.root)

    def test_valid_receipts_and_exact_checks(self):
        r=self.check();self.assertTrue(r['passed']);self.assertEqual(r['valid_receipts'],2)
        self.assertFalse(r['engine_execution_proven'])

    def test_coherent_wrong_result_is_caught(self):
        p=self.root/'total-result.json';v=json.loads(p.read_text());v['total_cents']+=1;p.write_text(json.dumps(v))
        self.receipts[-1]['result_sha256']=file_digest(p)
        self.assertFalse(self.check()['passed'])

    def test_catalog_binding_mutations(self):
        for change in ('unavailable','stale','engine','program','runtime','mode'):
            with self.subTest(change=change):
                c=copy.deepcopy(self.catalog)
                if change=='unavailable':c['operations']['calculate']['available']=False
                if change=='stale':c['observed_at']=time.time()-3601
                if change=='engine':c['operations']['calculate']['engine']='wrong'
                if change=='program':c['operations']['calculate']['programs']={}
                if change=='runtime':c['operations']['calculate']['runtime_sha256']='0'*64
                if change=='mode':c['registry']={'mode':'live','freshness':'SOURCE_CHANGED'}
                self.assertFalse(self.check(catalog=c)['passed'])

    def test_receipt_binding_mutations(self):
        for change in ('duplicate','missing','inputs','args','source','origin','incomplete','failed','not_executed','program'):
            with self.subTest(change=change):
                r=copy.deepcopy(self.receipts)
                if change=='duplicate':r.append(copy.deepcopy(r[-1]))
                if change=='missing':r=r[1:]
                if change=='inputs':r[-1]['input_hashes']={}
                if change=='args':r[-1]['args_sha256']='0'*64
                if change=='source':r[-1]['source_ids']=['a'];r[-1]['origin_ids']=['A']
                if change=='origin':r[-1]['origin_ids']=['A','B','B']
                if change=='incomplete':r[-1].update(native_status='INCOMPLETE',incomplete=True)
                if change=='failed':r[-1]['native_status']='FAILED'
                if change=='not_executed':r[-1]['executed']=False
                if change=='program':r[-1]['program_sha256']='0'*64
                self.assertFalse(self.check(receipts=r)['passed'])

    def test_artifact_hash_and_path_checks(self):
        for key,path in [('result_path','../outside.json'),('result_path','source-a.json'),('result_sha256','0'*64)]:
            r=copy.deepcopy(self.receipts);r[-1][key]=path
            self.assertFalse(self.check(receipts=r)['passed'])
        (self.root/'source-a.json').write_text('{"cents":999}')
        self.assertFalse(self.check()['passed'])

    def test_unrelated_result_change_rejected(self):
        p=self.root/'total-result.json';v=json.loads(p.read_text());v['other_total']+=1;p.write_text(json.dumps(v))
        self.receipts[-1]['result_sha256']=file_digest(p)
        self.assertFalse(self.check()['passed'])

    def test_independent_origins_count_copies_once(self):
        p=self.root/'total-result.json';v=json.loads(p.read_text());v['independent_origins']=3;p.write_text(json.dumps(v))
        self.receipts[-1]['result_sha256']=file_digest(p)
        self.assertFalse(self.check()['passed'])

    def test_nonfinite_float_and_boolean_exactness(self):
        for value in (1.25,True,'NaN','Infinity'):
            with self.assertRaises(ValueError):exact_number(value)
        self.assertEqual(exact_number('0.1')+exact_number('0.2'),exact_number('0.3'))
        self.assertEqual(exact_number(10**70)+exact_number(1),exact_number(str(10**70+1)))

    def test_invalid_requests_are_reports(self):
        for q in ({},[],{'version':'weave.request.v1','plan':{},'checks':[]}):
            self.assertFalse(self.check(request=q)['passed'])
        q=copy.deepcopy(self.request);q['checks']=[];self.assertFalse(self.check(request=q)['passed'])

    def test_feedback_excludes_source_contents(self):
        path=self.root/'memory.jsonl'
        append_memory(path,self.check());append_memory(path,self.check(receipts=[]))
        rows=[json.loads(s) for s in path.read_text().splitlines()]
        self.assertEqual(len(rows),2);self.assertTrue(rows[0]['passed']);self.assertFalse(rows[1]['passed'])
        self.assertNotIn('source-a',path.read_text());self.assertNotIn('source_ids',rows[0]);self.assertNotIn('result_values',rows[0])

    def test_json_pointer_escape(self):
        self.assertEqual(pointer({'a/b':{'~x':[4]}},'/a~1b/~0x/0'),4)


if __name__=='__main__':unittest.main()
