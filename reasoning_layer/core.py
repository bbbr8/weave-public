"""Inspectable validation and answer resolution; no model calls or native imports."""
from __future__ import annotations
import ast
from decimal import Decimal, localcontext
import re
from .contracts import ABSTAIN, digest, signature, validate_task

def issue(code, detail, severity="error", node=None):
    return dict(code=code, detail=detail, severity=severity, node=node)

def citation(task, quote):
    if not isinstance(quote, dict) or set(quote) != {"source_id", "quote"}: raise ValueError("citation needs source_id and quote")
    if quote["source_id"] != "context": raise ValueError("facts and operands must cite supplied context")
    text = quote["quote"]
    if not isinstance(text, str) or not text or text not in task["context"]: raise ValueError("quoted text is absent from the source")
    start = task["context"].find(text)
    return dict(source_id="context", start=start, end=start+len(text), quote=text, source_sha256=task["context_sha256"], occurrence_count=task["context"].count(text))

def formula_tree(formula, operands):
    tree = ast.parse(formula, mode="eval")
    if len(list(ast.walk(tree))) > 100: raise ValueError("formula exceeds bound")
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.UAdd, ast.USub, ast.Name, ast.Load, ast.Constant)
    for n in ast.walk(tree):
        if not isinstance(n, allowed): raise ValueError("formula permits only names, decimal constants and + - * /")
        if isinstance(n, ast.Name) and n.id not in operands: raise ValueError("formula names undeclared operand")
        if isinstance(n, ast.Constant) and (isinstance(n.value, bool) or not isinstance(n.value, (int, float)) or not Decimal(str(n.value)).is_finite() or len(str(n.value))>24): raise ValueError("invalid formula constant")
    return tree

def formula_unit(tree,units):
    def unit(n):
        if isinstance(n,ast.Expression):return unit(n.body)
        if isinstance(n,ast.Name):return units[n.id]
        if isinstance(n,ast.Constant):return 'number'
        if isinstance(n,ast.UnaryOp):return unit(n.operand)
        a,b=unit(n.left),unit(n.right)
        if isinstance(n.op,(ast.Add,ast.Sub)):
            if a!=b:raise ValueError('addition/subtraction mixes money and dimensionless numbers')
            return a
        if isinstance(n.op,ast.Mult):
            if a==b=='money':raise ValueError('money times money is not supported')
            return 'money' if 'money' in [a,b] else 'number'
        if a=='number' and b=='money':raise ValueError('inverse money unit is not supported')
        return 'number' if a==b else a
    return unit(tree)

def calculate(calculation):
    operands = {x["name"]: Decimal(x["value"]) for x in calculation["operands"]}
    tree = formula_tree(calculation["formula"], operands)
    def ev(n):
        if isinstance(n, ast.Expression): return ev(n.body)
        if isinstance(n, ast.Name): return operands[n.id]
        if isinstance(n, ast.Constant): return Decimal(str(n.value))
        if isinstance(n, ast.UnaryOp): return -ev(n.operand) if isinstance(n.op, ast.USub) else ev(n.operand)
        a,b=ev(n.left),ev(n.right)
        if isinstance(n.op, ast.Add): return a+b
        if isinstance(n.op, ast.Sub): return a-b
        if isinstance(n.op, ast.Mult): return a*b
        return a/b
    with localcontext() as ctx:
        ctx.prec=50
        return ev(tree)

def validate_program(task, program):
    diagnostics = [issue("task_invalid", x) for x in validate_task(task)]
    resolved=[]
    if diagnostics: return dict(valid=False, diagnostics=diagnostics, citations=[], semantic_assurance="not_evaluated")
    if not isinstance(program, dict): return dict(valid=False,diagnostics=[issue("program_shape","program must be an object")],citations=[])
    for field in ["task_id","question_sha256","query_signature","operation","nodes","facts","rules","goals","calculation","assumptions"]:
        if field not in program: diagnostics.append(issue("program_field_missing",field))
    if diagnostics: return dict(valid=False,diagnostics=diagnostics,citations=[])
    required={'task_id','question_sha256','query_signature','operation','nodes','facts','rules','goals','calculation','assumptions'}
    if set(program)-{'source_ledger'}!=required:diagnostics.append(issue('unknown_program_fields','program fields differ from the contract'))
    if not isinstance(program['assumptions'],list) or any(not isinstance(x,str) for x in program['assumptions']):diagnostics.append(issue('invalid_assumptions','assumptions must be a list of strings'))
    if program["task_id"] != task["id"]: diagnostics.append(issue("task_identity_changed","program task ID differs"))
    if program["question_sha256"] != task["question_sha256"]: diagnostics.append(issue("question_changed","original question hash differs"))
    if program["query_signature"] != task["query_signature"]: diagnostics.append(issue("query_signature_changed","modality, quantifier or polarity differs from frozen task"))
    expected=task["operation"]
    if expected not in ["auto", "direct"] and program["operation"]!=expected: diagnostics.append(issue("operation_changed","program changed the caller's operation"))
    if program["assumptions"]: diagnostics.append(issue("assumptions_declared","Program relies on explicitly declared assumptions", "review"))
    if program["operation"]=="arithmetic":
        if any(program[k]!=[] for k in ['nodes','facts','rules','goals']):diagnostics.append(issue('mixed_operations','arithmetic programs must keep rule arrays empty'))
        calc=program["calculation"]
        try:
            if task["policy"]["mode"]!="numeric": raise ValueError("arithmetic requires caller-declared numeric policy")
            if not isinstance(calc,dict) or set(calc)!={"operands","formula"}: raise ValueError("calculation needs operands and formula")
            if not 1<=len(calc["operands"])<=12: raise ValueError("operand bound 1..12")
            names=[]
            for op in calc["operands"]:
                if set(op)!={"name","value","unit","source_id","quote"}: raise ValueError("operand fields differ")
                if not re.fullmatch(r"[a-z][a-z0-9_]{0,23}",op["name"]): raise ValueError("invalid operand name")
                names.append(op["name"])
                if op["unit"] not in ["number","money"]: raise ValueError("invalid operand unit")
                if not re.fullmatch(r"-?\d{1,18}(?:\.\d{1,12})?",op["value"]): raise ValueError("invalid bounded decimal")
                if op['unit']=='money' and Decimal(op['value']).as_tuple().exponent < -2:raise ValueError('money operands require at most two decimal places')
                resolved.append(citation(task,{"source_id":op["source_id"],"quote":op["quote"]}))
                numbers=re.findall(r"-?\d+(?:,\d{3})*(?:\.\d+)?",op["quote"])
                if Decimal(op["value"]) not in [Decimal(n.replace(',','')) for n in numbers]: raise ValueError("operand value is not present in its quote; explicit normalization required")
            if len(names)!=len(set(names)): raise ValueError("duplicate operands")
            tree=formula_tree(calc["formula"],set(names))
            if formula_unit(tree,{o['name']:o['unit'] for o in calc['operands']})!=task['policy']['unit']:raise ValueError('formula result unit differs from task policy')
            calculate(calc)
        except Exception as exc: diagnostics.append(issue("calculation_invalid",str(exc)))
    elif program["operation"]=="rules":
        try:
            nodes=program["nodes"]
            if not isinstance(nodes,list) or not 1<=len(nodes)<=64: raise ValueError("node bound 1..64")
            byid={}
            for n in nodes:
                if set(n)!={"id","text","quotes"} or not isinstance(n['text'],str) or not n['text']: raise ValueError("invalid node fields")
                if not re.fullmatch(r"p\d{1,4}",n["id"]) or n["id"] in byid: raise ValueError("invalid/duplicate node ID")
                byid[n["id"]]=n
                for quote in n["quotes"]: resolved.append(citation(task,quote))
            facts=program["facts"]
            if not isinstance(facts,list) or len(facts)>64 or len(facts)!=len(set(facts)): raise ValueError("invalid facts")
            for fact in facts:
                if fact not in byid: raise ValueError("fact node missing")
                if not byid[fact]["quotes"]: diagnostics.append(issue("unsourced_fact","asserted fact has no source quote",node=fact))
            if not isinstance(program["rules"],list) or len(program["rules"])>128: raise ValueError("invalid rule bound")
            for rule in program["rules"]:
                if set(rule)!={"if","then","basis"} or not isinstance(rule['if'],list) or not 1<=len(rule["if"])<=8 or not isinstance(rule['basis'],str): raise ValueError("invalid rule")
                if any(n not in byid for n in rule["if"]+[rule["then"]]): raise ValueError("rule references missing node")
            goals=program["goals"]
            if not isinstance(goals,list): raise ValueError("goals must be a list")
            seen=set()
            for goal in goals:
                if set(goal)!={"role","label","node","question_sha256","query_signature"}: raise ValueError("invalid goal fields")
                if goal["node"] not in byid: raise ValueError("goal node missing")
                if goal["question_sha256"]!=task["question_sha256"] or goal["query_signature"]!=task["query_signature"]: diagnostics.append(issue("goal_question_changed","answer goal changed the frozen question",node=goal['node']))
                if task["policy"]["mode"]=="truth":
                    if goal["role"] not in ['support','refute']: raise ValueError("truth goals require support/refute roles")
                    expected_label=task['policy']['supported' if goal['role']=='support' else 'refuted']
                    if goal['label']!=expected_label: diagnostics.append(issue("goal_label_changed","goal label differs from caller policy",node=goal['node']))
                    key=goal['role']
                elif task["policy"]["mode"]=="choice":
                    if goal['role']!='choice' or goal['label'] not in task['labels']: raise ValueError("invalid choice goal")
                    key=goal['label']
                else: raise ValueError("rules require truth or choice policy")
                if key in seen: diagnostics.append(issue("duplicate_goal_role","each answer role/label needs one goal"))
                seen.add(key)
                node_text=byid[goal['node']]['text']
                if signature(node_text)['modality']=='required' and task['query_signature']['modality']!='required':
                    diagnostics.append(issue("possible_modality_strengthening","Goal text adds a requirement absent from the question; inspect its actual logical role",'review',goal['node']))
            needed={'support','refute'} if task['policy']['mode']=='truth' else set(task['labels'])
            if seen!=needed: diagnostics.append(issue("answer_coverage_incomplete","expected goals "+str(sorted(needed))+", found "+str(sorted(seen))))
            if len({g['node'] for g in goals})!=len(goals): diagnostics.append(issue("answer_goal_collision","different answer roles share one node"))
        except Exception as exc: diagnostics.append(issue("program_structure",str(exc)))
    else: diagnostics.append(issue("unknown_operation","native operation must be rules or arithmetic"))
    return dict(valid=not any(x['severity']=='error' for x in diagnostics),diagnostics=diagnostics,citations=resolved,semantic_assurance="Span matching and typed consistency only; source entailment requires review")

def lower(program):
    """Compile wide conjunctions to the six-premise common native interface.

    Auxiliary atoms are derived only; source programs and their rule identities
    remain untouched. The bridge verifies full compiled closure before projecting
    results back onto original atoms.
    """
    nodes={n['id']:n['text'] for n in program['nodes']}
    rules=[];steps=[];candidate=9999
    for i,rule in enumerate(program['rules']):
        body=list(rule['if'])
        while len(body)>6:
            while 'p'+str(candidate) in nodes:candidate-=1
            auxiliary='p'+str(candidate);candidate-=1
            nodes[auxiliary]='Compiler conjunction for original rule '+str(i)
            rules.append({'if':body[:6],'then':auxiliary,'basis':rule['basis']})
            steps.append(dict(original_rule=i,compiled_rule=len(rules)-1,auxiliary=auxiliary,premises=body[:6]))
            body=[auxiliary]+body[6:]
        rules.append(dict(rule,**{'if':body}))
    return dict(nodes=nodes,facts=list(program['facts']),rules=rules,answers={},
                compilation=dict(max_premises=6,original_nodes=[n['id'] for n in program['nodes']],steps=steps))

def closure(program):
    known=set(program['facts']);witnesses={n:{'kind':'source_fact'} for n in known}
    while True:
        added=False
        for i,r in enumerate(program['rules']):
            if r['then'] not in known and set(r['if'])<=known:
                known.add(r['then']);witnesses[r['then']]={'kind':'rule','index':i,'premises':r['if'],'basis':r['basis']};added=True
        if not added:return known,witnesses

def resolve(task,program,known):
    if task['policy']['mode']=='truth':
        fired={g['role'] for g in program['goals'] if g['node'] in known}
        state='inconsistent' if fired=={'support','refute'} else 'supported' if 'support' in fired else 'refuted' if 'refute' in fired else 'undetermined'
        return dict(answer=task['policy'][state],state=state,policy_basis=task['policy']['basis'])
    labels={g['label'] for g in program['goals'] if g['node'] in known}
    state='resolved' if len(labels)==1 else 'conflicting' if labels else 'unresolved'
    return dict(answer=next(iter(labels)) if len(labels)==1 else task['policy'][state],state=state,policy_basis=task['policy']['basis'])

def format_number(value,unit):
    value=Decimal(str(value))
    return '$'+format(value.quantize(Decimal('.01')),'.2f') if unit=='money' else format(value.normalize(),'f')

def reference_execute(task,program):
    if program['operation']=='arithmetic':
        result=format_number(calculate(program['calculation']),task['policy']['unit'])
        return dict(answer=result,state='calculated',backend='reference_decimal',native=False)
    known,witness=closure(program)
    return dict(**resolve(task,program,known),known=sorted(known),witnesses=witness,backend='reference_closure',native=False)
