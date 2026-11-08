param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
$Config = Join-Path $Root 'ingestion\config.json'
if (-not (Test-Path $Config)) { throw 'Missing ingestion/config.json. Copy config.example.json and set your SEC contact email.' }
$AzDirs = @("$env:ProgramFiles\Microsoft SDKs\Azure\CLI2\wbin", "${env:ProgramFiles(x86)}\Microsoft SDKs\Azure\CLI2\wbin")
$AzDir = $AzDirs | Where-Object { Test-Path (Join-Path $_ 'az.cmd') } | Select-Object -First 1
if ($AzDir) { $env:PATH = "$AzDir;$env:PATH" }
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    & py -3 -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed' }
}
& $Python -m pip install -r (Join-Path $Root 'ingestion\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
if (-not $DryRun) {
    $account = & az account show --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $account.id -ne 'ff9cce9f-71fe-4f87-ae04-e106a1a6ffb1' -or $account.tenantId -ne 'b0c33ece-98f7-4f4d-bc31-8aad22f835c2') {
        throw 'Incorrect Azure subscription or tenant; upload blocked.'
    }
}
$Args = @('ingestion/ingest_sec.py', '--config', 'ingestion/config.json')
if ($DryRun) { $Args += '--dry-run' }
& $Python @Args
if ($LASTEXITCODE -ne 0) { throw 'Ingestion failed. See error above.' }
Write-Host 'Ingestion completed successfully.' -ForegroundColor Green
