# CIRA - instructions for Claude Code

Read AGENTS.md and docs/CIRA-HANDOVER.md before doing anything. They are the source of truth.

Non-negotiable rules:
- Inspect before changing. Explain the plan and wait for approval before any change to Azure, any commit or any push.
- Terraform ONLY via infrastructure\terraform\Invoke-CIRA-Terraform.ps1 (plan first; apply only after the user approves the listed changes). Never run terraform state commands without explicit approval.
- Images ONLY via scripts\37-Build-CIRA-Image.ps1. Commit the build record right after the apply. Never git restore a Terraform file after a build.
- Tests: python -m pytest tests -q (same as CI). CI must be green before any rollout.
- Rollout order when the company list changes: dashboard first, then research job, then a test run, then check the log for CIRA COMPANY FAILED.
- Secrets: never print, store or commit keys. EODHD/OpenFIGI keys only from environment variables. Never print the contents of dev.tfvars, backend.hcl or ingestion/config.json.
- Windows PowerShell 5.1: keep each file's line endings (CRLF/LF) as they are; never invent CLI flags - check --help first.
- Memory: close VS Code before Terraform plan/apply (terraform show has crashed out of memory).
- Research only: no orders, no broker access, no investment recommendations.
