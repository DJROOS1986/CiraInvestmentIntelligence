<#
.SYNOPSIS
    Reconciles known CIRA Terraform drift without deploying anything.

.DESCRIPTION
    1. Adds the Streamlit dark-theme env blocks to dashboard.tf (skipped if already present).
       They are inserted directly after CIRA_DASHBOARD_ACCESS_KEY so the order matches what is
       deployed today; this keeps the plan diff small (only the two AI variables are added).
    2. Formats and validates the Terraform configuration.
    3. Imports the existing AI account into Terraform state if it is missing (asks for confirmation).
    4. Runs a read-only terraform plan and prints a summary with safety checks.

    This script NEVER runs terraform apply, never deletes Azure resources and never commits to Git.
    Undo the file edit at any time with: git restore -- infrastructure/terraform/dashboard.tf

.EXAMPLE
    .\infrastructure\terraform\Reconcile-CIRA-Drift.ps1

.EXAMPLE
    .\infrastructure\terraform\Reconcile-CIRA-Drift.ps1 -SkipImport
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = 'rg-cira-dev',
    [string]$AiAccountName = 'ai-cira-dev-a2pjnb',
    [switch]$SkipImport
)

$ErrorActionPreference = 'Stop'
$tfDir    = $PSScriptRoot
if (-not $tfDir) { $tfDir = (Get-Location).Path }
if (-not (Test-Path -LiteralPath (Join-Path $tfDir 'dashboard.tf'))) { throw "dashboard.tf not found in $tfDir. Run from infrastructure\terraform." }
$repoRoot = (Resolve-Path (Join-Path $tfDir '../..')).Path
$varFile  = 'environments/dev.tfvars'

$tfExe   = 'terraform'
$localTf = Join-Path $repoRoot '.tools/terraform-1.13.5/terraform.exe'
if (Test-Path -LiteralPath $localTf) { $tfExe = (Resolve-Path $localTf).Path }

function Write-Step([string]$Text) { Write-Host "`n=== $Text ===" -ForegroundColor Cyan }

function Invoke-Tf([string[]]$Arguments) {
    & $tfExe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "terraform $($Arguments[0]) failed (exit $LASTEXITCODE)." }
}

function Add-ThemeBlocks {
    $path = Join-Path $tfDir 'dashboard.tf'
    $raw  = Get-Content -LiteralPath $path -Raw
    if ($raw -match 'STREAMLIT_THEME_BASE') { Write-Host 'Theme env blocks already present; no edit needed.'; return }

    $newline = "`n"
    if ($raw -match "`r`n") { $newline = "`r`n" }
    $lines = [System.Collections.Generic.List[string]]::new([string[]]($raw -split "\r?\n"))

    $anchor = @(0..($lines.Count - 1) | Where-Object { $lines[$_] -match 'name\s*=\s*"CIRA_DASHBOARD_ACCESS_KEY"' })
    if ($anchor.Count -ne 1) { throw "Expected one CIRA_DASHBOARD_ACCESS_KEY env block, found $($anchor.Count). No changes made." }

    $close = @(($anchor[0] + 1)..($lines.Count - 1) | Where-Object { $lines[$_] -match '^\s*\}\s*$' } | Select-Object -First 1)
    if ($close.Count -ne 1) { throw 'Closing brace of CIRA_DASHBOARD_ACCESS_KEY env block not found. No changes made.' }

    $indent = ([regex]::Match($lines[$close[0]], '^\s*')).Value
    $theme = [ordered]@{
        STREAMLIT_THEME_BASE                       = 'dark'
        STREAMLIT_THEME_PRIMARY_COLOR              = '#5eead4'
        STREAMLIT_THEME_BACKGROUND_COLOR           = '#0b1422'
        STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR = '#111f30'
        STREAMLIT_THEME_TEXT_COLOR                 = '#e5eaf2'
    }
    $block = foreach ($key in $theme.Keys) {
        "${indent}env {"
        "${indent}  name  = `"$key`""
        "${indent}  value = `"$($theme[$key])`""
        "${indent}}"
    }

    $lines.InsertRange($close[0] + 1, [string[]]$block)
    [System.IO.File]::WriteAllText($path, ($lines -join $newline), [System.Text.UTF8Encoding]::new($false))
    Write-Host "Inserted $($theme.Count) theme env blocks after line $($close[0] + 1) of dashboard.tf."
}

function Initialize-TfEnvironment {
    $cfg = Get-Content (Join-Path $repoRoot 'ingestion/config.json') -Raw | ConvertFrom-Json
    if (-not $cfg.sec_user_agent) { throw 'Missing sec_user_agent in ingestion/config.json.' }
    $env:TF_VAR_cira_sec_user_agent = $cfg.sec_user_agent

    $match = [regex]::Match((Get-Content (Join-Path $tfDir $varFile) -Raw), '(?m)^subscription_id\s*=\s*"([^"]+)"')
    if (-not $match.Success) { throw "Missing subscription_id in $varFile." }

    $current = az account show --query id -o tsv
    if ($current -ne $match.Groups[1].Value) { throw 'Azure CLI subscription does not match dev.tfvars. Run az account set first.' }

    $env:ARM_SUBSCRIPTION_ID = $current
    return $current
}

function Import-AiAccount([string]$SubscriptionId) {
    if ($SkipImport) { Write-Host 'Import skipped (-SkipImport).'; return }

    $stateList = @(& $tfExe state list)
    if ($LASTEXITCODE -ne 0) { throw 'terraform state list failed.' }
    if ($stateList -contains 'azurerm_cognitive_account.research') { Write-Host 'AI account already in Terraform state; no import needed.'; return }

    $null = az cognitiveservices account show --resource-group $ResourceGroup --name $AiAccountName --query id -o tsv
    if ($LASTEXITCODE -ne 0) { throw "AI account $AiAccountName not found in $ResourceGroup. Refusing to import." }

    $id = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.CognitiveServices/accounts/$AiAccountName"
    Write-Host "Will import into Terraform state:"
    Write-Host "  azurerm_cognitive_account.research  <-  $id"
    Write-Host 'This changes Terraform state only. No Azure resource is modified.'
    $answer = Read-Host 'Type IMPORT to continue (anything else skips)'
    if ($answer -cne 'IMPORT') { Write-Host 'Import skipped by user.'; return }

    Invoke-Tf @('import', "-var-file=$varFile", '-input=false', '-lock-timeout=5m', '-no-color', 'azurerm_cognitive_account.research', $id)
}

function Show-PlanSummary {
    $out = @(& $tfExe plan "-var-file=$varFile" -input=false -lock-timeout=5m -no-color)
    if ($LASTEXITCODE -ne 0) { $out | Select-Object -Last 30; throw 'terraform plan failed.' }

    $out | Where-Object { $_ -match '^\s*# \S+\.\S+ (will|must)|^\s*[+-]\s+(env|name\s*=)|^Plan:|No changes' }

    Write-Step 'Safety checks'
    $themeChanged = @($out | Where-Object { $_ -match '^\s*[-~]\s.*STREAMLIT_THEME' })
    $destructive  = @($out | Where-Object { $_ -match 'will be destroyed|must be replaced' })
    $aiAccountNew = @($out | Where-Object { $_ -match '# azurerm_cognitive_account\.research will be created' })

    if ($themeChanged.Count -gt 0) { Write-Warning 'Plan still changes STREAMLIT_THEME variables. Do NOT apply.' }
    if ($destructive.Count -gt 0)  { Write-Warning 'Plan destroys or replaces resources. Do NOT apply until reviewed.' }
    if ($aiAccountNew.Count -gt 0) { Write-Warning 'Plan wants to CREATE the AI account, which already exists. Import it first. Do NOT apply.' }
    if ($themeChanged.Count + $destructive.Count + $aiAccountNew.Count -eq 0) {
        Write-Host 'OK: theme preserved, AI account known to state, nothing destroyed or replaced.' -ForegroundColor Green
    }
}

Push-Location $tfDir
try {
    Write-Step '1/4 Dashboard theme in dashboard.tf'
    Add-ThemeBlocks

    Write-Step '2/4 Format and validate'
    $subscriptionId = Initialize-TfEnvironment
    & $tfExe fmt dashboard.tf | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'terraform fmt failed.' }
    Invoke-Tf @('validate', '-no-color')

    Write-Step '3/4 AI account in Terraform state'
    Import-AiAccount -SubscriptionId $subscriptionId

    Write-Step '4/4 Read-only plan'
    Show-PlanSummary

    Write-Step 'Local Git changes'
    git --no-pager diff --stat
    Write-Host "`nNothing was applied. Review the plan above before any terraform apply." -ForegroundColor Yellow
}
finally {
    Remove-Item Env:TF_VAR_cira_sec_user_agent -ErrorAction SilentlyContinue
    Pop-Location
}
