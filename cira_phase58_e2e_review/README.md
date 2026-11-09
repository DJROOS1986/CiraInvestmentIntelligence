# CIRA Phase 5.8 — Isolated E2E Test Package (REVIEW ONLY)

Status: DESIGN ONLY. No executable tests are included. No files in the user's Windows project are changed by preparing this package.

## Purpose
Review a proposed isolated end-to-end test of the staged hardened Phase 5.8 runner. This package is **not** approval to run, replace, sign, deploy, or schedule anything.

## Scope
- Target under review: `C:\Users\45298\CiraInvestmentIntelligence\cira_phase58_hardened`
- Proposed future sandbox: `C:\Users\45298\CiraInvestmentIntelligence\cira_phase58_sandbox`
- Real Phase 5.7 and Phase 5.8 files, monitoring history, and logs remain untouched.
- No Azure operations, Git commits, scheduler changes, production promotion, or recovery.

## Contents
- `TEST-MATRIX.md`: 10 planned scenarios and expected evidence.
- `ISOLATION-AND-SAFETY.md`: sandbox design, path and process controls, cleanup.
- `IMPLEMENTATION-REVIEW.md`: questions to resolve before creating executable tests.
- `APPROVAL-GATE.md`: explicit next-stage authorization boundary.

## Known status
- Existing staging: six required files found, both PowerShell scripts signed.
- Offline contract tests: 9/9 PASS.
- Synthetic Windows process tests: 6/6 PASS.
- Hardened runner dry run: PASS.
- Read-only signature and configuration audit: PASS.
- Full isolated E2E: NOT RUN.

## Note
A real E2E test will create and remove test files and start mock processes. It requires explicit authorization in a future turn.
