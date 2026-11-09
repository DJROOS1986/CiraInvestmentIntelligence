# Proposed E2E Test Matrix

| ID | Scenario | Proposed setup | Expected result | Evidence |
|---|---|---|---|---|
| E2E-01 | Successful mock collection | Signed mock returns 0 and emits bounded output | PASS execution event | Sandbox JSON log, exit code |
| E2E-02 | Nonzero mock exit | Signed mock returns 23 | FAIL with original exit code 23 | Sandbox JSON log |
| E2E-03 | Timeout | Signed mock and descendant outlive configured test deadline | TIMEOUT 124; all sandbox child processes stopped | Process IDs before/after; log |
| E2E-04 | Concurrent attempts | Start two sandbox runner instances simultaneously | Only one acquires lock; second skips; no duplicate collection | Lock events, mock invocation count |
| E2E-05 | Large output | Mock writes stdout and stderr beyond pipe buffer | No deadlock; bounded capture and truncation indication | Bounded diagnostic metadata |
| E2E-06 | Unhealthy snapshot | Mock exits 0 but writes a WARN health snapshot | Execution PASS, health WARN (separate fields) | Execution log + mock history |
| E2E-07 | Expired runner log | Pre-seed sandbox-owned cira-run-*.json older than 30 days | Only eligible old runner logs removed | Before/after manifest |
| E2E-08 | Protected files | Pre-seed old unrelated JSON and mock history | Unrelated files and history unchanged | SHA-256 before/after |
| E2E-09 | Signature rejection | Mock orchestrator missing/invalid signature | Reject before launching mock | No invocation marker; failure output |
| E2E-10 | Forced interruption | Terminate test runner while mock spawns child | Lock recoverable; descendants terminated | Process inventory and subsequent run |

All cases must run only in an isolated disposable project tree. Test controller must record results and assert no writes outside the sandbox. A passing contract test alone is not evidence of E2E behavior.
