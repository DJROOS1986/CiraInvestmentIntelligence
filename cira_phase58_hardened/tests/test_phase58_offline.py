import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PS = (ROOT / 'Invoke-CIRA-Phase58.ps1').read_text(encoding='utf-8')
CS = (ROOT / 'Phase58Process.cs').read_text(encoding='utf-8')
CFG = json.loads((ROOT / 'phase58-config.json').read_text(encoding='utf-8'))

class HardenedContractTests(unittest.TestCase):
    def test_approved_configuration(self):
        self.assertEqual(CFG, dict(phase='5.8', enabled=False, frequency='daily', local_time='09:00', operation='collect', timeout_seconds=120, log_retention_days=30, run_if_missed=False, allow_overlapping_runs=False, allow_azure_operations=False, allow_promotion_recovery=False))
    def test_explicit_manual_gate(self):
        self.assertIn('if (-not $Run)', PS)
        self.assertIn('return\n}', PS)
    def test_signature_checks(self):
        self.assertIn('Get-AuthenticodeSignature -LiteralPath $Orchestrator', PS)
        self.assertIn('Get-AuthenticodeSignature -LiteralPath $PSCommandPath', PS)
    def test_job_object_cleanup(self):
        for token in ('CreateJobObject','AssignProcessToJobObject','JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE','TerminateJobObject','CloseHandle'):
            self.assertIn(token, CS)
    def test_async_bounded_output(self):
        for token in ('BeginOutputReadLine','BeginErrorReadLine','captured.Length < 8192','WaitForExit(timeoutMs)'):
            self.assertIn(token, CS)
    def test_logging_and_health_separation(self):
        for token in ('execution_status=$status','health_status=$health',"$snapshot.overall_status",'CreateNew'):
            self.assertIn(token, PS)
    def test_lock_and_retention_scope(self):
        for token in ('[IO.FileShare]::None','phase58.lock',"'cira-run-*.json'",'Assert-SafePath $_.FullName'):
            self.assertIn(token, PS)
        self.assertNotIn('monitoring\\history\\*', PS)
    def test_no_scheduling_or_policy_bypass(self):
        for forbidden in ('Register-ScheduledTask','New-ScheduledTask','schtasks.exe','ExecutionPolicy Bypass','git commit','az login'):
            self.assertNotIn(forbidden.lower(), PS.lower())
    def test_test_fixture_is_offline(self):
        self.assertNotIn('subprocess', PS.lower())

if __name__ == '__main__': unittest.main()
