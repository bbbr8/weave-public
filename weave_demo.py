"""Execute synthetic fixture operations and demonstrate Weave verification."""
import argparse
import copy
import json
from pathlib import Path
import time
from weave_verify import verify,digest_json,file_digest,append_memory


def create_fixture(root):
    root=Path(root);root.mkdir(exist_ok=False)
    def save(name,value):
        path=root/name
        with path.open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)
        return path
    save('source-a.json',{'cents':12000})
    save('source-b.json',{'cents':10200})
    save('source-b-copy.json',{'cents':10200})
    save('fixture-program.json',{'version':'synthetic-only','operations':['read','sum']})
    sources=[{'id':ident,'origin_id':origin,'path':filename,'sha256':file_digest(root/filename)} for ident,origin,filename in [('a','A','source-a.json'),('b','B','source-b.json'),('b_copy','B','source-b-copy.json')]]
    request={'version':'weave.request.v1','require_complete':True,'plan':{'version':'weave.v1','steps':[
        {'id':'input','op':'read','inputs':[],'args':{'program_ref':'fixture/read'}},
        {'id':'total','op':'calculate','inputs':['input'],'args':{'program_ref':'fixture/sum'}}]},
        'sources':sources,'required_sources':{'input':['a','b','b_copy'],'total':['a','b','b_copy']},
        'checks':[
         {'kind':'equals','step':'total','pointer':'/total_cents','value':22200},
         {'kind':'sum','step':'total','pointer':'/total_cents','terms':[{'step':'input','pointer':'/amounts/0'},{'step':'input','pointer':'/amounts/1'}]},
         {'kind':'unchanged','step':'total','pointer':'/other_total','baseline_step':'input','baseline_pointer':'/other_total'},
         {'kind':'origin_count','step':'total','pointer':'/independent_origins','source_ids':['a','b','b_copy']},
         {'kind':'difference','step':'total','pointer':'/difference','left':{'step':'input','pointer':'/amounts/0'},'right':{'step':'input','pointer':'/amounts/1'},'unit':'cents'},
         {'kind':'product','step':'total','pointer':'/product','terms':[{'step':'input','pointer':'/quantity'},{'step':'input','pointer':'/rate'}]},
         {'kind':'range','step':'total','pointer':'/total_cents','minimum':0,'maximum':30000,'unit':'cents'},
         {'kind':'set_equals','step':'total','pointer':'/origin_set','values':['A','B']},
         {'kind':'field_changes','step':'total','pointer':'/revision','baseline_step':'input','baseline_pointer':'/revision','paths':['/amount']},
         {'kind':'receipt_status','step':'total','value':'COMPLETE','completion_state':'COMPLETE'}]}
    request['checks'][1]['unit']='cents'
    runtime_sha=file_digest(__file__); program_sha=file_digest(root/'fixture-program.json')
    catalog={'version':'weave.capabilities.v1','data_class':'synthetic','observed_at':time.time(),'registry':{'mode':'fixture'},'operations':{}}
    for op,engine,ref in [('read','loom','fixture/read'),('calculate','tally','fixture/sum')]:
        catalog['operations'][op]={'engine':engine,'installed':True,'available':True,'adapter_ready':True,'runtime_sha256':runtime_sha,'qualified_runtime_sha256':runtime_sha,'programs':{ref:{'sha256':program_sha,'available':True}}}
    started=time.perf_counter()
    a=json.loads((root/'source-a.json').read_text())['cents'];b=json.loads((root/'source-b.json').read_text())['cents']
    save('input-result.json',{'amounts':[a,b],'other_total':4500,'quantity':2,'rate':3,'revision':{'amount':a,'fixed':4500}})
    read_ms=(time.perf_counter()-started)*1000
    started=time.perf_counter()
    save('total-result.json',{'total_cents':a+b,'other_total':4500,'independent_origins':2,'difference':a-b,'product':2*3,'origin_set':['B','A'],'revision':{'amount':b,'fixed':4500}})
    sum_ms=(time.perf_counter()-started)*1000
    receipts=[]
    for step,path,elapsed in zip(request['plan']['steps'],['input-result.json','total-result.json'],[read_ms,sum_ms]):
        receipts.append({'step_id':step['id'],'engine':catalog['operations'][step['op']]['engine'],'op':step['op'],
            'executed':True,'native_status':'COMPLETE','incomplete':False,'elapsed_ms':elapsed,'coverage':{'fixture_records':3},
            'plan_sha256':digest_json(request['plan']),'args_sha256':digest_json(step['args']),
            'runtime_sha256':runtime_sha,'program_sha256':program_sha,'source_ids':['a','b','b_copy'],'origin_ids':['A','B'],
            'input_hashes':{r['step_id']:r['result_sha256'] for r in receipts if r['step_id'] in step['inputs']},
            'result_path':path,'result_sha256':file_digest(root/path),
            'result_units':{'/amounts/0':'cents','/amounts/1':'cents','/total_cents':'cents','/difference':'cents'}})
    save('request.json',request);save('catalog.json',catalog);save('receipts.json',receipts)
    return request,catalog,receipts


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    args=parser.parse_args();request,catalog,receipts=create_fixture(args.directory)
    good=verify(request,catalog,receipts,args.directory)
    # A coherent but wrong result must fail exact checks even with its hash updated.
    result_path=args.directory/'total-result.json'; altered=json.loads(result_path.read_text());altered['total_cents']+=1
    result_path.write_text(json.dumps(altered),encoding='utf-8')
    bad_receipts=copy.deepcopy(receipts);bad_receipts[-1]['result_sha256']=file_digest(result_path)
    bad=verify(request,catalog,bad_receipts,args.directory)
    append_memory(args.directory/'feedback.jsonl',good);append_memory(args.directory/'feedback.jsonl',bad)
    # Leave the successful fixture coherent and save the rejected variant separately.
    (args.directory/'rejected-result.json').write_text(json.dumps(altered),encoding='utf-8')
    altered['total_cents']-=1;result_path.write_text(json.dumps(altered,indent=2),encoding='utf-8')
    assert file_digest(result_path)==receipts[-1]['result_sha256']
    summary={'data_class':'synthetic','good':good,'coherent_wrong_result':bad}
    (args.directory/'demonstration.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({'synthetic_valid_passed':good['passed'],'coherent_wrong_result_rejected':not bad['passed'],'checks':len(good['checks'])}))
    return 0 if good['passed'] and not bad['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
