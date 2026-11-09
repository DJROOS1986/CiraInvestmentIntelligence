# CIRA Phase 5.8 deployment — 2026-11-09

## Verified deployment

- Azure subscription and tenant matched the development Terraform inputs and personal account.
- Terraform refreshed the deployment and reported no changes. No apply was necessary.
- Azure workflows `logic-cira-daily-dev` and `logic-cira-evening-dev` were Enabled.
- Their recurrence configuration is 09:00 and 21:30, Romance Standard Time (Copenhagen).
- The latest morning and evening container job executions on November 9 succeeded.
- `CIRA-Daily-Monitoring` is registered for 09:00 local time with S4U and limited privileges. It can run while the user is logged out; the Windows computer must be on.
- The scheduled action enforces AllSigned, avoids overlapping runs, and has a three-minute scheduler execution limit. The helper timeout is 120 seconds plus bounded cleanup.
- A real monitoring collection and a scheduler-launched S4U collection succeeded, each reporting execution PASS and health PASS. Scheduler result was 0.
- The obsolete local `CIRA-Daily-Investment-Intelligence` pipeline task is disabled to avoid duplicating Azure ingestion.

## Implementation and validation

The existing final-cleanup C# candidate was installed as `Phase58Process.cs` with qualified thread-state handling and checked handle closure. Children start suspended, enter a kill-on-close job, then resume. Output capture and draining are bounded. The signed wrapper checks the helper's SHA-256 before loading it.

Seven Windows integration tests cover success, preserved nonzero exit, timeout, stdout/stderr overflow, empty output, and cleanup of a descendant retaining output pipes. The full test suite passed: 37 tests.

Both the Phase 5.7 orchestrator and changed Phase 5.8 wrapper were verified with valid Authenticode signatures using the existing CIRA Development Code Signing certificate. The administrative finalizer is also signed and verifies signatures before scheduling changes.

The empty local ingestion configuration was repaired from the existing example and deployed job settings. Temporary Terraform input files were removed after planning; saved plans remain Git-ignored.

## Scope and limits

This verifies the existing Azure financial pipeline and local monitoring automation. It does not certify the entire platform as production complete, report freshness, investment recommendation correctness, alert delivery, or live trading. Local monitoring checks local report presence and component integrity; it does not monitor Azure job freshness. No production report promotion or recovery was performed.

The Windows timezone was verified as Romance Standard Time. Missed local monitoring runs are not replayed. The next registered monitoring run was November 10 at 09:00 Copenhagen time. S4U execution was tested immediately; a future daily recurrence has not yet been observed.

For administrative task maintenance, use the signed `scripts/33-Finalize-CIRA-Monitoring.ps1` from an elevated Windows PowerShell session. It tests the S4U task before disabling the old pipeline task.
