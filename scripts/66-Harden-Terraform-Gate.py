"""Harden the Terraform gate's review step (one-off, idempotent).

13 Nov 2026: `terraform show` crashed (out of memory); the gate read no plan, PowerShell turned the empty result
into one blank "change", and the gate still offered APPLY without having reviewed anything.
Now: (1) stop if `terraform show` fails or returns nothing, (2) ignore empty entries, and (3) the reviewed
create/update/delete counts must equal Terraform's own "Plan: X to add, Y to change, Z to destroy" line.
Usage (repo root): python scripts/66-Harden-Terraform-Gate.py
"""
import re
import sys
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "infrastructure" / "terraform" / "Invoke-CIRA-Terraform.ps1"
text = path.read_bytes().decode("utf-8")
if "Review mismatch" in text:
    print("Already applied.")
    sys.exit(0)
nl = "\r\n" if "\r\n" in text else "\n"
pattern = (r"(?m)^(?P<ind>[ \t]*)\$json\s*=\s*\(& \$tfExe show -json \$planFile\) -join \"`n\" \| ConvertFrom-Json[ \t]*\r?\n"
           r"[ \t]*\$changes = @\(\$json\.resource_changes \| Where-Object \{ \(\$_\.change\.actions -join ','\) -notin @\('no-op', 'read'\) \}\)[ \t]*(?=\r?\n)")
hits = list(re.finditer(pattern, text))
if len(hits) != 1:
    sys.exit(f"Review lines matched {len(hits)} times (expected 1). Nothing written.")
i = hits[0]["ind"]
new = [
    "$showOut = @(& $tfExe show -json $planFile)",
    "if ($LASTEXITCODE -ne 0 -or $showOut.Count -eq 0) { throw 'terraform show failed (often: out of memory - close VS Code and other programs). Nothing applied.' }",
    "try { $json = ($showOut -join \"`n\") | ConvertFrom-Json } catch { throw 'The plan could not be read as JSON. Nothing applied.' }",
    "if ($null -eq $json) { throw 'The plan could not be read. Nothing applied.' }",
    "$changes = @(@($json.resource_changes) | Where-Object { $null -ne $_ -and $_.address -and (($_.change.actions -join ',') -notin @('no-op', 'read')) })",
    "$planLine = @($out | Where-Object { $_ -match '^Plan: \\d+ to add, \\d+ to change, \\d+ to destroy' }) | Select-Object -First 1",
    "if ($planLine -match '^Plan: (\\d+) to add, (\\d+) to change, (\\d+) to destroy') {",
    "    $wantAdd = [int]$Matches[1]; $wantChange = [int]$Matches[2]; $wantDestroy = [int]$Matches[3]",
    "    $gotAdd = @($changes | Where-Object { $_.change.actions -contains 'create' }).Count",
    "    $gotChange = @($changes | Where-Object { $_.change.actions -contains 'update' }).Count",
    "    $gotDestroy = @($changes | Where-Object { $_.change.actions -contains 'delete' }).Count",
    "    if ($gotAdd -ne $wantAdd -or $gotChange -ne $wantChange -or $gotDestroy -ne $wantDestroy) {",
    "        throw \"Review mismatch: Terraform says '$planLine' but the review found $gotAdd add / $gotChange change / $gotDestroy destroy. Nothing applied.\"",
    "    }",
    "} elseif ($changes.Count -gt 0) { throw 'Changes found but no Plan summary line. Nothing applied.' }",
]
block = nl.join(i + line for line in new)
text = text[:hits[0].start()] + block + text[hits[0].end():]
path.write_bytes(text.encode("utf-8"))
print("Gate review hardened: stops if terraform show fails, and cross-checks against the Plan line.")
