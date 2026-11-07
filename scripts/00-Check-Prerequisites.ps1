$ErrorActionPreference = 'Stop'
foreach ($name in @('terraform','az')) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "Missing $name. Install it before continuing." }
}
terraform version
az version --output json | ConvertFrom-Json | Select-Object -ExpandProperty 'azure-cli'
