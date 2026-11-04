import copy
import json
from pathlib import Path
import tempfile
import unittest
from reasoning_layer.contracts import digest,make_task
from reasoning_layer.examples import rules_packet
from reasoning_layer.model import CodexModel
from reasoning_layer.native import ReferenceBackend
from reasoning_layer.pipeline import ReasoningLayer

class Model:
    def __init__(self,p,kind):self.p=p;self.kind=kind;self.count=0
    def respond(self,prompt,schema,folder):
        self.count+=1
        return {'programs':[self.p]} if self.count==1 else {'reviews':[dict(id=self.p['task_id'],accepted=False,issues=[dict(kind=self.kind,detail='review fixture')],program=self.p)]}

def unknown_packet():
    x=rules_packet();t=x['task'];p=x['program']
    x['task']=make_task(t['id'],'If File K is recorded, it is approved. No facts about File K are supplied.',t['question'],t['labels'],data_class='synthetic')
    p['facts']=[];p['nodes'][0]['quotes']=[]
    return x

class ReviewPolicy(unittest.TestCase):
    def test_insufficient_evidence_is_valid_unknown(self):
        x=unknown_packet();m=Model(x['program'],'insufficient_evidence')
        with tempfile.TemporaryDirectory() as d:
            r=ReasoningLayer(m,ReferenceBackend(),source_accounting=False).run([x['task']],d)[x['task']['id']]
            self.assertEqual(r['answer'],'Unknown');self.assertEqual(r['review_status'],'preserved_unknown_by_task_policy')
    def test_actual_source_defect_still_abstains(self):
        x=unknown_packet();m=Model(x['program'],'source_mismatch')
        with tempfile.TemporaryDirectory() as d:self.assertEqual(ReasoningLayer(m,ReferenceBackend(),source_accounting=False).run([x['task']],d)[x['task']['id']]['answer'],'ABSTAIN')
    def test_uncertainty_cannot_preserve_an_asserted_positive(self):
        x=rules_packet();m=Model(x['program'],'insufficient_evidence')
        with tempfile.TemporaryDirectory() as d:self.assertEqual(ReasoningLayer(m,ReferenceBackend(),source_accounting=False).run([x['task']],d)[x['task']['id']]['answer'],'ABSTAIN')
    def test_invalid_goal_cannot_bypass_validation_as_unknown(self):
        x=unknown_packet();x['program']['goals'][0]['question_sha256']='wrong';m=Model(x['program'],'insufficient_evidence')
        with tempfile.TemporaryDirectory() as d:self.assertEqual(ReasoningLayer(m,ReferenceBackend(),source_accounting=False).run([x['task']],d)[x['task']['id']]['answer'],'ABSTAIN')
    def test_completed_run_reuses_outputs_without_model_call(self):
        x=unknown_packet();m=Model(x['program'],'insufficient_evidence')
        with tempfile.TemporaryDirectory() as d:
            layer=ReasoningLayer(m,ReferenceBackend(),source_accounting=False);first=layer.run([x['task']],d);again=layer.run([x['task']],d)
            self.assertEqual(first,again);self.assertEqual(m.count,2)
    def test_cached_model_cannot_be_relabelled_as_another_model(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'request.json').write_text(json.dumps(dict(prompt_digest=digest('prompt'),model_requested='other',effort='high')))
            with self.assertRaisesRegex(RuntimeError,'different model'):CodexModel().respond('prompt',{},p)
    def test_cached_model_cannot_change_schema(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'request.json').write_text(json.dumps(dict(prompt_digest=digest('prompt'),model_requested='gpt-6.1-sol',effort='high',schema_digest=digest({'type':'object'}))))
            with self.assertRaisesRegex(RuntimeError,'different output schema'):CodexModel().respond('prompt',{'type':'string'},p)

if __name__=='__main__':unittest.main()
