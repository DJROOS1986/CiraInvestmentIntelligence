# Implementation Questions to Resolve Before Coding

1. **Runner path resolution:** Confirm where the staged runner reads `phase58-config.json` and `Phase58Process.cs`. The original runner locates the orchestrator under `ProjectRoot/cira_phase57`; the mock must satisfy the hardened runner's actual path assumptions.
2. **Job Object containment:** Determine whether child processes are created suspended or assigned immediately after launch. Document the race and whether descendant cleanup is guaranteed in tests.
3. **Logging schema:** Inspect the hardened runner's actual JSON fields before asserting health/execution separation; do not invent expected keys.
4. **Concurrency skip:** Determine whether skipped executions return an explicit status/exit code and whether a skip log is expected.
5. **Timeout test seam:** Confirm whether the helper permits an isolated timeout parameter. Avoid changing the approved 120-second configuration.
6. **Retention:** Verify exact filename filter, time comparison, path safety, and whether only runner-owned logs can be deleted.
7. **Interrupt behavior:** Confirm how Windows PowerShell and helper process termination propagate; specify evidence required to prove no orphan descendants.
8. **Signatures:** Ensure the sandbox mock and test scripts are locally signed and verify as Valid before execution.
9. **No writes outside sandbox:** Establish a before/after manifest and specific sentinel files, without claiming an exhaustive filesystem guarantee.
10. **Failure handling:** Preserve enough evidence on failure; do not automatically erase logs needed for diagnosis.

## Required inspection inputs
- Full contents of staged `Invoke-CIRA-Phase58.ps1` and `Phase58Process.cs` (excluding signature block if convenient).
- The synthetic test fixture's invocation and mock behaviors.
- Configuration file (already approved).

Executable test scripts should be authored only after the above are resolved and user explicitly approves preparing them.
