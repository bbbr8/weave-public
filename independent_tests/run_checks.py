"""Run existing suites separately from independent synthetic checks."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('--repo', required=True)
p.add_argument('--target', required=True, type=Path)
p.add_argument('--independent', action='store_true')
a = p.parse_args()
target = a.target.resolve()
py = sys.executable
if a.independent:
    commands = [[py, '-B', str(Path(__file__).with_name('checks.py')), str(target), a.repo]]
elif a.repo == 'loom-public':
    commands = [[py, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                [py, '-B', '-m', 'unittest', 'discover', '-s', 'runtime/tests', '-q'],
                ['node', '--check', 'web/app.js'], ['node', '--test', 'tests/workbench.test.cjs']]
elif a.repo == 'tally-public':
    commands = [[py, '-B', 'tally.py', '--selftest'], [py, '-B', 'verify_reference.py']]
elif a.repo == 'vein':
    commands = [[py, '-B', 'vein.py', '--selftest'], [py, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-q']]
else:
    commands = [[py, '-B', '-m', 'unittest', 'discover', '-q']]
failed = 0
for cmd in commands:
    print('RUN', ' '.join(cmd), flush=True)
    try:
        r = subprocess.run(cmd, cwd=target, timeout=180,
                           env=dict(os.environ, SURD_USAGE='0', TALLY_NO_EXPERIMENT_LOG='1'))
        failed += r.returncode != 0
    except (OSError, subprocess.TimeoutExpired) as e:
        print('ERROR', e, flush=True)
        failed += 1
print('COMMANDS', len(commands), 'FAILED', failed, flush=True)
raise SystemExit(bool(failed))
