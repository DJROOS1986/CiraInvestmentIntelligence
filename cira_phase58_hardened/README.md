# CIRA Phase 5.8 — Hardened runner candidate (design / validation only)

Configuration is fixed to the approved daily 09:00 local / collect / 120 seconds / 30 days / disabled profile. **No Windows scheduled task is created or enabled.** No Git, Azure, promotion or recovery calls are present. The existing Phase 5.7 scripts and history are not modified by installation.

## Files

- `Invoke-CIRA-Phase58.ps1`: candidate replacement runner; no-argument mode is read-only dry run. `-Run` collects one snapshot and writes one execution log (DO NOT USE until runtime acceptance and separate approval).
- `Phase58Process.cs`: Windows Job Object process helper, asynchronous stdout/stderr draining, bounded 8192-character capture, process exit and timeout classifications.
- `phase58-config.json`: exact approved configuration.
- `Test-CIRA-Phase58-Process.ps1`: synthetic Windows process tests; starts only harmless PowerShell fixtures, no CIRA monitoring.
- `tests/test_phase58_offline.py`: static contract tests (not Windows runtime proof).

## Install and sign

Download ZIP into `C:\Users\45298\CiraInvestmentIntelligence` (your chosen location). Unzip to a **new staging folder** `cira_phase58_hardened`; do not overwrite the installed `cira_phase58` directory. Inspect the files before signing. Use the existing CIRA Development Code Signing certificate on your PC; the private key cannot be accessed by the assistant. Sign BOTH `.ps1` files using `Set-AuthenticodeSignature -HashAlgorithm SHA256`, then verify `Get-AuthenticodeSignature` returns `Valid`.

Offline tests: `.\.venv\Scripts\python.exe -m unittest discover -s .\cira_phase58_hardened\tests -v`.

Dry run: `& .\cira_phase58_hardened\Invoke-CIRA-Phase58.ps1` (no changes).

Synthetic Windows tests: `& .\cira_phase58_hardened\Test-CIRA-Phase58-Process.ps1` (spawns harmless fixture processes, no CIRA monitoring).

Do not run `-Run` until Windows process tests and a review of the candidate pass. This package is **not an automatic scheduler**.

## Security notes and limitations

The helper starts a child process then immediately assigns it to a Windows Job Object configured with `KILL_ON_JOB_CLOSE`. There is a **small race between start and assignment**; absolute containment from process creation would require a suspended-start implementation. If assignment fails, the helper fails closed and attempts to kill the immediate child. Nested-job restrictions on some Windows hosts may cause assignment failure; this is an explicit test target.

Captured output is limited to 8192 characters in memory but event handlers continue draining the pipes. Diagnostic output is **not** written into logs to reduce exposure of sensitive data. A malformed/truncated JSON response is treated as collection validation failure. The runner logs `execution_status` separately from `health_status`; health `WARN` or `FAIL` does not initiate recovery. Logs are created only for explicit manual `-Run`; old matching runner-owned logs can be pruned after validation, never monitoring history.

Only structural tests have been run in the authoring environment; actual Windows Job Object behavior and Authenticode signing must be tested on your PC. There is no scheduled-task registration or enabling code.
