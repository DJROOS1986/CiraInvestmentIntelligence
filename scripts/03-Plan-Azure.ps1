param([ValidateSet('dev','prod')][string]$Environment='dev')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Push-Location (Join-Path $root 'infrastructure/terraform')
try {
  $file="environments/$Environment.tfvars"
  if (-not (Test-Path $file)) { throw "Create $file from $file.example and review IDs." }
  terraform validate
  if ($LASTEXITCODE -ne 0) { throw 'Terraform validation failed.' }
  terraform plan -var-file=$file -out="$Environment.tfplan"
  if ($LASTEXITCODE -ne 0) { throw 'Terraform plan failed.' }
} finally { Pop-Location }
