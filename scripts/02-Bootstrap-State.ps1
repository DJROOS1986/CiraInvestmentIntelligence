param([string]$Location='westeurope')
$ErrorActionPreference='Stop'
$tenant='b0c33ece-98f7-4f4d-bc31-8aad22f835c2'
$subscription='ff9cce9f-71fe-4f87-ae04-e106a1a6ffb1'
az login --tenant $tenant --use-device-code
if ($LASTEXITCODE -ne 0) { throw 'Azure login failed. Check Entra sign-in logs; do not bypass Conditional Access.' }
az account set --subscription $subscription
if ($LASTEXITCODE -ne 0) { throw 'Subscription selection failed.' }
$rg='rg-cira-tfstate'
$suffix=([guid]::NewGuid().ToString('N')).Substring(0,8)
$storage="stciratf$suffix"
az group create --name $rg --location $Location --output none
az storage account create --name $storage --resource-group $rg --location $Location --sku Standard_LRS --kind StorageV2 --allow-blob-public-access false --min-tls-version TLS1_2 --output none
az storage account update --name $storage --resource-group $rg --allow-shared-key-access false --output none
$me=az ad signed-in-user show --query id -o tsv
if (-not $me) { throw 'Could not resolve signed-in Entra user object ID.' }
$scope="/subscriptions/$subscription/resourceGroups/$rg/providers/Microsoft.Storage/storageAccounts/$storage"
az role assignment create --assignee-object-id $me --assignee-principal-type User --role 'Storage Blob Data Contributor' --scope $scope --output none
if ($LASTEXITCODE -ne 0) { throw 'Failed to grant state blob role. Check permissions.' }
Write-Host 'Allow a few minutes for RBAC propagation.'
az storage container create --name tfstate --account-name $storage --auth-mode login --output none
if ($LASTEXITCODE -ne 0) { throw 'Container creation failed. Retry after RBAC propagates.' }
$target=Join-Path (Split-Path $PSScriptRoot -Parent) 'infrastructure/terraform/backend.hcl'
@"
resource_group_name  = "$rg"
storage_account_name = "$storage"
container_name       = "tfstate"
key                  = "cira/dev.tfstate"
use_azuread_auth     = true
"@ | Set-Content -Path $target -Encoding utf8
Write-Host "Created remote state backend: $storage. Protect this resource group from deletion."
