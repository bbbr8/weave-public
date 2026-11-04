import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from evidence_search import EvidenceIndex,file_records


def row(ident,text,parent='report-A',**meta):
    return dict(id=ident,parent_id=parent,text=text,locator='fictional:'+ident,metadata=meta)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'index.sqlite';self.ix=EvidenceIndex(self.path,True)
    def tearDown(self):self.ix.close();self.tmp.cleanup()

    def test_scope_before_candidate_limit(self):
        self.ix.ingest([row('other'+str(i),'settlement credit payment',account='other') for i in range(1200)]+
                       [row('wanted','settlement credit payment '+('long context '*500),account='00017')])
        r=self.ix.search('settlement credit payment',1,dict(account='00017'))
        self.assertEqual([x['id'] for x in r['hits']],['wanted'])

    def test_leading_zero_account(self):
        self.ix.ingest([row('a','payment',account='00017'),row('b','payment',account='17')])
        self.assertEqual([x['id'] for x in self.ix.search('payment',10,dict(account='00017'))['hits']],['a'])

    def test_receipt_cutoff_preserves_unknown(self):
        self.ix.ingest([row('early','notice',received='2044-02-01'),row('late','notice',received='2044-04-01'),row('unknown','notice')])
        self.assertEqual([x['id'] for x in self.ix.search('notice',10,before=dict(received='2044-03-01'))['hits']],['early'])
        self.assertEqual(self.ix.search('notice')['scoped_records'],3)

    def test_sent_is_not_applied_by_metadata(self):
        self.ix.ingest([row('sent','payment invoice',stage='payment_sent'),row('applied','payment invoice',stage='payment_applied')])
        self.assertEqual([x['id'] for x in self.ix.search('payment invoice',10,dict(stage='payment_applied'))['hits']],['applied'])

    def test_text_revision_invalidates_citation_and_old_index_terms(self):
        self.ix.ingest([row('a','earlier invoice balance')]);old=self.ix.search('earlier')['hits'][0]
        self.ix.ingest([row('a','corrected invoice balance')])
        self.assertEqual(self.ix.validate_citation(old),dict(valid=False,reason='record_changed'))
        self.assertFalse(self.ix.search('earlier')['hits'])

    def test_metadata_revision_invalidates_citation(self):
        self.ix.ingest([row('a','payment',stage='sent')]);old=self.ix.search('payment')['hits'][0]
        self.ix.ingest([row('a','payment',stage='applied')]);self.assertFalse(self.ix.validate_citation(old)['valid'])

    def test_failed_import_is_atomic(self):
        with self.assertRaises(ValueError):self.ix.ingest([row('valid','invoice'),dict(id='broken')])
        self.assertEqual(self.ix.stats()['records'],0)

    def test_conflicting_duplicate_rejected(self):
        with self.assertRaises(ValueError):self.ix.ingest([row('a','first value'),row('a','different value')])
        self.assertEqual(self.ix.stats()['records'],0)

    def test_followup_finds_nonmatching_row(self):
        self.ix.ingest([row('anchor','What percent of current debt?'),row('total','Total 1000',order=1),row('amount','2011 463',order=2)])
        self.assertNotIn('amount',[x['id'] for x in self.ix.search('percent current debt')['hits']])
        r=self.ix.expand('percent current debt');self.assertIn('amount',[x['id'] for x in r['hits']])
        self.assertTrue(any(x['stage']=='followup' for x in r['trace']))

    def test_expansion_respects_original_scope(self):
        self.ix.ingest([row('a','debt ratio',account='A'),row('b','total 500',account='B'),row('c','2011 123',account='A')])
        r=self.ix.expand('debt ratio',where=dict(account='A'))
        self.assertEqual({h['id'] for h in r['hits']},{'a','c'})

    def test_expansion_budgets_disclosed(self):
        self.ix.ingest([row(str(i),'invoice debt '+('x'*100)) for i in range(20)])
        r=self.ix.expand('invoice',max_records=3,max_chars=250)
        self.assertLessEqual(len(r['hits']),3);self.assertLessEqual(r['budget']['used_chars'],250)
        self.assertTrue(r['budget']['limit_reached'])

    def test_persistence(self):
        self.ix.ingest([row('a','persisted source')]);other=EvidenceIndex(self.path)
        try:self.assertEqual(other.search('persisted')['hits'][0]['id'],'a')
        finally:other.close()

    def test_remove_clears_postings_and_citation(self):
        self.ix.ingest([row('a','withdrawn invoice')]);old=self.ix.search('invoice')['hits'][0];self.ix.remove(['a'])
        self.assertFalse(self.ix.search('invoice')['hits']);self.assertEqual(self.ix.validate_citation(old)['reason'],'record_missing')

    def test_shortened_native_file_removes_old_chunks(self):
        p=Path(self.tmp.name)/'source.txt';p.write_text('old debt '*700)
        self.ix.index_files([str(p)]);self.assertGreater(self.ix.stats()['records'],1)
        p.write_text('new credit');self.ix.index_files([str(p)])
        self.assertEqual(self.ix.stats()['records'],1);self.assertFalse(self.ix.search('old debt')['hits'])

    def test_source_character_offsets(self):
        p=Path(self.tmp.name)/'source.md';p.write_bytes(('évidence\r\n'*400).encode())
        decoded=p.read_bytes().decode()
        for r in file_records([str(p)]):
            self.assertEqual(decoded[r['metadata']['start']:r['metadata']['end']],r['text'])

    def test_parameterized_filters_and_quoted_query(self):
        self.ix.ingest([row('a','invoice balance',account="a' OR 1=1 --"),row('b','unrelated',account='B')])
        r=self.ix.search('"invoice" OR * --',10,dict(account="a' OR 1=1 --"));self.assertEqual([x['id'] for x in r['hits']],['a'])

    def test_empty_query_and_invalid_limits(self):
        self.ix.ingest([row('a','invoice')]);self.assertEqual(self.ix.search('!!!')['status'],'empty_query')
        with self.assertRaises(ValueError):self.ix.search('invoice',True)
        with self.assertRaises(ValueError):self.ix.search('invoice',before=dict(received='2044-99-99'))

    def test_exact_snippets(self):
        self.ix.ingest([row('a','initial '+('padding '*90)+'invoice balance final')])
        h=self.ix.search('invoice')['hits'][0];s=h['snippet'];self.assertEqual(h['text'][s['start']:s['end']],s['text'])

    def test_declared_links_cross_parents_and_cycles(self):
        self.ix.ingest([row('a','invoice reconciliation',depends_on=['b']),row('b','credit 123',parent='credit-register',depends_on=['a'])])
        r=self.ix.expand('invoice reconciliation');self.assertEqual({x['id'] for x in r['hits']},{'a','b'})
        self.assertEqual(r['unresolved_dependencies'],[])

    def test_missing_link_resolved_after_more_data_imported(self):
        self.ix.ingest([row('a','invoice reconciliation',depends_on=['b'])])
        r=self.ix.expand('invoice reconciliation');self.assertEqual(r['unresolved_dependencies'][0]['reason'],'missing_from_index')
        self.ix.ingest([row('b','credit posted',parent='credit-register')]);self.assertEqual(self.ix.expand('invoice reconciliation')['unresolved_dependencies'],[])

    def test_link_obeys_scope_and_receipt_constraints(self):
        self.ix.ingest([row('a','invoice reconciliation',account='A',depends_on=['b']),row('b','credit posted',parent='other',account='B')])
        r=self.ix.expand('invoice reconciliation',where=dict(account='A'))
        self.assertEqual(r['unresolved_dependencies'][0]['reason'],'excluded_by_scope')

    def test_link_depth_limit(self):
        self.ix.ingest([row('a','invoice reconciliation',depends_on=['b']),row('b','credit posted',parent='other',depends_on=['c']),row('c','reversal posted',parent='third')])
        r=self.ix.expand('invoice reconciliation',max_depth=1)
        self.assertEqual(r['unresolved_dependencies'][0]['required_id'],'c')
        self.assertEqual(r['unresolved_dependencies'][0]['reason'],'depth_limit')

    def test_parent_context_links_are_traversed(self):
        self.ix.ingest([row('a','invoice reconciliation'),row('context','unrelated wording',depends_on=['missing'])])
        r=self.ix.expand('invoice reconciliation');self.assertEqual(r['unresolved_dependencies'][0]['required_id'],'missing')

    def test_csv_duplicate_headers_rejected_without_data_loss(self):
        p=Path(self.tmp.name)/'data.csv';p.write_text('amount,amount\n12,99\n')
        with self.assertRaises(ValueError):self.ix.index_files([str(p)])
        self.assertEqual(self.ix.stats()['records'],0)

    def test_json_duplicate_keys_rejected(self):
        p=Path(self.tmp.name)/'data.jsonl';p.write_text('{"id":"a","text":"first","text":"second","locator":"native:a"}\n')
        with self.assertRaises(ValueError):self.ix.index_files([str(p)])
        self.assertEqual(self.ix.stats()['records'],0)

    def test_reimport_prunes_only_its_own_file(self):
        a=Path(self.tmp.name)/'a.txt';b=Path(self.tmp.name)/'b.txt';a.write_text('first source');b.write_text('second source')
        self.ix.index_files([str(a),str(b)]);a.write_text('');self.ix.index_files([str(a)])
        self.assertEqual(self.ix.stats()['records'],1);self.assertTrue(self.ix.search('second')['hits'])

    def test_failed_reimport_keeps_existing_index(self):
        p=Path(self.tmp.name)/'data.jsonl';p.write_text(json.dumps(row('a','old wording'))+'\n');self.ix.index_files([str(p)])
        p.write_text(json.dumps(row('a','new wording'))+'\n'+json.dumps({'id':'broken'})+'\n')
        with self.assertRaises(ValueError):self.ix.index_files([str(p)])
        self.assertTrue(self.ix.search('old wording')['hits']);self.assertFalse(self.ix.search('new')['hits'])

    def test_nonfinite_metadata_rejected(self):
        with self.assertRaises(ValueError):self.ix.ingest([row('a','invoice',amount=float('nan'))])
        self.assertEqual(self.ix.stats()['records'],0)

    def test_malformed_source_dates_do_not_become_known(self):
        self.ix.ingest([row('valid','notice',received='2044-01-01'),row('us-format','notice',received='01/01/2044'),
                        row('invalid-day','notice',received='2043-02-30'),row('unknown','notice',received='unknown')])
        r=self.ix.search('notice',10,before=dict(received='2044-03-01'))
        self.assertEqual([h['id'] for h in r['hits']],['valid'])
        self.assertEqual(self.ix.stats()['records'],4)


if __name__=='__main__':unittest.main()
