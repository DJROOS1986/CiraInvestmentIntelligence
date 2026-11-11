# CIRA Investment Intelligence — Handover

**Last updated:** 10 November 2026, ~23:15 Danish time
**Supersedes:** handover of 10 November 2026 (morning)
**Repo:** `C:\Users\45298\CiraInvestmentIntelligence` (Windows, PowerShell 5.1, VS Code, Python `.venv`)
**HEAD at handover:** `0714903` on `main` (local only, not pushed)

Every statement below is marked by how it is known:
**[verified]** = checked with a command or test during the session · **[inferred]** = strong evidence, not directly proven · **[open]** = not yet checked

---

## 1. Rules for any AI assistant working on CIRA

1. **Inspect before modifying.** The Git repo is the source of truth; this document is context, not a substitute for reading current files.
2. One step (or one small coherent set of commands) at a time. Wait for the real output before continuing.
3. **All Terraform changes go through `infrastructure/terraform/Invoke-CIRA-Terraform.ps1`.** Run it without switches to plan; with `-Apply` to apply after typing `APPLY`. Never run `terraform apply` directly.
4. **Never change Terraform-managed resources with `az ... update`.** That is how the theme drift happened (section 9). Change the `.tf` file instead.
5. Never deploy, delete Azure resources, rotate credentials, commit or push without explicit approval. State-changing scripts use typed confirmations (`APPLY`, `IMPORT`, `ARCHIVE`, `REMOVE`) — case-sensitive by design.
6. No `else` in new PowerShell. Use guard clauses and independent conditions.
7. Do not modify working financial calculations without a demonstrated, tested defect.
8. Never expose the dashboard access key, tokens, credentials or personal data in logs or chat.
9. A successful Azure job is not proof of financial correctness.
10. Never invent function names, Terraform arguments, API endpoints or CLI flags. If unsure, say so and validate (`terraform validate`, `--help`).
11. Do not create backup copies, `-v2`, `(1)`, `.candidate`, or phase folders in the repo root. Archive outside the repo (`..\CiraInvestmentIntelligence_archive\`).

### PowerShell 5.1 pitfalls seen in this project
- Native commands (`az`, `git`) lose embedded double quotes inside single-quoted arguments. Use double-quoted strings with single quotes inside, or avoid inner quotes.
- `$ErrorActionPreference = 'Stop'` + `2>&1` on a native command turns the first stderr line into a terminating error. Use `cmd /c "... 2>&1"` instead.
- `git diff` opens a pager; use `git --no-pager ...`. Pressing `s` in the pager saves to a file.
- Scripts must be run as files (`.\path\script.ps1`), not pasted — `$PSScriptRoot` is empty when pasted.
- Files downloaded by the browser land in the **repo root**; move them, then `Unblock-File`.

---

## 2. Purpose and safeguards (unchanged)

Personal, research-only investment intelligence for one long-term investor (USD 10–50k, no leverage).
No trading, no broker orders, no buy/sell recommendations. AI explains; deterministic code calculates.
Saxo is the intended read-only portfolio source of record (not yet integrated).

---

## 3. Current status

| Area | Status |
|---|---|
| Terraform state vs Azure | **In sync** — plan shows no changes [verified] |
| Terraform state lock | Released (stale lock from interrupted apply on 9 Nov) [verified] |
| Research pipeline (Container Apps Job) | Running twice daily, all executions succeeded [verified] |
| Failure alerting | **Live**: 2 log alert rules, enabled [verified]; test email **[open]** |
| AI model deployment | **Live**, smoke-tested with Entra ID auth [verified] |
| Dashboard | AI image + dark theme, healthy, latest batch loads [verified]; AI feature in UI **[open]** |
| Evening price timing | Was intraday; schedule moved to 22:30 [verified]; proof pending **[open]** |
| Repo root | Cleaned; tests 25/25 OK [verified] |
| Saxo integration | Not started |
| Production market data | Prototype only (Yahoo chart endpoint, unadjusted) |

---

## 4. Azure resources (`rg-cira-dev`, North Europe)

| Resource | Name | Managed by |
|---|---|---|
| Key Vault | `kv-cira-dev-a2pjnb` | Terraform |
| Storage / container | `stciradeva2pjnb` / `reports` (+ `raw-filings`) | Terraform |
| Log Analytics | `law-cira-dev` | Terraform |
| Container Registry | `acrciradeva2pjnb` | Terraform |
| Container Apps environment | `cae-cira-dev` | Terraform |
| Research job | `caj-cira-dev` | Terraform |
| Logic Apps | `logic-cira-daily-dev`, `logic-cira-evening-dev` | Terraform |
| Dashboard | `ca-cira-dashboard-dev` | Terraform |
| AI account | `ai-cira-dev-a2pjnb` (imported into state 10 Nov) | Terraform |
| AI deployment | `cira-research` | Terraform |
| Alert rules | `alert-cira-pipeline-failed-dev`, `alert-cira-pipeline-silent-dev` | Terraform |
| Action group | `ag-cira-failures-dev` (1 email receiver) | **Outside Terraform** — referenced as data source only |
| Budget | `budget-cira-dev` | Terraform |

---

## 5. Terraform

- Binary: `.tools/terraform-1.13.5/terraform.exe` (pinned). Provider `azurerm` **4.81.0** (`~> 4.0`) [verified].
- Remote state: `backend "azurerm"` with local `backend.hcl` (untracked); state blob `tfstate/cira/dev.tfstate` [verified].
- Variables: `environments/dev.tfvars` (contains `subscription_id`) and `phase3.dev.auto.tfvars`, both untracked. Neither overrides image tags [verified].
- Required env var: `TF_VAR_cira_sec_user_agent`, read from `ingestion/config.json` (the scripts set it automatically).
- **The state contains the dashboard access key in plain text** (`random_password.dashboard_access`). Treat state storage access as secret access.
- Scripts in `infrastructure/terraform/`:
  - `Invoke-CIRA-Terraform.ps1` — standard plan/apply gate. Plans to a temp file (deleted afterwards), lists changes, **blocks any delete/replace**, applies only after `APPLY`.
  - `Reconcile-CIRA-Drift.ps1` — one-off used on 10 Nov (theme blocks + AI import). Idempotent; safe to keep as reference.
  - `Complete-CIRA-Phase4.ps1` — original Phase 4 activation script; `scripts/Complete-CIRA-Phase4.ps1` is a wrapper that calls it.

---

## 6. Research pipeline

- Job image: `cira-financial-intelligence:research-20261110-724e313` [verified], built from **`Dockerfile.phase5`** at commit `724e313` with `scripts/37-Build-CIRA-Image.ps1`; test run succeeded 10 Nov 22:34 UTC [verified]. Every build is recorded in `docs/IMAGE-BUILDS.md`.
- Entry point: `scripts/12-Run-Cloud-Pipeline.py` (image CMD; job has no command override) [verified].
- Behaviour [verified by code reading]:
  - Any stage failure → `CIRA CLOUD PIPELINE FAILED: …` on stderr, exit code 1.
  - A complete versioned batch is published **only** after all stages succeed; then `CIRA CLOUD PIPELINE: SUCCESS` on stdout.
  - Stages 07 and 10 run via `runpy` **without** the `run_stage` wrapper (an early `sys.exit(0)` there would end the run "successfully" without publishing; the silent alert would catch it).
  - Expected reports for AAPL and MSFT are **hard-coded** (lines ~151–156). Must change when the universe grows.
- Console logs reach Log Analytics table `ContainerAppConsoleLogs_CL` (columns `Log_s`, `ContainerJobName_s`, `Stream_s`, `ContainerImage_s`) [verified].

### Schedules (time zone `Romance Standard Time` = Copenhagen, follows DST)

| Logic App | Trigger name | Actual time |
|---|---|---|
| `logic-cira-daily-dev` | `EveryDayAt0700` (misleading name) | **09:00** |
| `logic-cira-evening-dev` | `EveryDayAt2130` (misleading name) | **22:30** (changed 10 Nov) |

Do not rename the triggers: renaming would recreate them, and the gated script blocks replacements.
The Logic Apps only start the job; they do not check its outcome. Failure detection is done by the alert rules.

---

## 7. Monitoring and alerts

| Rule | Condition | Frequency / window | Severity |
|---|---|---|---|
| `alert-cira-pipeline-failed-dev` | `CIRA CLOUD PIPELINE FAILED` logged by `caj-cira-dev` | 15 min / 30 min | 1 |
| `alert-cira-pipeline-silent-dev` | no `CIRA CLOUD PIPELINE: SUCCESS` in last **15 h** | 1 h / 1 day (15 h filter in query) | 2 |

Both send to `ag-cira-failures-dev`. Both are stateful (auto-resolve). Defined in `infrastructure/terraform/monitoring_alerts.tf`.
Longest normal gap between successful runs is 13.5 h (09:00 → 22:30), so 15 h leaves margin.

**[open]** Send a test notification: Portal → Monitor → Alerts → Action groups → `ag-cira-failures-dev` → Test action group. Check spam folder.
**Decided 10 Nov:** Scheduled Task `CIRA-Daily-Monitoring` (runs `cira_phase58_hardened_v2/Invoke-CIRA-Phase58.ps1 -Run`) is **disabled**: it failed to start (0x800710E0), depended on the laptop, wrote into tracked `monitoring/history/`, and the wrapper itself states `-Run` is manual-only. Azure alerts are the primary detection; scripts 29-34 remain on-demand tools. `CIRA-Daily-Investment-Intelligence` (old local pipeline `scripts/11-Run-All.ps1`) stays disabled. Task XML backups are in the archive folder; undo with `Enable-ScheduledTask -TaskName CIRA-Daily-Monitoring`.

---

## 8. AI

- Account `ai-cira-dev-a2pjnb`, kind OpenAI, S0, `local_auth_enabled = false` (Entra ID only), public network access enabled [verified].
- Deployment `cira-research`: `gpt-5.4-mini` version `2026-03-17`, SKU `GlobalStandard`, capacity 1, auto-upgrade `OnceNewDefaultVersionAvailable` [verified]. Consider pinning the version for reproducible research.
- Role `Cognitive Services OpenAI User` for the dashboard identity and the developer [verified].
- Smoke test passed via `https://ai-cira-dev-a2pjnb.openai.azure.com/openai/v1/chat/completions` with an Entra token (21 tokens) [verified].
- AI must explain verified facts only; it must not produce figures or recommendations.

---

## 9. Dashboard

- Image `cira-dashboard:dashboard-ai-20261109`, revision `ca-cira-dashboard-dev--0000002`, running and ready, health `200 ok` [verified].
- 11 env vars in this order: `AZURE_CLIENT_ID`, `CIRA_STORAGE_ACCOUNT`, `CIRA_REPORTS_CONTAINER`, `CIRA_DASHBOARD_ACCESS_KEY` (secret ref), 5 × `STREAMLIT_THEME_*`, `CIRA_AI_ENDPOINT`, `CIRA_AI_DEPLOYMENT` [verified].
- **Env blocks are a positional list in Terraform.** Inserting in the middle shows as renames in the plan; append or keep the order.
- Theme is now defined in `dashboard.tf` (previously only set via CLI, which a Terraform apply would have removed).
- Rollback image if the AI build misbehaves: apply with `-var=cira_dashboard_image_tag=dashboard-20261109`.
- Access protection is an application-level key, not Entra ID sign-in. Move to Entra before any Saxo data is shown.
- URL: `https://ca-cira-dashboard-dev.lemonpebble-6d0d2f65.northeurope.azurecontainerapps.io`

---

## 10. Data quality

- **Intraday capture:** the old 21:30 run started 30 min before the US close (both summer and winter), so evening "latest close" values were intraday [verified for batch `20261110T203058Z-02f7eff8743e` by timing]. Schedule moved to 22:30, which is ≥30 min after the US close all year [verified in Azure].
- **Proven 10 Nov [verified]:** same-date closes differed between the 20:30 UTC batch and a post-close batch (AAPL 348.71 vs 348.51, MSFT 533.243 vs 533.16). Re-run `python scripts/35-Check-Price-Consistency.py` after 12 Nov: check 1 should list no new intraday batches.
- Market data is still the Yahoo chart endpoint (prototype, unadjusted prices). Not a verified production source.
- MSFT figures were reconciled against SEC Company Facts in an earlier session; AAPL figures have not been independently reconciled against the SEC filing.

---

## 11. Repository

- Root cleaned on 10 Nov. Removed items are archived outside the repo in `C:\Users\45298\CiraInvestmentIntelligence_archive\` (timestamped folders, with `manifest.csv` where applicable) and remain in Git history.
- Deliberately kept: `cira_phase58_hardened_v2/` (used by `scripts/33-…` and `tests/test_phase58_process.py`); ignored folders `.phase55-backups`, `.phase55-staging`, `audit-reports`.
- New scripts:
  - `scripts/35-Check-Price-Consistency.py` — read-only intraday/consistency check across all batches.
  - `scripts/36-Archive-Root-Leftovers.ps1` — report/archive/restore for root leftovers.
- **Tests:** run with
  `cmd /c "python -m unittest discover -s tests 2>&1"`
  (not `-t .` — `tests/` has no `__init__.py`). Result on 10 Nov: **25/25 OK** [verified].
- Line-ending warnings (LF → CRLF) on every add are harmless; a `.gitattributes` would silence them.

### Commits on 10 Nov (local, not pushed)
`b59cc56` reconcile drift · `f05640d` alerts + Terraform gate script · `98144e0` evening run 22:30 · `0de5dda` silent alert 15 h + price check · `e496a63` root cleanup + renumber · `59132b4` duplicate copies + phase58 drafts · `0714903` orphan Phase 4 script + stray recovery candidate

---

## 12. Backlog (priority order)

1. Intraday capture proven and fixed (10 Nov). Re-run `scripts/35-Check-Price-Consistency.py` after 12 Nov to confirm no new intraday batches.
2. **[open]** Send the action-group test email.
3. **[open]** Check the AI feature in the dashboard UI.
4. Done 10 Nov: local monitoring reviewed; daily Scheduled Task disabled (see section 7); scripts 29-34 kept as on-demand tools.
5. Done 10 Nov: builds via `scripts/37-Build-CIRA-Image.ps1`, recorded in `docs/IMAGE-BUILDS.md`. Follow-ups: pin base-image digest and package versions (rebuild pulled newer deps); add `.tools` to `.dockerignore` (159 MiB upload); check the `Dockerfile.phase5` step 21 `mkdir` line (market-data and market-analysis appear joined).
6. Wrap pipeline stages 07 and 10 in `run_stage`.
7. Replace the hard-coded AAPL/MSFT expected-file list before expanding the universe.
8. Python 3.10 → 3.12 in both Dockerfiles (3.10 is believed to have reached end of life in Oct 2026 — verify on python.org).
9. Decide whether to push to a remote for backup.
10. Later: Entra ID sign-in for the dashboard, licensed market data, Saxo read-only integration, AAPL SEC reconciliation.

---

## 13. How the next session should start

```powershell
git --no-pager status --short          # expect empty
git --no-pager log --oneline -8        # expect 0714903 at the top (or newer)
.\infrastructure\terraform\Invoke-CIRA-Terraform.ps1   # expect "No changes. Azure matches the code."
python scripts/35-Check-Price-Consistency.py           # data-quality status
```

If the Terraform check shows changes nobody intended, stop and investigate drift before doing anything else.

**Operating principle:** preserve what works, verify what is uncertain, change only what is necessary, test each change before continuing.

---

## 14. Security hardening (11 Nov 2026)

- **Phase A complete [verified]:** all data access is keyless (Storage and tfstate shared keys off, Terraform backend Entra auth, Key Vault RBAC + purge protection, ACR admin/anonymous pull off, AI local auth off). Dashboard behind **Entra ID sign-in**: app registration "CIRA Dashboard (dev)", assignment required, only Roland assigned, no client secret (providers `azuread` + `azapi`). The app-level access key is still active as a second layer.
- **Phase B option 1 complete [verified]:** `vnet-cira-dev` 10.40.0.0/16 (`snet-cae` /23 delegated to Microsoft.App/environments, `snet-pe` /24). Private endpoints + private DNS zones for blob, Key Vault and AI. Storage, Key Vault and AI firewalls **default Deny**, no Azure-services bypass, admin IP allowlist via `var.allowed_admin_ips` (untracked `dev.tfvars`). `cae-cira-dev` recreated VNet-integrated (old environment took ~20 min to delete). Job and dashboard both verified over the private path on 11 Nov.
- **Dashboard URL changed** to `https://ca-cira-dashboard-dev.lemonpebble-6d0d2f65.northeurope.azurecontainerapps.io`.
- **If the home IP changes:** run `scripts/39-Prepare-PhaseB.ps1` then `Invoke-CIRA-Terraform.ps1 -Apply` (workload firewalls), and `scripts/40-Harden-TfState-Network.ps1 -RemoveOtherIps` (state account).
- `Invoke-CIRA-Terraform.ps1` supports `-AllowReplace <address>,...`; every other delete/replace stays blocked.
- **Laptop has 7.9 GB RAM:** run Terraform outside VS Code (VS Code used ~2.6 GB; the azurerm provider once crashed out of memory during validate).
- **Terraform state account `stciratf74e50510` restricted [verified]:** default Deny, bypass None, admin IP rule only; set with `scripts/40-Harden-TfState-Network.ps1` (re-run after an IP change; `-RemoveOtherIps` drops old rules). A future GitHub Actions pipeline needs its own access path.
- `scripts/38-Security-Baseline.ps1` result: A 13/13, B 8/8, C 0/3.
- **Open:** remove the dashboard access key using Entra identity headers; run Terraform from GitHub Actions with OIDC; Phase C optional (ACR Premium private endpoint, Log Analytics private query).

---

## 15. Repository, CI, build hygiene and AI resilience (11 Nov 2026)

- **Remote:** private GitHub repo `DJROOS1986/CiraInvestmentIntelligence` (remote URL includes the username so Git Credential Manager uses the right account). History scanned before first push: no secrets; local-only files (`dev.tfvars`, `backend.hcl`, `.terraform`, `ingestion/config.json`, `.venv`, `.tools`) are ignored.
- **CI:** `.github/workflows/ci.yml` runs on every push (tests on Ubuntu + Windows, `terraform validate` without Azure access). Green [verified]. Real plans/applies stay local until a VNet self-hosted runner exists.
- **Dashboard sign-in:** accepts the Entra ID identity (`X-MS-CLIENT-PRINCIPAL-ID` must equal `CIRA_ALLOWED_PRINCIPAL_ID`); the access key is only a fallback. Planned: remove the key after a few days of stable sign-in.
- **Line endings:** `.gitattributes` (LF for code/config, CRLF for PowerShell/C#; `cira_phase58_hardened_v2/**` stored as exact bytes so its Authenticode signature survives a fresh clone).
- **Reproducible images:** base images pinned by digest; exact versions in `ingestion/constraints-research.txt` and `dashboard/constraints-dashboard.txt`; `scripts/37-Build-CIRA-Image.ps1` builds from a `git archive` of HEAD (~150 KiB upload). Build one image at a time: build, plan, apply, test, commit.
- **Quarterly task:** bump base-image digests and constraint versions deliberately (security patches no longer arrive automatically), rebuild, test, record.
- **AI highlights [verified 11 Nov]:** work end to end via the AI private endpoint (10.40.2.6) with the dashboard managed identity. Earlier "unavailable" errors were HTTP 429 (deployment capacity 1). Fix: capacity 10, one retry honouring Retry-After (max 20 s), and the dashboard now shows and logs the real reason (`describe_failure`). Diagnostics: `scripts/42-Diagnose-AI-Highlights.py`, `scripts/43-Reproduce-AI-With-Real-Report.py`; AI account metrics `TotalCalls/SuccessfulCalls/ClientErrors/BlockedCalls`.
- Tests: 38 (25 existing + 8 dashboard access + 5 AI resilience).
