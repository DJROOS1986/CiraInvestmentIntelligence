<#
.SYNOPSIS
    Plans, and optionally applies, CIRA Terraform changes behind safety gates.

.DESCRIPTION
    1. Checks the environment (config.json user agent, subscription matches dev.tfvars).
    2. Checks formatting (warning only) and validates the configuration.
    3. Plans to a temporary file OUTSIDE the repo. Plan files can contain secrets, so it is
       always deleted at the end.
    4. Lists every resource change and BLOCKS if anything would be deleted or replaced.
    5. With -Apply: asks you to type APPLY, then applies exactly the plan you just reviewed.

    Without -Apply nothing in Azure is changed. Never commits to Git.

.EXAMPLE
    .\infrastructure\terraform\Invoke-CIRA-Terraform.ps1              # plan only
.EXAMPLE
    .\infrastructure\terraform\Invoke-CIRA-Terraform.ps1 -Apply       # plan, review, typed approval, apply
.EXAMPLE
    .\infrastructure\terraform\Invoke-CIRA-Terraform.ps1 -Details     # also print the full plan text
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$Details
)

$ErrorActionPreference = 'Stop'
$tfDir = $PSScriptRoot
if (-not $tfDir) { $tfDir = (Get-Location).Path }
if (-not (Test-Path -LiteralPath (Join-Path $tfDir 'versions.tf'))) { throw "versions.tf not found in $tfDir. Run from infrastructure\terraform." }

$repoRoot = (Resolve-Path (Join-Path $tfDir '../..')).Path
$varFile  = 'environments/dev.tfvars'
$tfExe    = 'terraform'
$localTf  = Join-Path $repoRoot '.tools/terraform-1.13.5/terraform.exe'
if (Test-Path -LiteralPath $localTf) { $tfExe = (Resolve-Path $localTf).Path }
$planFile = Join-Path $env:TEMP ('cira-{0}.tfplan' -f [guid]::NewGuid().ToString('N'))

function Write-Step([string]$Text) { Write-Host "`n=== $Text ===" -ForegroundColor Cyan }

function Invoke-Tf([string[]]$Arguments) {
    & $tfExe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "terraform $($Arguments[0]) failed (exit $LASTEXITCODE)." }
}

Push-Location $tfDir
try {
    Write-Step '1/4 Environment'
    $cfg = Get-Content (Join-Path $repoRoot 'ingestion/config.json') -Raw | ConvertFrom-Json
    if (-not $cfg.sec_user_agent) { throw 'Missing sec_user_agent in ingestion/config.json.' }
    $env:TF_VAR_cira_sec_user_agent = $cfg.sec_user_agent

    $match = [regex]::Match((Get-Content $varFile -Raw), '(?m)^subscription_id\s*=\s*"([^"]+)"')
    if (-not $match.Success) { throw "Missing subscription_id in $varFile." }
    $current = az account show --query id -o tsv
    if ($current -ne $match.Groups[1].Value) { throw 'Azure CLI subscription does not match dev.tfvars. Run az account set first.' }
    $env:ARM_SUBSCRIPTION_ID = $current
    Write-Host "Terraform : $tfExe"
    Write-Host 'Subscription matches dev.tfvars.'

    Write-Step '2/4 Format and validate'
    & $tfExe fmt -check -recursive
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Formatting differences in the files listed above (style only, not blocking).' }
    Invoke-Tf @('validate', '-no-color')

    Write-Step '3/4 Plan (read-only)'
    $out = @(& $tfExe plan "-var-file=$varFile" -input=false -lock-timeout=5m -no-color "-out=$planFile")
    if ($LASTEXITCODE -ne 0) { $out | Select-Object -Last 40; throw 'terraform plan failed.' }
    if ($Details) { $out }

    Write-Step '4/4 Review'
    $json    = (& $tfExe show -json $planFile) -join "`n" | ConvertFrom-Json
    $changes = @($json.resource_changes | Where-Object { ($_.change.actions -join ',') -notin @('no-op', 'read') })
    if ($changes.Count -eq 0) { Write-Host 'No changes. Azure matches the code.' -ForegroundColor Green; return }

    $changes | ForEach-Object { '{0,-16} {1}' -f ($_.change.actions -join '+'), $_.address }
    $out | Where-Object { $_ -match '^Plan:' }

    $risky = @($changes | Where-Object { $_.change.actions -contains 'delete' })
    if ($risky.Count -gt 0) { Write-Warning "BLOCKED: plan deletes or replaces $($risky.Count) resource(s). Review with -Details; nothing applied."; return }
    if (-not $Apply) { Write-Host "`nPlan only, nothing applied. Re-run with -Apply to apply." -ForegroundColor Yellow; return }

    $answer = Read-Host 'Type APPLY to apply exactly the changes listed above (anything else cancels)'
    if ($answer -cne 'APPLY') { Write-Host 'Cancelled. Nothing applied.'; return }
    Invoke-Tf @('apply', '-input=false', '-lock-timeout=5m', '-no-color', $planFile)
    Write-Host "`nApply complete. Commit the .tf changes when you are satisfied." -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $planFile -ErrorAction SilentlyContinue
    Remove-Item Env:TF_VAR_cira_sec_user_agent -ErrorAction SilentlyContinue
    Pop-Location
}
