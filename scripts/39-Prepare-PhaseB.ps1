<#
.SYNOPSIS
    Prepares Phase B (private network, option 1) and shows the plan. Never applies.

.DESCRIPTION
    1. Detects your current public IPv4 (api.ipify.org) and writes allowed_admin_ips into
       infrastructure/terraform/environments/dev.tfvars (adds it, or updates it if your IP changed).
       Re-run this script whenever your home IP changes; then apply the resulting in-place update.
    2. Adds variable "allowed_admin_ips" to variables.tf (once).
    3. Passes allowed_ips = var.allowed_admin_ips to the storage and keyvault modules in main.tf (once).
    4. Formats the Phase B files and runs Invoke-CIRA-Terraform.ps1 (plan only).

    The IP address is never printed.

.EXAMPLE
    .\scripts\39-Prepare-PhaseB.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$top = git rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) { throw 'Not inside a Git repository.' }
$repo  = (Resolve-Path $top).Path
$tfDir = Join-Path $repo 'infrastructure/terraform'

function Read-Text([string]$Path) { return [IO.File]::ReadAllText($Path) }
function Write-Text([string]$Path, [string]$Text) { [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false)) }
function Get-Nl([string]$Text) { if ($Text -match "`r`n") { return "`r`n" }; return "`n" }

foreach ($f in 'network.tf', 'ai.tf', 'phase3_cloud_automation.tf', 'modules/storage/main.tf', 'modules/keyvault/main.tf') {
    $p = Join-Path $tfDir $f
    if (-not (Test-Path -LiteralPath $p)) { throw "$f missing - extract CIRA-PhaseB.zip into the repo root first." }
}
if ((Read-Text (Join-Path $tfDir 'network.tf')) -notmatch 'azurerm_private_endpoint') { throw 'network.tf is not the Phase B version.' }

Write-Host "`n=== 1/4 Admin IP allowlist (dev.tfvars) ===" -ForegroundColor Cyan
$ip = "$(Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 15)".Trim()
if ($ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { throw 'Could not detect a public IPv4 address. Nothing changed.' }
$tfvars = Join-Path $tfDir 'environments/dev.tfvars'
$t  = Read-Text $tfvars
$nl = Get-Nl $t
$line = 'allowed_admin_ips = ["' + $ip + '"]'
$existing = [regex]::Match($t, '(?m)^allowed_admin_ips\s*=.*$')
if (-not $existing.Success) { Write-Text $tfvars ($t.TrimEnd() + $nl + $line + $nl); Write-Host 'Added allowed_admin_ips with your current public IPv4.' }
if ($existing.Success -and $existing.Value.Trim() -ne $line) { Write-Text $tfvars ($t.Replace($existing.Value, $line)); Write-Host 'Updated allowed_admin_ips: your public IPv4 has changed.' -ForegroundColor Yellow }
if ($existing.Success -and $existing.Value.Trim() -eq $line) { Write-Host 'allowed_admin_ips already matches your current public IPv4.' }

Write-Host "`n=== 2/4 variables.tf ===" -ForegroundColor Cyan
$vf = Join-Path $tfDir 'variables.tf'
$v  = Read-Text $vf
$nl = Get-Nl $v
if ($v -match 'variable "allowed_admin_ips"') { Write-Host 'Variable allowed_admin_ips already present.' }
if ($v -notmatch 'variable "allowed_admin_ips"') {
    $block = @(
        'variable "allowed_admin_ips" {',
        '  type        = list(string)',
        '  description = "Public IPv4 addresses (no CIDR suffix) allowed through the Storage, Key Vault and AI firewalls for management. Set in dev.tfvars."',
        '}'
    ) -join $nl
    Write-Text $vf ($v.TrimEnd() + $nl + $nl + $block + $nl)
    Write-Host 'Added variable allowed_admin_ips.'
}

Write-Host "`n=== 3/4 main.tf module wiring ===" -ForegroundColor Cyan
$mf = Join-Path $tfDir 'main.tf'
$m  = Read-Text $mf
$nl = Get-Nl $m
foreach ($mod in 'storage', 'keyvault') {
    $blk = [regex]::Match($m, '(?ms)^(module "' + $mod + '" \{.*?)^\}')
    if (-not $blk.Success) { throw "module `"$mod`" block not found in main.tf. Nothing further changed." }
    if ($blk.Value -match 'allowed_ips') { Write-Host "module $mod already wired."; continue }
    $m = $m.Remove($blk.Index, $blk.Length).Insert($blk.Index, $blk.Groups[1].Value + '  allowed_ips = var.allowed_admin_ips' + $nl + '}')
    Write-Host "module $mod now receives allowed_ips."
}
Write-Text $mf $m

Write-Host "`n=== 4/4 Format and plan ===" -ForegroundColor Cyan
Push-Location $tfDir
try {
    $tf = (Resolve-Path '../../.tools/terraform-1.13.5/terraform.exe').Path
    foreach ($f in 'main.tf', 'variables.tf', 'network.tf', 'ai.tf', 'phase3_cloud_automation.tf', 'modules/storage/main.tf', 'modules/keyvault/main.tf') {
        & $tf fmt $f | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "terraform fmt failed on $f" }
    }
}
finally { Pop-Location }

git --no-pager diff --stat
& (Join-Path $tfDir 'Invoke-CIRA-Terraform.ps1')
