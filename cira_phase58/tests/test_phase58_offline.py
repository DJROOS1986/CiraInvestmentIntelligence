"""Offline design-contract tests. Does not execute PowerShell or touch the CIRA project."""
import json
import pathlib
import unittest

BASE = pathlib.Path(__file__).resolve().parents[1]
EXPECTED = {
    'phase': '5.8', 'enabled': False, 'frequency': 'daily',
    'local_time': '09:00', 'operation': 'collect', 'timeout_seconds': 120,
    'log_retention_days': 30, 'run_if_missed': False,
    'allow_overlapping_runs': False, 'allow_azure_operations': False,
    'allow_promotion_recovery': False,
}

class Phase58OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((BASE / 'phase58-config.json').read_text(encoding='utf-8'))
        cls.script = (BASE / 'Invoke-CIRA-Phase58.ps1').read_text(encoding='utf-8')

    def test_exact_approved_configuration(self):
        self.assertEqual(self.config, EXPECTED)

    def test_explicit_manual_execution_gate(self):
        self.assertIn('[switch]$Run', self.script)
        self.assertIn('if (-not $Run)', self.script)
        self.assertIn('return\n}', self.script)

    def test_existing_orchestrator_is_signature_checked(self):
        self.assertIn('Get-AuthenticodeSignature', self.script)
        self.assertIn("$signature.Status -ne 'Valid'", self.script)

    def test_lock_timeout_and_exit_code(self):
        self.assertIn('[IO.FileShare]::None', self.script)
        self.assertIn('WaitForExit(120000)', self.script)
        self.assertIn('$process.ExitCode', self.script)

    def test_log_scope(self):
        self.assertIn("'cira-run-*.json'", self.script)
        self.assertIn("Join-Path $Monitoring 'logs'", self.script)
        self.assertIn('AddDays(-30)', self.script)

    def test_no_scheduler_registration_or_policy_bypass(self):
        lowered = self.script.lower()
        for forbidden in ('register-scheduledtask', 'schtasks.exe', 'new-scheduledtask',
                          'executionpolicy bypass', 'az login', 'terraform apply',
                          'git commit'):
            self.assertNotIn(forbidden, lowered)

if __name__ == '__main__':
    unittest.main()
