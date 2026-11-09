# Isolation and Safety Design

## Proposed sandbox layout (not created)

```
cira_phase58_sandbox/
  runner/                    # reviewed copy of hardened runner and helper
  cira_phase58_hardened/     # configuration adjacent to runner if required
  cira_phase57/              # signed mock orchestrator only
  monitoring/
    history/                 # mock snapshots only
    logs/                    # mock runner logs and lock only
  fixtures/                  # signed mock behavior fixtures
  evidence/                  # hashes, process IDs, and test results
  manifest.json              # files created by the harness
```

## Mandatory gates
1. Resolve every path to an absolute canonical path and confirm it is inside the disposable sandbox before any write or deletion; reject reparse points and symlink escapes.
2. Never invoke the real `cira_phase57/Invoke-CIRA-Phase57.ps1` or its Python scripts. Mock only.
3. Sign the mock orchestrator and any new PowerShell test scripts locally using the CIRA development certificate; never export the private key.
4. Keep `enabled=false`, `allow_azure_operations=false`, and `allow_promotion_recovery=false`. No scheduler APIs or task registration.
5. Test with a separate process group/Job Object. Kill and wait for mock descendants on timeout and interruption.
6. Snapshot and hash selected real project sentinel files before/after tests; do not read secrets or export private data.
7. Cleanup only manifest-listed sandbox files, after verifying the sandbox path and owner; no recursive deletion of the real project or monitoring history.
8. No `-ExecutionPolicy Bypass`, no Git writes, no Azure login, no real collection.
9. If isolation assumptions cannot be met, STOP rather than modify the real runner.

## Timeouts
The approved configuration remains 120 seconds. A shortened timeout for testing must be achieved with a dedicated isolated test harness or a review-approved test seam; never silently alter the production configuration.

## Rollback
No real runner changes are allowed. A failed test leaves sandbox evidence for review; cleanup requires confirmation and must be restricted to manifest-owned paths.
