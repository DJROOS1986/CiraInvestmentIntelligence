<#
.SYNOPSIS
    Read-only security baseline for CIRA: network exposure, private endpoints, keys vs managed identity.

.DESCRIPTION
    Reads ARM properties of every CIRA resource and compares them with the hardened target.
    Each check is tagged with the hardening phase that would close it:
        A = identity hardening (no network rebuild, ~no cost)
        B = private networking (VNet, private endpoints, new Container Apps environment)
        C = optional, costly (ACR Premium private endpoint, VPN)
    Status: OK / GAP / ? (property not returned; Azure default applies or access denied)

    Changes nothing.

.EXAMPLE
    .\scripts\38-Security-Baseline.ps1
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = 'rg-cira-dev',
    [string]$Storage       = 'stciradeva2pjnb',
    [string]$KeyVault      = 'kv-cira-dev-a2pjnb',
    [string]$Registry      = 'acrciradeva2pjnb',
    [string]$AiAccount     = 'ai-cira-dev-a2pjnb',
    [string]$Environment   = 'cae-cira-dev',
    [string]$Dashboard     = 'ca-cira-dashboard-dev',
    [string]$Workspace     = 'law-cira-dev'
)

$ErrorActionPreference = 'Continue'

function Get-Res([string]$Rg, [string]$Name, [string]$Type) {
    $json = az resource show -g $Rg -n $Name --resource-type $Type -o json 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $json) { return $null }
    return ($json -join "`n" | ConvertFrom-Json)
}

function Get-Prop($Obj, [string]$Path) {
    foreach ($part in $Path.Split('.')) {
        if ($null -eq $Obj) { return $null }
        $Obj = $Obj.$part
    }
    return $Obj
}

$rows = New-Object System.Collections.Generic.List[object]
function Add-Check([string]$Res, [string]$Setting, $Value, [string]$Target, [string]$Phase, [string]$Default = '') {
    $shown = $Value
    if ($null -eq $Value -and $Default) { $shown = "$Default (Azure default)" }
    if ($null -eq $Value -and -not $Default) { $shown = '(not returned)' }
    $effective = $Value
    if ($null -eq $Value -and $Default) { $effective = $Default }
    $status = '?'
    if ($null -ne $effective) { $status = 'GAP' }
    if ($null -ne $effective -and "$effective" -eq $Target) { $status = 'OK' }
    $rows.Add([pscustomobject]@{ Phase = $Phase; Status = $status; Resource = $Res; Setting = $Setting; Value = "$shown"; Target = $Target })
}

function Get-PeCount($Obj) { return @(Get-Prop $Obj 'properties.privateEndpointConnections' | Where-Object { $_ }).Count }

# Phase B target (option 1): firewall default Deny + admin IP allowlist; workloads via private endpoint.
function Test-StorageAccount([string]$Rg, [string]$Name, [string]$Label, [bool]$NeedsPe = $true) {
    $s = Get-Res $Rg $Name 'Microsoft.Storage/storageAccounts'
    if (-not $s) { Add-Check $Label 'resource readable' $null 'yes' 'A'; return }
    Add-Check $Label 'allowSharedKeyAccess'          (Get-Prop $s 'properties.allowSharedKeyAccess')       'False'    'A' 'True'
    Add-Check $Label 'allowBlobPublicAccess'         (Get-Prop $s 'properties.allowBlobPublicAccess')      'False'    'A'
    Add-Check $Label 'minimumTlsVersion'             (Get-Prop $s 'properties.minimumTlsVersion')          'TLS1_2'   'A'
    Add-Check $Label 'networkAcls.defaultAction'     (Get-Prop $s 'properties.networkAcls.defaultAction')  'Deny'     'B' 'Allow'
    if ($NeedsPe) { Add-Check $Label 'private endpoints (count >= 1)' ([int]((Get-PeCount $s) -ge 1)) '1' 'B' }
}

Write-Host 'Reading resource properties (read-only)...' -ForegroundColor Cyan

Test-StorageAccount $ResourceGroup $Storage "storage $Storage"

$backend = 'infrastructure/terraform/backend.hcl'
if (Test-Path -LiteralPath $backend) {
    $b = Get-Content -LiteralPath $backend -Raw
    $sa = [regex]::Match($b, '(?m)^\s*storage_account_name\s*=\s*"([^"]+)"').Groups[1].Value
    $rg = [regex]::Match($b, '(?m)^\s*resource_group_name\s*=\s*"([^"]+)"').Groups[1].Value
    $aad = [regex]::Match($b, '(?m)^\s*use_azuread_auth\s*=\s*(\w+)').Groups[1].Value
    if ($sa -and $rg) { Test-StorageAccount $rg $sa "tfstate $sa" $false }
    Add-Check 'terraform backend' 'use_azuread_auth' $(if ($aad) { $aad } else { $null }) 'true' 'A' 'false'
}

$kv = Get-Res $ResourceGroup $KeyVault 'Microsoft.KeyVault/vaults'
Add-Check "keyvault $KeyVault" 'enableRbacAuthorization' (Get-Prop $kv 'properties.enableRbacAuthorization') 'True' 'A' 'False'
Add-Check "keyvault $KeyVault" 'enablePurgeProtection'   (Get-Prop $kv 'properties.enablePurgeProtection')   'True' 'A' 'False'
Add-Check "keyvault $KeyVault" 'networkAcls.defaultAction' (Get-Prop $kv 'properties.networkAcls.defaultAction') 'Deny' 'B' 'Allow'
Add-Check "keyvault $KeyVault" 'private endpoints (count >= 1)' ([int]((Get-PeCount $kv) -ge 1)) '1' 'B'

$acr = Get-Res $ResourceGroup $Registry 'Microsoft.ContainerRegistry/registries'
Add-Check "acr $Registry" 'adminUserEnabled'    (Get-Prop $acr 'properties.adminUserEnabled')    'False' 'A' 'False'
Add-Check "acr $Registry" 'anonymousPullEnabled' (Get-Prop $acr 'properties.anonymousPullEnabled') 'False' 'A' 'False'
Add-Check "acr $Registry" 'sku (Premium needed for private endpoint)' (Get-Prop $acr 'sku.name') 'Premium' 'C'
Add-Check "acr $Registry" 'publicNetworkAccess' (Get-Prop $acr 'properties.publicNetworkAccess') 'Disabled' 'C' 'Enabled'

$ai = Get-Res $ResourceGroup $AiAccount 'Microsoft.CognitiveServices/accounts'
Add-Check "ai $AiAccount" 'disableLocalAuth (keyless)' (Get-Prop $ai 'properties.disableLocalAuth') 'True' 'A' 'False'
Add-Check "ai $AiAccount" 'networkAcls.defaultAction'  (Get-Prop $ai 'properties.networkAcls.defaultAction') 'Deny' 'B' 'Allow'
Add-Check "ai $AiAccount" 'private endpoints (count >= 1)' ([int]((Get-PeCount $ai) -ge 1)) '1' 'B'

$env = Get-Res $ResourceGroup $Environment 'Microsoft.App/managedEnvironments'
$vnet = Get-Prop $env 'properties.vnetConfiguration.infrastructureSubnetId'
Add-Check "env $Environment" 'VNet-integrated (subnet set)' ([string][bool]$vnet) 'True' 'B' 'False'

$app = Get-Res $ResourceGroup $Dashboard 'Microsoft.App/containerApps'
$external = Get-Prop $app 'properties.configuration.ingress.external'
Write-Host "Dashboard ingress external: $external (public URL; protect with Entra ID sign-in)"
$authJson = az containerapp auth show -n $Dashboard -g $ResourceGroup -o json 2>$null
$authOn = $null
if ($LASTEXITCODE -eq 0 -and $authJson) { $authOn = Get-Prop ($authJson -join "`n" | ConvertFrom-Json) 'platform.enabled' }
Add-Check "app $Dashboard" 'Entra ID sign-in (built-in auth)' $authOn 'True' 'A' 'False'

$law = Get-Res $ResourceGroup $Workspace 'Microsoft.OperationalInsights/workspaces'
Add-Check "law $Workspace" 'publicNetworkAccessForQuery (info)' (Get-Prop $law 'properties.publicNetworkAccessForQuery') 'Disabled' 'C' 'Enabled'

$rows | Sort-Object Phase, @{ Expression = { @('GAP', '?', 'OK').IndexOf($_.Status) } }, Resource |
    Format-Table Phase, Status, Resource, Setting, Value, Target -AutoSize -Wrap

foreach ($p in 'A', 'B', 'C') {
    $set = @($rows | Where-Object Phase -eq $p)
    Write-Host ("Phase {0}: {1} OK, {2} GAP, {3} unknown" -f $p,
        @($set | Where-Object Status -eq 'OK').Count, @($set | Where-Object Status -eq 'GAP').Count, @($set | Where-Object Status -eq '?').Count)
}
Write-Host "`nRead-only. Nothing was changed." -ForegroundColor Yellow
