"""Pinned tiny native jobs over existing fleet transport, with replayable receipts."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shlex
import subprocess
import uuid
from .contracts import digest
from .core import closure, format_number, lower, reference_execute, resolve

FLEET=Path('C:/Users/mbryc/fleet/bin')
REMOTE='/Users/jones/Training Labs/noncase/language-benchmarks-20261103/reasoning-layer-runs'

def dump(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')
def psquote(s):return "'"+str(s).replace("'","''")+"'"

def command(script,folder,name):
    path=folder/(name+'.ps1');path.write_text(script,encoding='utf-8-sig')
    r=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(path)],capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (folder/(name+'.stdout.txt')).write_text(r.stdout,encoding='utf-8');(folder/(name+'.stderr.txt')).write_text(r.stderr,encoding='utf-8')
    if r.returncode:raise RuntimeError(name+' failed; inspect '+str(folder/(name+'.stderr.txt')))

def transfer(direction,source,target,folder,name):
    # Win32 device paths confuse scp's host:path parser; normal drive/UNC paths do not.
    def transport_path(value):
        value=str(value)
        if value.startswith('\\\\?\\UNC\\'):return '\\\\'+value[8:]
        if value.startswith('\\\\?\\'):return value[4:]
        return value
    source=transport_path(source);target=transport_path(target)
    command('& '+psquote(FLEET/'fleetnet.cmd')+' '+direction+' macbook-pro '+psquote(source)+' '+psquote(target)+'\nexit $LASTEXITCODE\n',folder,name)

class ReferenceBackend:
    name='reference'
    def run_many(self,items,folder):return {t['id']:reference_execute(t,p) for t,p in items}

class MacBackend:
    name='mac_native'
    def run_many(self,items,folder):
        folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
        request=dict(items=[dict(id=t['id'],operation=p['operation'],program=lower(p),calculation=p['calculation']) for t,p in items])
        payload=folder/'request.json';statefile=folder/'state.json'
        if payload.exists():
            if json.loads(payload.read_text())!=request:raise RuntimeError('Native request folder already owns different input')
            if not (folder/'result.json').exists():raise RuntimeError('Native job remains pinned; use recover-native, do not duplicate execution')
        else:
            dump(payload,request);remote=REMOTE+'/'+uuid.uuid4().hex
            state=dict(remote=remote,status='prepared',request_digest=digest(request));dump(statefile,state)
            invoke=folder/'invoke.sh';invoke.write_text('mkdir -p '+shlex.quote(remote)+'\n',encoding='utf-8')
            try:
                command('& '+psquote(FLEET/'mac.ps1')+' -File '+psquote(invoke)+'\nexit $LASTEXITCODE\n',folder,'make-remote')
                transfer('put',payload,remote+'/request.json',folder,'stage-input')
                transfer('put',Path(__file__).with_name('native_worker.py'),remote+'/worker.py',folder,'stage-worker')
                invoke.write_text('python3 '+shlex.quote(remote+'/worker.py')+' '+shlex.quote(remote)+'\n',encoding='utf-8')
                state['status']='submitted';dump(statefile,state)
                command('& '+psquote(FLEET/'mac.ps1')+' -File '+psquote(invoke)+'\nexit $LASTEXITCODE\n',folder,'execute')
                transfer('get',remote+'/result.json',folder/'result.json',folder,'fetch')
                state['status']='finished';dump(statefile,state)
            except Exception:
                state['status']='unknown';dump(statefile,state);raise
        import hashlib
        result=json.loads((folder/'result.json').read_text())
        if result['request_sha256']!=hashlib.sha256(payload.read_bytes()).hexdigest():raise RuntimeError('Native result is for a different input')
        assert result['runtimes_unchanged']
        out={};taskmap={t['id']:(t,p) for t,p in items}
        for row in result['results']:
            task,program=taskmap[row['id']];rows=row['engines']
            if any(r['status']!='executed' for r in rows):
                out[row['id']]=dict(answer='ABSTAIN',state='execution_error',backend=self.name,native=True,engines=rows);continue
            if program['operation']=='rules':
                if len(rows)!=6 or len({tuple(r['known']) for r in rows})!=1:raise RuntimeError('Native engine disagreement')
                compiled=lower(program);all_known=set(rows[0]['known'])
                if all_known!=closure(compiled)[0]:raise RuntimeError('Native/compiled reference closure disagreement')
                known=all_known & {n['id'] for n in program['nodes']};expected,witness=closure(program)
                if known!=expected:raise RuntimeError('Native/reference closure disagreement')
                out[row['id']]=dict(**resolve(task,program,known),known=sorted(known),witnesses=witness,backend=self.name,native=True,engines=rows,compilation=compiled['compilation'])
            else:
                value=rows[0]['response']['value']
                value=str(value).replace('$','').replace(',','')
                answer=format_number(value,task['policy']['unit'])
                expected=reference_execute(task,program)['answer']
                if answer!=expected:raise RuntimeError('Native/reference arithmetic disagreement')
                out[row['id']]=dict(answer=answer,state='calculated',backend=self.name,native=True,engines=rows)
        if set(out)!=set(taskmap):raise RuntimeError('Native result coverage differs')
        return out

    def recover(self,folder):
        folder=Path(folder).resolve();state=json.loads((folder/'state.json').read_text())
        transfer('get',state['remote']+'/result.json',folder/'result.json',folder,'recover-fetch')
        state['status']='fetched_for_reconciliation';dump(folder/'state.json',state)
        return state

