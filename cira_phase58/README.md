# CIRA Phase 5.8 — Design-only monitoring runner

## Scope

This package does **not** register or enable any scheduled task. Configuration `enabled=false` is intentional. It is a proposed daily 09:00 local schedule, not an active schedule. `-Run` is an explicit **manual** collection action, and is not part of offline testing.

## Files

- `phase58-config.json`: exact approved design settings
- `Invoke-CIRA-Phase58.ps1`: default read-only dry run; `-Run` manually invokes the signed Phase 5.7 orchestrator's `-Collect` mode, writes a metadata-only execution log, and applies 30-day retention to its own logs
- `tests/test_phase58_offline.py`: contract tests without PowerShell execution or project modifications

## Offline tests (safe on any machine with Python 3)

```powershell
python -m unittest discover -s .\cira_phase58\tests -v
```

## Installation and dry-run plan (not performed by this package)

1. Extract the `cira_phase58` folder into the CIRA project root. Review files first.
2. Run offline tests above.
3. Sign `Invoke-CIRA-Phase58.ps1` with your existing trusted CIRA code-signing certificate. Verify `Get-AuthenticodeSignature` reports `Valid`.
4. Run `& '.\cira_phase58\Invoke-CIRA-Phase58.ps1'` without switches. This validates configuration and Phase 5.7 signature without writing logs or snapshots.
5. A later **separate explicit approval** is required before running `-Run`, which writes a monitoring snapshot and a metadata log. Scheduling needs another separate approval.

## Operational notes

- The Phase 5.7 orchestrator is not modified.
- Run metadata logs contain status, exit code, UTC timestamp, duration, and a fixed generic detail. Child stdout/stderr are not logged to avoid exposing monitoring details.
- A non-overlap lock uses an exclusive file handle at `monitoring/logs/phase58.lock`. An abandoned lock file is harmless; an active handle prevents concurrency.
- The 120-second timeout terminates the PowerShell child process. On Windows PowerShell 5.1, terminating its descendant Python process is **not guaranteed**. Do not enable unattended scheduling until this is hardened and tested on Windows.
- The current runner treats child exit code 0 as a successful collection **process**, not necessarily an overall health PASS. Consult the validated Phase 5.7 history report for health status.
- Local start time is a design parameter; no scheduling logic is included. Missed runs are not replayed.
- Retention only applies to matching `cira-run-*.json` files in `monitoring/logs`; Phase 5.7 history is never pruned.
- The runner's current process capture is appropriate for the small JSON outputs of Phase 5.7, but should be hardened for unexpectedly large child output before unattended deployment.
