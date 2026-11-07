param([ValidateSet('dev','prod')][string]$Environment='dev')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location (Join-Path $root 'infrastructure/terraform')
if (-not (Test-Path 'backend.hcl')) { throw 'Copy backend.hcl.example to backend.hcl and configure remote state first. Run scripts/02-Bootstrap-State.ps1.' }
terraform init -backend-config=backend.hcl
terraform fmt -recursive
terraform validate
