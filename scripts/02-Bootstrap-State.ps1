param(
    [string]$Location = "westeurope"
)

$ErrorActionPreference = "Stop"

$Tenant = "b0c33ece-98f7-4f4d-bc31-8aad22f835c2"
$Subscription = "ff9cce9f-71fe-4f87-ae04-e106a1a6ffb1"

$RG = "rg-cira-tfstate"
$Container = "tfstate"

function Invoke-Az {
    param([string[]]$Arguments)

    & az @Arguments

    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Arguments -join ' ')"
    }
}

# Verify personal Azure subscription
$Account = az account show -o json | ConvertFrom-Json

if ($LASTEXITCODE -ne 0 -or
    $Account.id -ne $Subscription -or
    $Account.tenantId -ne $Tenant) {
    throw "Incorrect Azure subscription or tenant."
}

Write-Host "Verified personal Azure subscription." -ForegroundColor Green

# Prevent duplicate backend creation
$RGExists = az group exists --name $RG -o tsv

if ($LASTEXITCODE -ne 0) {
    throw "Unable to check Terraform state resource group."
}

$Existing = $null

if ($RGExists -eq "true") {
    $Existing = az storage account list `
        --resource-group $RG `
        --query "[0].name" -o tsv

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Terraform state storage."
    }
}

if ($LASTEXITCODE -ne 0) {
    $Existing = $null
}

if ($Existing) {
    $Storage = $Existing
    Write-Host "Using existing storage account: $Storage"
}
else {
    $Suffix = ([guid]::NewGuid().ToString("N")).Substring(0,8)
    $Storage = "stciratf$Suffix"

    # Only create the resource group if it does not exist.
    # Existing resource groups retain their original location.
    if ($RGExists -ne "true") {
        Invoke-Az -Arguments @(
            "group", "create",
            "--name", $RG,
            "--location", $Location,
            "--output", "none"
        )
    }

    Invoke-Az -Arguments @(
        "storage", "account", "create",
        "--name", $Storage,
        "--resource-group", $RG,
        "--location", $Location,
        "--sku", "Standard_LRS",
        "--kind", "StorageV2",
        "--allow-blob-public-access", "false",
        "--min-tls-version", "TLS1_2",
        "--https-only", "true",
        "--output", "none"
    )
}

# Configure storage security
Invoke-Az -Arguments @(
    "storage", "account", "update",
    "--name", $Storage,
    "--resource-group", $RG,
    "--allow-shared-key-access", "false",
    "--output", "none"
)

Invoke-Az -Arguments @(
    "storage", "account", "blob-service-properties", "update",
    "--account-name", $Storage,
    "--resource-group", $RG,
    "--enable-versioning", "true",
    "--enable-delete-retention", "true",
    "--delete-retention-days", "14",
    "--enable-container-delete-retention", "true",
    "--container-delete-retention-days", "14",
    "--output", "none"
)

# Grant Entra-based blob access
$Me = az ad signed-in-user show --query id -o tsv

if ($LASTEXITCODE -ne 0 -or -not $Me) {
    throw "Could not resolve signed-in Entra user."
}

$Scope = "/subscriptions/$Subscription/resourceGroups/$RG/providers/Microsoft.Storage/storageAccounts/$Storage"

$RoleAssignments = @(az role assignment list `
    --assignee $Me `
    --scope $Scope `
    --role "Storage Blob Data Contributor" `
    --query "[].id" `
    --output tsv)

$RoleCount = @($RoleAssignments | Where-Object { $_ }).Count

if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect existing RBAC assignments."
}

if ([int]$RoleCount -eq 0) {
    Invoke-Az -Arguments @(
        "role", "assignment", "create",
        "--assignee-object-id", $Me,
        "--assignee-principal-type", "User",
        "--role", "Storage Blob Data Contributor",
        "--scope", $Scope,
        "--output", "none"
    )
}

# Create private state container
$Created = $false

for ($Attempt = 1; $Attempt -le 12; $Attempt++) {
    $null = az storage container create `
        --name $Container `
        --account-name $Storage `
        --auth-mode login `
        --public-access off `
        --output json 2>$null

    if ($LASTEXITCODE -eq 0) {
        $Created = $true
        break
    }

    Start-Sleep -Seconds 15
}

if (-not $Created) {
    throw "Container creation failed. Check RBAC propagation."
}

# Generate Terraform backend configuration
$Target = Join-Path (
    Split-Path $PSScriptRoot -Parent
) "infrastructure\terraform\backend.hcl"

@"
resource_group_name  = "$RG"
storage_account_name = "$Storage"
container_name       = "$Container"
key                  = "cira/dev.tfstate"
use_azuread_auth     = true
tenant_id            = "$Tenant"
subscription_id      = "$Subscription"
"@ | Set-Content -Path $Target -Encoding UTF8

Write-Host ""
Write-Host "Remote Terraform backend prepared." -ForegroundColor Green
Write-Host "Storage account: $Storage"
Write-Host "Resource group: $RG"
Write-Host "Container: $Container"
Write-Host "Backend file: $Target"
