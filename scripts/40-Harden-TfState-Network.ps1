<#
.SYNOPSIS
    Restricts the Terraform STATE storage account to your current public IPv4, with an automatic
    lock-out test and rollback.

.DESCRIPTION
    The state account is managed outside the CIRA Terraform configuration (Terraform cannot manage
    the account that stores its own state), so this is done with az CLI.

    1. Reads the state account from infrastructure/terraform/backend.hcl.
    2. Detects your current public IPv4 (api.ipify.org). The IP is never printed.
    3. Shows the current firewall summary and asks you to type HARDEN.
    4. Adds your IP rule FIRST, then sets default action Deny and bypass None.
    5. Lock-out test: `terraform state list` must still read the state (retries for ~2 minutes
       while the firewall change propagates).
    6. If the test fails, it reverts the default action to Allow automatically.

    Re-run any time your home IP changes: firewall rules are control-plane operations, so this
    script works even when the data plane is blocked. Use -RemoveOtherIps to drop old IP rules.

    Note: a future GitHub Actions pipeline will need its own network access to the state account.

.EXAMPLE
    .\scripts\40-Harden-TfState-Network.ps1
.EXAMPLE
    .\scripts\40-Harden-TfState-Network.ps1 -RemoveOtherIps
#>
[CmdletBinding()]
param(
    [switch]$RemoveOtherIps
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Text) { Write-Host "`n=== $Text ===" -ForegroundColor Cyan }

function Get-Rules([string]$Name, [string]$Rg) {
    $json = az storage account show --name $Name --resource-group $Rg --query networkRuleSet -o json
    if ($LASTEXITCODE -ne 0) { throw "Cannot read network rules of $Name." }
    return ($json -join "`n" | ConvertFrom-Json)
}

function Show-Summary($Rules, [string]$Ip) {
    $ips = @($Rules.ipRules | ForEach-Object { $_.ipAddressOrRange })
    Write-Host ("Default action : {0}" -f $Rules.defaultAction)
    Write-Host ("Bypass         : {0}" -f $Rules.bypass)
    Write-Host ("IP rules       : {0} (your current IP included: {1})" -f $ips.Count, ($ips -contains $Ip))
}

function Test-StateAccess([string]$TfDir) {
    Push-Location $TfDir
    try {
        $tf = (Resolve-Path '../../.tools/terraform-1.13.5/terraform.exe').Path
        $out = @(& $tf state list 2>&1 | ForEach-Object { "$_" })
        return (($LASTEXITCODE -eq 0) -and ($out -contains 'azurerm_resource_group.main'))
    }
    finally { Pop-Location }
}

$top = git rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) { throw 'Not inside a Git repository.' }
$repo  = (Resolve-Path $top).Path
$tfDir = Join-Path $repo 'infrastructure/terraform'

Write-Step '1/5 Locate state account'
$backend = Join-Path $tfDir 'backend.hcl'
if (-not (Test-Path -LiteralPath $backend)) { throw 'backend.hcl not found.' }
$b  = Get-Content -LiteralPath $backend -Raw
$sa = [regex]::Match($b, '(?m)^\s*storage_account_name\s*=\s*"([^"]+)"').Groups[1].Value
$rg = [regex]::Match($b, '(?m)^\s*resource_group_name\s*=\s*"([^"]+)"').Groups[1].Value
if (-not $sa -or -not $rg) { throw 'storage_account_name or resource_group_name missing in backend.hcl.' }
$env:ARM_SUBSCRIPTION_ID = az account show --query id -o tsv
Write-Host "State account  : $sa  (resource group $rg)"

Write-Step '2/5 Detect public IPv4'
$ip = "$(Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 15)".Trim()
if ($ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { throw 'Could not detect a public IPv4 address. Nothing changed.' }
Write-Host 'Detected (not shown).'

Write-Step '3/5 Current firewall'
$before = Get-Rules $sa $rg
Show-Summary $before $ip
$alreadyDone = ($before.defaultAction -eq 'Deny') -and (@($before.ipRules | ForEach-Object { $_.ipAddressOrRange }) -contains $ip) -and -not $RemoveOtherIps
if ($alreadyDone) { Write-Host 'Already restricted to your current IP. Nothing to do.' -ForegroundColor Green; return }

Write-Host "`nPlan: add your IP rule, set default action Deny + bypass None, then test Terraform state access."
Write-Host 'If the test fails, default action is reverted to Allow automatically.'
if ($RemoveOtherIps) { Write-Host 'Also: remove all other IP rules.' -ForegroundColor Yellow }
if ((Read-Host 'Type HARDEN to continue (anything else cancels)') -cne 'HARDEN') { Write-Host 'Cancelled. Nothing changed.'; return }

Write-Step '4/5 Apply firewall'
$existing = @($before.ipRules | ForEach-Object { $_.ipAddressOrRange })
if ($existing -notcontains $ip) {
    az storage account network-rule add --account-name $sa --resource-group $rg --ip-address $ip --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Adding the IP rule failed. Default action unchanged.' }
    Write-Host 'IP rule added.'
}
if ($RemoveOtherIps) {
    foreach ($old in ($existing | Where-Object { $_ -ne $ip })) {
        az storage account network-rule remove --account-name $sa --resource-group $rg --ip-address $old --only-show-errors | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Warning 'Removing an old IP rule failed (continuing).' }
    }
    Write-Host 'Other IP rules removed.'
}
az storage account update --name $sa --resource-group $rg --default-action Deny --bypass None --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Setting default action Deny failed. IP rule may have been added; default unchanged.' }
Write-Host 'Default action Deny, bypass None.'

Write-Step '5/5 Lock-out test (terraform state list)'
$ok = $false
for ($i = 1; $i -le 4; $i++) {
    Start-Sleep -Seconds 30
    $ok = Test-StateAccess $tfDir
    Write-Host ("Attempt {0}/4: {1}" -f $i, $(if ($ok) { 'state readable' } else { 'not yet' }))
    if ($ok) { break }
}

if (-not $ok) {
    Write-Warning 'Terraform could not read its state through the firewall. Reverting default action to Allow.'
    az storage account update --name $sa --resource-group $rg --default-action Allow --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warning "REVERT FAILED. Run: az storage account update -n $sa -g $rg --default-action Allow" }
    Show-Summary (Get-Rules $sa $rg) $ip
    throw 'Hardening rolled back. Nothing is locked out.'
}

Show-Summary (Get-Rules $sa $rg) $ip
Write-Host "`nState account restricted to your IP; Terraform state access verified." -ForegroundColor Green
