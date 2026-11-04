"""Task-owned Mac worker; imports native adapters without modifying their runtimes."""
import hashlib
import json
from pathlib import Path
import sys
import time
import ast
from decimal import Decimal

BASE=Path('/Users/jones/Training Labs/noncase/language-benchmarks-20261103')
sys.path.insert(0,str(BASE))
import engine_pass as e

def tally_expression(calculation):
    operands={o['name']:o for o in calculation['operands']}
    def emit(n):
        if isinstance(n,ast.Expression):return emit(n.body)
        if isinstance(n,ast.Name):
            o=operands[n.id];return '$'+format(Decimal(o['value']),'.2f') if o['unit']=='money' else o['value']
        if isinstance(n,ast.Constant):return str(n.value)
        if isinstance(n,ast.UnaryOp):return '('+('-' if isinstance(n.op,ast.USub) else '+')+emit(n.operand)+')'
        symbols={ast.Add:'+',ast.Sub:'-',ast.Mult:'*',ast.Div:'/'}
        return '('+emit(n.left)+symbols[type(n.op)]+emit(n.right)+')'
    return emit(ast.parse(calculation['formula'],mode='eval'))

def main():
    root=Path(sys.argv[1]);request=json.loads((root/'request.json').read_text())
    paths={n:Path(m.__file__) for n,m in [('TELL',e.tell),('CaseLog',e.caselog),('Warrant',e.warrant),('Accrete',e.accrete),('Finding',e.finding)]}
    paths['Tally']=e.CASE/'tools/tally/tally.py'
    fingerprints={n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in paths.items()}
    results=[];start=time.monotonic()
    with e.Tally() as client:
        engines={'Tally':lambda p:e.run_tally(p,client),'TELL':e.run_tell,'CaseLog':e.run_caselog,'Warrant':e.run_warrant,'Accrete':e.run_accrete,'Finding':e.run_finding}
        for item in request['items']:
            rows=[]
            if item['operation']=='rules':
                for name,fn in engines.items():
                    try:
                        known,code,receipt=fn(item['program'])
                        rows.append(dict(engine=name,status='executed',known=sorted(known),program_sha256=hashlib.sha256(code.encode()).hexdigest()))
                    except Exception as exc:rows.append(dict(engine=name,status='error',error=str(exc)))
            else:
                try:
                    expression=tally_expression(item['calculation']);response=client.eval(expression)
                    rows.append(dict(engine='Tally',status='executed' if response.get('ok') else 'error',expression=expression,response=response))
                except Exception as exc:rows.append(dict(engine='Tally',status='error',error=str(exc)))
            results.append(dict(id=item['id'],operation=item['operation'],engines=rows))
    after={n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in paths.items()}
    assert fingerprints==after,'Runtime changed during execution'
    output=dict(results=results,request_sha256=hashlib.sha256((root/'request.json').read_bytes()).hexdigest(),runtime_sha256=fingerprints,runtimes_unchanged=True,seconds=time.monotonic()-start)
    temp=root/'result.tmp';temp.write_text(json.dumps(output,indent=2));temp.replace(root/'result.json')
    print(json.dumps(dict(items=len(results),runtime_unchanged=True,seconds=output['seconds'])))

if __name__=='__main__':main()

