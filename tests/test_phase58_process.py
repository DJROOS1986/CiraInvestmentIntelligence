"""Windows integration tests for bounded output and process containment."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows job objects')
HELPER = Path(__file__).resolve().parents[1] / 'cira_phase58_hardened_v2/Phase58Process.cs'


def run_child(code, timeout=5000):
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"
    arguments = subprocess.list2cmdline(['-c', code])
    command = (
        "$ErrorActionPreference='Stop'; "
        f"Add-Type -TypeDefinition ([IO.File]::ReadAllText({literal(HELPER)})); "
        f"$r=[Phase58Process]::Run({literal(sys.executable)},{literal(arguments)},{timeout}); "
        '$r | ConvertTo-Json -Compress'
    )
    completed = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True, text=True, timeout=25, check=True,
    )
    return json.loads(completed.stdout)


def test_success_output():
    result = run_child("print('collection-ok')")
    assert result['Status'] == 'PASS', result
    assert result['Output'].strip() == 'collection-ok'


def test_nonzero_exit_preserved():
    result = run_child('import sys; print("failed"); sys.exit(23)')
    assert (result['Status'], result['ExitCode']) == ('FAIL', 23), result


def test_timeout_is_bounded():
    result = run_child('import time; time.sleep(30)', timeout=300)
    assert (result['Status'], result['ExitCode']) == ('TIMEOUT', 124), result
    assert result['DurationMs'] < 8000


@pytest.mark.parametrize('stream,limit', [('stdout', 1100000), ('stderr', 10000)])
def test_output_limit_rejected_without_deadlock(stream, limit):
    result = run_child(f'import sys; sys.{stream}.write("x"*{limit})')
    assert result['Status'] == 'FAIL', result
    assert 'exceeded character limit' in result['Detail']


def test_empty_success_rejected():
    result = run_child('pass')
    assert result['Status'] == 'FAIL', result
    assert 'empty collection output' in result['Detail']


def test_descendant_holding_pipe_cannot_hang_runner(tmp_path):
    pidfile = tmp_path / 'descendant.pid'
    child = 'import time; time.sleep(30)'
    code = (
        'import subprocess,sys,pathlib; '
        f'p=subprocess.Popen([sys.executable,"-c",{child!r}]); '
        f'pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); '
        'print("parent-exited")'
    )
    result = run_child(code)
    assert result['Status'] == 'FAIL', result
    assert 'drain deadline' in result['Detail']
    pid = int(pidfile.read_text())
    process = subprocess.run(
        ['powershell.exe', '-NoProfile', '-Command',
         f'Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id'],
        capture_output=True, text=True, timeout=10,
    )
    assert not process.stdout.strip(), 'Descendant survived job closure'
