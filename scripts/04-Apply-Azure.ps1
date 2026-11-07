param([ValidateSet('dev','prod')][string]$Environment='dev')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Push-Location (Join-Path $root 'infrastructure/terraform')
try {
  if (-not (Test-Path "$Environment.tfplan")) { throw 'Run 03-Plan-Azure.ps1 first.' }
  terraform apply "$Environment.tfplan"
  if ($LASTEXITCODE -ne 0) { throw 'Terraform apply failed.' }
} finally { Pop-Location }
