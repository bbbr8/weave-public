"""Resume only a positively identified pre-execution staging failure."""
import hashlib
import json
from pathlib import Path
import shlex
import time
from .native import FLEET,command,dump,psquote,transfer

def resume_staging(folder):
    folder=Path(folder).resolve();state=json.loads((folder/'state.json').read_text());remote=state['remote']
    if (folder/'execute.ps1').exists() or (folder/'resume-execute.ps1').exists():
        raise RuntimeError('Execution may already have started. Use recover-native to fetch its existing result; staging resume will not relaunch it.')
    request=folder/'request.json'
    expected=hashlib.sha256(request.read_bytes()).hexdigest()
    probe=folder/'resume-probe.sh'
    probe.write_text("python3 - <<'PY'\nfrom pathlib import Path\nimport json,hashlib\np=Path("+repr(remote)+")\nprint(json.dumps({'result':(p/'result.json').exists(),'request_sha256':hashlib.sha256((p/'request.json').read_bytes()).hexdigest() if (p/'request.json').exists() else None}))\nPY\n")
    command('& '+psquote(FLEET/'mac.ps1')+' -File '+psquote(probe)+'\nexit $LASTEXITCODE\n',folder,'resume-probe')
    observed=json.loads((folder/'resume-probe.stdout.txt').read_text().strip())
    if observed['request_sha256'] not in [None,expected]:raise RuntimeError('Remote request differs; preserve identity and reconcile')
    if not observed['result']:
        transfer('put',request,remote+'/request.json',folder,'resume-stage-input')
        worker=folder/'worker.snapshot.py'
        if not worker.exists():worker=Path(__file__).with_name('native_worker.py')
        transfer('put',worker,remote+'/worker.py',folder,'resume-stage-worker')
        job=folder/'resume-existing.sh';job.write_text('python3 '+shlex.quote(remote+'/worker.py')+' '+shlex.quote(remote)+'\n')
        state['status']='resume_submitted';dump(folder/'state.json',state)
        command('& '+psquote(FLEET/'mac.ps1')+' -File '+psquote(job)+'\nexit $LASTEXITCODE\n',folder,'resume-execute')
    transfer('get',remote+'/result.json',folder/'result.json',folder,'resume-fetch')
    result=json.loads((folder/'result.json').read_text())
    if result['request_sha256']!=expected:raise RuntimeError('Fetched result differs from original request')
    state.update(status='finished_reconciled',reconciliation=dict(at=time.time(),remote_preserved=True,probe=observed))
    dump(folder/'state.json',state)
    return state
