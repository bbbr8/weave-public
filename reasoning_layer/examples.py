"""Small synthetic packets that can be executed without a model or answer key."""
from .contracts import make_task

def rules_packet():
    t=make_task('example-rules','File K is recorded.\nIf File K is recorded, then File K is approved.','Is File K approved?',['True','False','Unknown'],data_class='synthetic')
    p=dict(task_id=t['id'],question_sha256=t['question_sha256'],query_signature=t['query_signature'],operation='rules',nodes=[dict(id='p1',text='File K is recorded.',quotes=[dict(source_id='context',quote='File K is recorded.')]),dict(id='p2',text='File K is approved.',quotes=[]),dict(id='p3',text='File K is not approved.',quotes=[])],facts=['p1'],rules=[{'if':['p1'],'then':'p2','basis':'Supplied recorded-to-approved rule'}],goals=[dict(role=r,label=t['policy'][s],node=n,question_sha256=t['question_sha256'],query_signature=t['query_signature']) for r,s,n in [('support','supported','p2'),('refute','refuted','p3')]],calculation=None,assumptions=[])
    return dict(task=t,program=p)

def arithmetic_packet():
    context='Fee A: $148.35. Fee B: $216.75. Credit: $24.10.'
    t=make_task('example-money',context,'What is the total of both fees after the credit?',[],policy=dict(mode='numeric',unit='money',basis='Exact sum of stated fees less stated credit'),operation='arithmetic',data_class='synthetic')
    ops=[dict(name=n,value=v,unit='money',source_id='context',quote=q) for n,v,q in [('fee_a','148.35','Fee A: $148.35.'),('fee_b','216.75','Fee B: $216.75.'),('credit','24.10','Credit: $24.10.')]]
    p=dict(task_id=t['id'],question_sha256=t['question_sha256'],query_signature=t['query_signature'],operation='arithmetic',nodes=[],facts=[],rules=[],goals=[],calculation=dict(operands=ops,formula='fee_a + fee_b - credit'),assumptions=[])
    return dict(task=t,program=p)

