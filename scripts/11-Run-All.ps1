param()

$ErrorActionPreference = "Stop"

$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

$Pipeline = Join-Path $Root "scripts\08-Run-Cira-Pipeline.ps1"
$LogDir = Join-Path $Root "reports\logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Log = Join-Path $LogDir "automation-$Stamp.log"

try {
    Write-Host "Starting CIRA automation..." -ForegroundColor Cyan

    $Arguments = @(
        "-NoProfile"
        "-NonInteractive"
        "-ExecutionPolicy"
        "Bypass"
        "-File"
        $Pipeline
    )

    $Process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList $Arguments `
        -Wait `
        -PassThru `
        -NoNewWindow `
        -RedirectStandardOutput $Log

    if ($Process.ExitCode -ne 0) {
        throw "Pipeline failed with exit code $($Process.ExitCode)"
    }

    $Results = Get-Content $Log -Raw

    if ($Results -notmatch "PIPELINE STATUS: SUCCESS") {
        throw "Pipeline did not report success."
    }

    Write-Host "PIPELINE STATUS: SUCCESS" -ForegroundColor Green

    Write-Host "Running financial analysis..." -ForegroundColor Cyan

    $Python = Join-Path $Root ".venv\Scripts\python.exe"
    $Analysis = Join-Path $Root "scripts\10-Analyze-Financial-Reports.py"

    & $Python $Analysis

    if ($LASTEXITCODE -ne 0) {
        throw "Financial analysis failed with exit code $LASTEXITCODE"
    }

    Write-Host "FINANCIAL ANALYSIS: SUCCESS" -ForegroundColor Green
    Write-Host "CIRA automation completed." -ForegroundColor Green
    Write-Host "Execution log: $Log"
}
catch {
    Write-Host "AUTOMATION FAILED: $_" -ForegroundColor Red
    Write-Host "Review log: $Log"
    exit 1
}


