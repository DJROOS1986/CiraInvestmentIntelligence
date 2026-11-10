# AGENTS.md - CIRA Investment Intelligence

Before doing anything in this repository, read `docs/CIRA-HANDOVER.md` completely.
Its section 1 (rules) is binding. Its section 13 lists the commands to start every session with.

Key rules in short:
- Inspect before modifying; the repo is the source of truth.
- All Terraform changes via `infrastructure/terraform/Invoke-CIRA-Terraform.ps1`; never `terraform apply` directly.
- Never change Terraform-managed Azure resources with `az ... update`.
- No deploy, delete, commit or push without explicit approval.
- No backup copies or versioned folders in the repo root.
- Never invent functions, Terraform arguments, endpoints or CLI flags; validate instead.
- No trading, no orders, no recommendations; AI explains, deterministic code calculates.
