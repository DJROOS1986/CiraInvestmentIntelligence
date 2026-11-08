# CIRA Phase 5 safe one-time readiness and completion audit
# PowerShell 5.1+; no Azure writes, no job starts, no Terraform apply.
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Join-Path $env:USERPROFILE 'CiraInvestmentIntelligence'),
    [switch]$SkipAzure
)
$ErrorActionPreference = 'Stop'
$script:Checks = [System.Collections.Generic.List[object]]::new()
$script:Root = $ProjectRoot
$script:Python = $null
$script:Evidence = @{}
function Add-Check([string]$Name,[string]$Status,[string]$Detail) {
    $script:Checks.Add([pscustomobject]@{ Check=$Name; Status=$Status; Detail=$Detail })
    $color = switch ($Status) { 'PASS' {'Green'} 'FAIL' {'Red'} default {'Yellow'} }
    Write-Host ('[{0}] {1}: {2}' -f $Status,$Name,$Detail) -ForegroundColor $color
}
function Invoke-External([string]$File,[string[]]$Arguments) {
    $previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $output = & $File @Arguments 2>&1 | Out-String
}
finally {
    $ErrorActionPreference = $previousPreference
}
    return [pscustomobject]@{ ExitCode=$LASTEXITCODE; Output=$output.Trim() }
}
function Test-File([string]$Relative,[bool]$Required=$true) {
    $exists = Test-Path -LiteralPath (Join-Path $script:Root $Relative) -PathType Leaf
    if ($exists) { Add-Check "File: $Relative" 'PASS' 'Present' }
    elseif ($Required) { Add-Check "File: $Relative" 'FAIL' 'Missing' }
    else { Add-Check "File: $Relative" 'WARN' 'Optional file missing' }
    return $exists
}
if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) { throw "Project not found: $ProjectRoot" }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$script:Root = $ProjectRoot
$ReportDir = Join-Path $ProjectRoot 'audit-reports'
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$ReportPath = Join-Path $ReportDir "phase5-completion-$stamp.json"
Write-Host "`nCIRA PHASE 5 - SAFE ONE-TIME AUDIT" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"
Write-Host 'No cloud deployments, uploads, pipeline starts, or Terraform changes.'
Push-Location $ProjectRoot
try {
    $required = @(
        'ingestion/market_data.py',
        'portfolio-engine/market_analytics.py',
        'portfolio-engine/company_intelligence.py',
        'scripts/13-Ingest-Market-Prices.py',
        'scripts/14-Analyze-Market-Prices.py',
        'scripts/15-Build-Company-Intelligence.py',
        'scripts/16-Refresh-Company-Intelligence.py',
        'scripts/17-Run-Phase5-Pipeline.py',
        'scripts/18-Run-Phase5-Cloud.py',
        'scripts/19-Build-Publishing-Manifest.py',
        'scripts/20-Publish-Versioned-Reports.py',
        'scripts/21-Validate-Data-Freshness.py',
        'scripts/22-Test-Shared-Run-ID.py',
        'tests/test_market_data.py',
        'tests/test_market_analytics.py',
        'tests/test_company_intelligence.py',
        'tests/test_bcg_integration.py'
    )
    foreach ($file in $required) { [void](Test-File $file) }
    $pythonCandidates = @((Join-Path $ProjectRoot '.venv/Scripts/python.exe'))
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $pythonCandidates += $cmd.Source }
    foreach ($candidate in $pythonCandidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        $test = Invoke-External $candidate @('--version')
        if ($test.ExitCode -eq 0) { $script:Python = $candidate; Add-Check 'Python' 'PASS' $test.Output; break }
    }
    if (-not $script:Python) { Add-Check 'Python' 'FAIL' 'Python interpreter not found' }
    else {
        # Compile sources in memory (no __pycache__ files).
        $compileCode = @'
import ast, pathlib, sys
root = pathlib.Path(sys.argv[1]); paths = [root/'ingestion', root/'portfolio-engine', root/'scripts', root/'tests']
files = [p for folder in paths if folder.exists() for p in folder.rglob('*.py') if '.venv' not in p.parts]
errors = []
for p in files:
    try: ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p))
    except Exception as e: errors.append(f'{p.relative_to(root)}: {e}')
print(f'Parsed {len(files)} Python files; errors={len(errors)}')
for err in errors[:20]: print(err)
sys.exit(1 if errors else 0)
'@
        $syntax = Invoke-External $script:Python @('-c',$compileCode,$ProjectRoot)
        Add-Check 'Python syntax' $(if ($syntax.ExitCode -eq 0) {'PASS'} else {'FAIL'}) $syntax.Output
        $pytest = Invoke-External $script:Python @('-m','pytest','-q','tests')
        $pytestOutput = $pytest.Output
        if ($pytestOutput.Length -gt 2400) { $pytestOutput = $pytestOutput.Substring($pytestOutput.Length-2400) }
        Add-Check 'Unit tests' $(if ($pytest.ExitCode -eq 0) {'PASS'} else {'FAIL'}) $pytestOutput
        if (Test-Path 'scripts/21-Validate-Data-Freshness.py') {
            $freshness = Invoke-External $script:Python @('scripts/21-Validate-Data-Freshness.py','--source-root',$ProjectRoot)
            $freshnessText = $freshness.Output
            if ($freshnessText.Length -gt 2400) { $freshnessText = $freshnessText.Substring($freshnessText.Length-2400) }
            Add-Check 'Freshness validator' $(if ($freshness.ExitCode -eq 0) {'PASS'} else {'FAIL'}) $freshnessText
        }
    }
    foreach ($ticker in @('AAPL','MSFT')) {
        foreach ($pair in @(
            @{Type='Market data'; Relative="reports/market-data/$ticker-daily-prices.json"},
            @{Type='Market analysis'; Relative="reports/market-analysis/$ticker-market-analysis.json"},
            @{Type='Company intelligence'; Relative="reports/company-intelligence/$ticker-company-intelligence.json"}
        )) {
            $rel = $pair.Relative
            $path = Join-Path $ProjectRoot $rel
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
                Add-Check "$ticker $($pair.Type)" 'FAIL' "Missing: $rel"; continue
            }
            try {
                $raw = [System.IO.File]::ReadAllText($path)
                $null = ConvertFrom-Json -InputObject $raw -ErrorAction Stop
                $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
                Add-Check "$ticker $($pair.Type)" 'PASS' "Valid JSON; SHA256=$hash"
            }
            catch { Add-Check "$ticker $($pair.Type)" 'FAIL' "Invalid JSON: $($_.Exception.Message)" }
        }
    }
    $runIdFiles = @('reports/company-intelligence/AAPL-company-intelligence.json','reports/company-intelligence/MSFT-company-intelligence.json')
    $ids = @()
    foreach ($relative in $runIdFiles) {
        $path = Join-Path $ProjectRoot $relative
        if (-not (Test-Path $path -PathType Leaf)) { continue }
        try {
            $obj = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
            $id = $null
            foreach ($key in @('run_id','pipeline_run_id')) {
                if ($obj.PSObject.Properties.Name -contains $key) { $id = [string]$obj.$key; break }
            }
            if (-not $id) { Add-Check "Shared run ID: $relative" 'WARN' 'No top-level run_id or pipeline_run_id found' }
            else { $ids += $id; Add-Check "Shared run ID: $relative" 'PASS' $id }
        } catch { Add-Check "Shared run ID: $relative" 'FAIL' $_.Exception.Message }
    }
    if ($ids.Count -eq 2 -and $ids[0] -ne $ids[1]) { Add-Check 'Cross-report run ID' 'FAIL' 'AAPL and MSFT run IDs differ' }
    elseif ($ids.Count -eq 2) { Add-Check 'Cross-report run ID' 'PASS' 'Matching run IDs' }
    else { Add-Check 'Cross-report run ID' 'WARN' 'Not verified across both reports' }
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $git = Invoke-External 'git' @('status','--porcelain')
        if ($git.ExitCode -eq 0) { Add-Check 'Git status' 'PASS' $(if ($git.Output) {'Changes exist (not modified by audit)'} else {'Clean before audit report'}) }
        else { Add-Check 'Git status' 'WARN' $git.Output }
    }
    if (-not $SkipAzure) {
        if (-not (Get-Command az -ErrorAction SilentlyContinue)) { Add-Check 'Azure CLI' 'WARN' 'Azure CLI unavailable' }
        else {
            $sub = Invoke-External 'az' @('account','show','--query','id','-o','tsv')
            if ($sub.ExitCode -ne 0) { Add-Check 'Azure authentication' 'WARN' $sub.Output }
            else {
                Add-Check 'Azure authentication' 'PASS' "Subscription $($sub.Output)"
                $job = Invoke-External 'az' @('containerapp','job','show','-n','caj-cira-dev','-g','rg-cira-dev','--query','{image:properties.template.containers[0].image,trigger:properties.configuration.triggerType}','-o','json')
                Add-Check 'Deployed job configuration' $(if ($job.ExitCode -eq 0) {'PASS'} else {'WARN'}) $job.Output
                $blobs = Invoke-External 'az' @('storage','blob','list','--account-name','stciradeva2pjnb','--container-name','reports','--auth-mode','login','--prefix','financial-intelligence/','--query','[].{name:name,modified:properties.lastModified}','-o','json')
                Add-Check 'Cloud report listing' $(if ($blobs.ExitCode -eq 0) {'PASS'} else {'WARN'}) $(if ($blobs.Output.Length -gt 2400) {$blobs.Output.Substring(0,2400)} else {$blobs.Output})
            }
        }
    }
    # These are production release gates, not claims that the features are absent.
    Add-Check 'Phase 5 production publishing' 'WARN' 'Not verified: live versioned publish, manifest-last, safe pointer/discovery, concurrency control and rollback/recovery'
    Add-Check 'Data provenance' 'WARN' 'Yahoo Finance prototype and BCG research are not independently validated for production investment use'
    Add-Check 'Phase 5 deployed integration' 'WARN' 'Deployed job may still run Phase 4 v2; Phase 5 cloud integration is not established by local tests'
}
finally { Pop-Location }
$fail = @($script:Checks | Where-Object Status -eq 'FAIL').Count
$warn = @($script:Checks | Where-Object Status -eq 'WARN').Count
$pass = @($script:Checks | Where-Object Status -eq 'PASS').Count
$status = if ($fail -gt 0) {'INCOMPLETE'} elseif ($warn -gt 0) {'NOT PRODUCTION COMPLETE'} else {'COMPLETE'}
$report = [ordered]@{
    project = 'CiraInvestmentIntelligence'; phase='5'; generated_utc=[DateTime]::UtcNow.ToString('o')
    status=$status; summary=@{passed=$pass;failed=$fail;warnings=$warn}
    constraints=@('No Azure writes','No Terraform apply','No scheduled job starts','No publishing')
    checks=@($script:Checks.ToArray())
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Host "`nPHASE 5 RESULT: $status" -ForegroundColor $(if ($status -eq 'COMPLETE') {'Green'} else {'Yellow'})
Write-Host "PASS=$pass FAIL=$fail WARN=$warn"
Write-Host "Report: $ReportPath"
Write-Host 'This audit does not deploy or auto-fix Phase 5.'
