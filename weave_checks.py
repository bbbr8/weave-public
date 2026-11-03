"""Typed request assertions and exact, dependency-aware Weave result checks."""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import json
import re


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def exact_equal(a,b):return canonical(a)==canonical(b)


def pointer_parts(path):
    if not isinstance(path,str) or (path and not path.startswith('/')):raise ValueError('Invalid JSON pointer')
    parts=path.split('/')[1:] if path else []
    if any(re.search(r'~(?![01])',x) for x in parts):raise ValueError('Invalid JSON pointer escape')
    return [x.replace('~1','/').replace('~0','~') for x in parts]


def pointer(value,path):
    for key in pointer_parts(path):
        if isinstance(value,list):
            if not key.isdigit() or (len(key)>1 and key.startswith('0')):raise ValueError('Invalid list index')
            value=value[int(key)]
        elif isinstance(value,dict):value=value[key]
        else:raise ValueError('Pointer traverses a scalar')
    return value


def exact_number(value):
    if type(value) is int:return Fraction(value)
    if isinstance(value,str) and len(value)<=256:
        try:result=Decimal(value)
        except InvalidOperation:raise ValueError('Invalid exact decimal')
        if result.is_finite() and -1000<=result.adjusted()<=1000:return Fraction(result)
    raise ValueError('Exact arithmetic needs integer units or finite decimal strings')


def changed_paths(before,after,path=''):
    escape=lambda k:str(k).replace('~','~0').replace('/','~1')
    if type(before) is not type(after):return [path]
    if isinstance(before,dict):
        paths=[path+'/'+escape(k) for k in set(before)^set(after)]
        for k in set(before)&set(after):paths+=changed_paths(before[k],after[k],path+'/'+escape(k))
        return sorted(paths)
    if isinstance(before,list):
        if len(before)!=len(after):return [path]
        return sorted(p for i,(a,b) in enumerate(zip(before,after)) for p in changed_paths(a,b,path+'/'+str(i)))
    return [] if exact_equal(before,after) else [path]


FIELDS={
 'equals':({'value'},set()),'sum':({'terms'},set()),'product':({'terms'},set()),
 'difference':({'left','right'},set()),'range':(set(),{'minimum','maximum','minimum_inclusive','maximum_inclusive'}),
 'unchanged':({'baseline_step','baseline_pointer'},set()),'origin_count':({'source_ids'},set()),
 'set_equals':({'values'},set()),'field_changes':({'baseline_step','baseline_pointer','paths'},set()),
 'receipt_status':({'value'},{'completion_state'}),
}


def references(check):
    result=[check['step']]
    if check['kind'] in ('sum','product'):result.extend(t['step'] for t in check['terms'])
    if check['kind']=='difference':result.extend(check[k]['step'] for k in ('left','right'))
    if check['kind'] in ('unchanged','field_changes'):result.append(check['baseline_step'])
    return result


def validate_check(check,step_ids):
    if not isinstance(check,dict) or not isinstance(check.get('kind'),str) or check['kind'] not in FIELDS:raise ValueError('Unknown check kind')
    kind=check['kind']; required,optional=FIELDS[kind]
    base={'kind','step'} if kind=='receipt_status' else {'kind','step','pointer'}
    if kind in ('equals','sum','difference','product','range'):optional=optional|{'unit'}
    if not base|required<=set(check) or not set(check)<=base|required|optional:raise ValueError('Check fields do not match its kind')
    if not isinstance(check['step'],str):raise ValueError('Check step must be text')
    if kind!='receipt_status':pointer_parts(check['pointer'])
    def ref(value):
        if not isinstance(value,dict) or set(value)!={'step','pointer'} or not isinstance(value['step'],str):raise ValueError('Invalid check operand')
        pointer_parts(value['pointer'])
    if kind in ('sum','product'):
        if not isinstance(check['terms'],list) or not 1<=len(check['terms'])<=128:raise ValueError('Expected bounded terms')
        for term in check['terms']:ref(term)
    if kind=='difference':
        for key in ('left','right'):ref(check[key])
    if kind in ('unchanged','field_changes'):
        if not isinstance(check['baseline_step'],str):raise ValueError('Baseline step must be text')
        pointer_parts(check['baseline_pointer'])
    if kind=='field_changes':
        paths=check['paths']
        if not isinstance(paths,list) or any(not isinstance(x,str) for x in paths) or len(paths)!=len(set(paths)):raise ValueError('Unique changed paths required')
        for p in paths:pointer_parts(p)
    if kind=='origin_count' and (not isinstance(check['source_ids'],list) or not check['source_ids'] or any(not isinstance(x,str) for x in check['source_ids'])):raise ValueError('Source IDs required')
    if kind=='set_equals':
        if not isinstance(check['values'],list) or len(check['values'])!=len({canonical(v) for v in check['values']}):raise ValueError('Distinct set values required')
    if kind=='range':
        if not {'minimum','maximum'}&set(check):raise ValueError('Range bound required')
        for k in ('minimum','maximum'):
            if k in check:exact_number(check[k])
        for k in ('minimum_inclusive','maximum_inclusive'):
            if k in check and type(check[k]) is not bool:raise ValueError('Range policy must be boolean')
        if {'minimum','maximum'}<=set(check) and exact_number(check['minimum'])>exact_number(check['maximum']):raise ValueError('Range bounds reversed')
    if kind=='receipt_status':
        if not isinstance(check['value'],str) or not check['value']:raise ValueError('Native status required')
        if 'completion_state' in check and check['completion_state'] not in ('COMPLETE','INCOMPLETE','FAILED'):raise ValueError('Completion status invalid')
    if 'unit' in check and (not isinstance(check['unit'],str) or not check['unit']):raise ValueError('Unit must be text')
    if any(s not in step_ids for s in references(check)):raise ValueError('Unknown check reference')
    canonical(check)


def evaluate_check(check,outputs,receipts,sources):
    row={'kind':check['kind'],'step':check['step'],'passed':False,'status':'NOT_EVALUATED'}
    if 'pointer' in check:row['pointer']=check['pointer']
    if any(s not in outputs or s not in receipts for s in references(check)):
        row['reason']='INPUT_RESULT_UNVERIFIED';return row
    try:
        kind=check['kind'];step=check['step'];receipt=receipts[step]
        actual=pointer(outputs[step],check['pointer']) if kind!='receipt_status' else None
        def operand(ref):return pointer(outputs[ref['step']],ref['pointer'])
        if 'unit' in check:
            refs=[{'step':step,'pointer':check['pointer']}]
            if kind=='sum':refs+=check['terms']
            if kind=='difference':refs+=[check['left'],check['right']]
            if any(receipts[r['step']].get('result_units',{}).get(r['pointer'])!=check['unit'] for r in refs):
                row.update(status='FAILED',reason='UNIT_MISMATCH');return row
        if kind=='equals':passed=exact_equal(actual,check['value'])
        elif kind=='sum':passed=exact_number(actual)==sum((exact_number(operand(t)) for t in check['terms']),Fraction(0))
        elif kind=='difference':passed=exact_number(actual)==exact_number(operand(check['left']))-exact_number(operand(check['right']))
        elif kind=='product':
            total=Fraction(1)
            for term in check['terms']:total*=exact_number(operand(term))
            passed=exact_number(actual)==total
        elif kind=='range':
            number=exact_number(actual);passed=True
            if 'minimum' in check:
                bound=exact_number(check['minimum']);passed&=number>=bound if check.get('minimum_inclusive',True) else number>bound
            if 'maximum' in check:
                bound=exact_number(check['maximum']);passed&=number<=bound if check.get('maximum_inclusive',True) else number<bound
        elif kind=='unchanged':passed=exact_equal(actual,pointer(outputs[check['baseline_step']],check['baseline_pointer']))
        elif kind=='origin_count':
            ids=check['source_ids']
            passed=set(ids)<=set(receipt['source_ids']) and type(actual) is int and actual==len({sources[x]['origin_id'] for x in ids})
        elif kind=='set_equals':
            encoded=[canonical(x) for x in actual] if isinstance(actual,list) else None
            passed=encoded is not None and len(encoded)==len(set(encoded)) and set(encoded)=={canonical(x) for x in check['values']}
        elif kind=='field_changes':
            paths=changed_paths(pointer(outputs[check['baseline_step']],check['baseline_pointer']),actual)
            row['changed_paths']=paths;passed=paths==sorted(check['paths'])
        elif kind=='receipt_status':
            completion=receipt.get('completion_state',receipt['native_status'])
            passed=receipt['native_status']==check['value'] and ('completion_state' not in check or completion==check['completion_state'])
        else:raise ValueError('Unknown check')
        row.update(passed=bool(passed),status='PASSED' if passed else 'FAILED',reason='MATCH' if passed else 'ASSERTION_MISMATCH')
    except (KeyError,TypeError,ValueError,IndexError,InvalidOperation,AttributeError):
        row.update(status='FAILED',reason='INVALID_ASSERTION_VALUE')
    return row
