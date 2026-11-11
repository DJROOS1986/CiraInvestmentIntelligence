#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Run,
    [string]$ProjectRoot = (Join-Path $env:USERPROFILE 'CiraInvestmentIntelligence')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-SafePath([string]$Path) {
    $p = [IO.Path]::GetFullPath($Path)
    while ($true) {
        if (Test-Path -LiteralPath $p) {
            $item = Get-Item -LiteralPath $p -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Reparse point rejected: $p" }
        }
        $parent = Split-Path -Path $p -Parent
        if (-not $parent -or $parent -eq $p) { break }
        $p = $parent
    }
}
function Assert-Config($c) {
    $expected = @('phase','enabled','frequency','local_time','operation','timeout_seconds','log_retention_days','run_if_missed','allow_overlapping_runs','allow_azure_operations','allow_promotion_recovery')
    $actual = @($c.PSObject.Properties.Name)
    if (@($actual | Where-Object { $_ -notin $expected }).Count -or @($expected | Where-Object { $_ -notin $actual }).Count) { throw 'Unexpected configuration fields.' }
    if ($c.phase -cne '5.8' -or $c.enabled -isnot [bool] -or
        $c.frequency -cne 'daily' -or $c.local_time -cne '09:00' -or $c.operation -cne 'collect' -or
        $c.timeout_seconds -isnot [int] -or $c.timeout_seconds -ne 120 -or
        $c.log_retention_days -isnot [int] -or $c.log_retention_days -ne 30 -or
        $c.run_if_missed -isnot [bool] -or $c.run_if_missed -or
        $c.allow_overlapping_runs -isnot [bool] -or $c.allow_overlapping_runs -or
        $c.allow_azure_operations -isnot [bool] -or $c.allow_azure_operations -or
        $c.allow_promotion_recovery -isnot [bool] -or $c.allow_promotion_recovery) { throw 'Configuration differs from approved safety profile.' }
}
function Save-ExecutionRecord([string]$status, [int]$exitCode, [int]$durationMs, [string]$detail, [string]$health) {
    $record = [ordered]@{
        phase='5.8'; event='manual_collection'; timestamp_utc=[DateTime]::UtcNow.ToString('o');
        execution_status=$status; exit_code=$exitCode; duration_ms=$durationMs;
        health_status=$health; detail=$detail
    }
    $json = ConvertTo-Json -InputObject $record -Compress
    $filename = 'cira-run-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ') + '-' + [guid]::NewGuid().ToString('N') + '.json'
    $destination = Join-Path $Logs $filename
    Assert-SafePath $destination
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($json)
    $stream = [IO.File]::Open($destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    Write-Host "Execution: $status; Health: $health; Exit: $exitCode"
}
function Prune-OwnLogs([int]$days) {
    $cutoff = [DateTime]::UtcNow.AddDays(-$days)
    Get-ChildItem -LiteralPath $Logs -Filter 'cira-run-*.json' -File | ForEach-Object {
        Assert-SafePath $_.FullName
        if ($_.LastWriteTimeUtc -ge $cutoff) { return }
        if ($_.Name -cnotmatch '^cira-run-\d{8}T\d{13}Z-[a-f0-9]{32}\.json$') { return }
        $record = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($record.phase -cne '5.8' -or $record.event -cne 'manual_collection') { return }
        Remove-Item -LiteralPath $_.FullName -Force
    }
}
$Root = [IO.Path]::GetFullPath($ProjectRoot)
$ConfigFile = Join-Path $PSScriptRoot 'phase58-config.json'
$Helper = Join-Path $PSScriptRoot 'Phase58Process.cs'
$ExpectedHelperHash = '88431765C2179854497A022681E8BB3730591B00FEF78E973AFC1340E5F31D06'
$Orchestrator = Join-Path $Root 'cira_phase57\Invoke-CIRA-Phase57.ps1'
$Monitoring = Join-Path $Root 'monitoring'
$Logs = Join-Path $Monitoring 'logs'
$LockFile = Join-Path $Logs 'phase58.lock'
foreach ($path in @($Root,$PSScriptRoot,$ConfigFile,$Helper,$Orchestrator,$Monitoring,$Logs,$LockFile)) { Assert-SafePath $path }
foreach ($file in @($ConfigFile,$Helper,$Orchestrator)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing file: $file" }
}
if (-not (Test-Path -LiteralPath $Root -PathType Container)) { throw 'Project root missing.' }
$config = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Config $config
if ((Get-FileHash -LiteralPath $Helper -Algorithm SHA256).Hash -ne $ExpectedHelperHash) { throw 'Process helper integrity mismatch.' }
if ((Get-AuthenticodeSignature -LiteralPath $Orchestrator).Status -ne 'Valid') { throw 'Phase 5.7 signature invalid.' }
if ((Get-AuthenticodeSignature -LiteralPath $PSCommandPath).Status -ne 'Valid') { throw 'Phase 5.8 signature invalid.' }
if (-not $Run) {
    Write-Host 'CIRA Phase 5.8 HARDENED DRY RUN - no files changed.'
    Write-Host "Daily 09:00 local; collect; 120s timeout; 30d log retention; enabled=$($config.enabled)."
    Write-Host 'No scheduler, monitoring collection, log writes or changes.'
    return
}
# -Run is manual-only. No task registration or schedule trigger is implemented.
if (-not (Test-Path -LiteralPath $Monitoring -PathType Container)) { throw 'Monitoring directory missing.' }
if (-not (Test-Path -LiteralPath $Logs -PathType Container)) { [void](New-Item -ItemType Directory -Path $Logs) }
Assert-SafePath $Logs
$lock = $null
try {
    try {
        $lock = [IO.File]::Open($LockFile, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] {
        Write-Host 'SKIP: another Phase 5.8 run owns the lock.'
        return
    }
    Add-Type -TypeDefinition ([IO.File]::ReadAllText($Helper)) -Language CSharp -ErrorAction Stop
    $shell = Join-Path $PSHOME 'powershell.exe'
    if (-not (Test-Path -LiteralPath $shell -PathType Leaf)) { throw 'Windows PowerShell executable missing.' }
    # Restrict quote injection in paths passed as process arguments.
    if ($Root.Contains('"') -or $Orchestrator.Contains('"')) { throw 'Invalid quote in path.' }
    $arguments = '-NoProfile -NonInteractive -File "' + $Orchestrator + '" -Collect -ProjectRoot "' + $Root + '"'
    $result = [Phase58Process]::Run($shell, $arguments, 120000)
    $health = 'UNKNOWN'
    $detail = $result.Detail
    if ($result.Status -eq 'PASS') {
        try {
            if ([string]::IsNullOrWhiteSpace($result.Output)) {
                throw 'Collection returned empty JSON output.'
            }
            $snapshot = $result.Output.Trim() | ConvertFrom-Json -ErrorAction Stop
            if ($snapshot.validation -cne 'PASS' -or $snapshot.saved -ne $true -or
                $snapshot.check_count -ne 9 -or $snapshot.overall_status -notin @('PASS','WARN','FAIL')) {
                throw 'Unexpected collection response contract.'
            }
            $historyPath = [string]$snapshot.history_file
            $historyRoot = [IO.Path]::GetFullPath((Join-Path $Monitoring 'history'))
            if (-not $historyPath.StartsWith($historyRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected history destination.' }
            Assert-SafePath $historyPath
            if (-not (Test-Path -LiteralPath $historyPath -PathType Leaf)) { throw 'Reported snapshot missing.' }
            $health = [string]$snapshot.overall_status
            $detail = 'validated monitoring snapshot saved'
        } catch {
            $result.Status = 'FAIL'
            $result.ExitCode = 2
            $detail = 'collection response validation failed'
        }
    }
    Save-ExecutionRecord $result.Status $result.ExitCode $result.DurationMs $detail $health
    Prune-OwnLogs 30
    if ($result.Status -ne 'PASS') { throw "Phase 5.8 execution $($result.Status) (exit $($result.ExitCode))." }
} finally {
    if ($lock) { $lock.Dispose() }
}

# SIG # Begin signature block
# MIIHPAYJKoZIhvcNAQcCoIIHLTCCBykCAQExDzANBglghkgBZQMEAgEFADB5Bgor
# BgEEAYI3AgEEoGswaTA0BgorBgEEAYI3AgEeMCYCAwEAAAQQH8w7YFlLCE63JNLG
# KX7zUQIBAAIBAAIBAAIBAAIBADAxMA0GCWCGSAFlAwQCAQUABCAKt/9mKARa7XJm
# 97ffTIUllUelCtcxoTcrhShp3XR6iKCCBCQwggQgMIICiKADAgECAhAVFyfD6LKF
# rkTwisQUN9OsMA0GCSqGSIb3DQEBCwUAMCgxJjAkBgNVBAMMHUNJUkEgRGV2ZWxv
# cG1lbnQgQ29kZSBTaWduaW5nMB4XDTI2MTEwODIxNTc0N1oXDTI4MTEwODIyMDc0
# N1owKDEmMCQGA1UEAwwdQ0lSQSBEZXZlbG9wbWVudCBDb2RlIFNpZ25pbmcwggGi
# MA0GCSqGSIb3DQEBAQUAA4IBjwAwggGKAoIBgQC2jHzglVs8pT+0sxxADJaasNzY
# Cu+pcYnc1KucLUU51mio7xBFFqd14lQSRZaZMxnZsssw3FrgmXBG3QhB39Gxn55i
# xkE3g2gotBXkBRdNCuzfEAnTfW3o20cjQnOhZ0Ei+VV6OMBNT+j1WCn3Xem3XrSv
# n4+j3INkbN8COJGqiH8do+0804Imd3+rXiI7+5jv5tyMMhTF5kou4oh8ANCzMOhg
# QQsw+zyTH3koCY5o7vhJRnKnBktxxa+xlSCtkZfUrB8ELUb7nuvFSXd5GQmMxplF
# wREG0B07F6KEADrstHUGXABSpYH1rZlvSZORzdJIjCduURfoq4ZKC9m7/sV32ybj
# tTwONGqX0lT6wOyMernYnZA/XZIAgiwlMRyAhTVPkmt0SMHh2/zhu4sLd14XPCRP
# 2vBYjwTtCbcuaq8kaFkUIYjngHR1qAmkXFf1F8RBgifqpqSuKed2mnvPCjTCA38k
# R0oJyNFJB47XLzS73fG2vjp1hoIEaNZGdB5qdvkCAwEAAaNGMEQwDgYDVR0PAQH/
# BAQDAgeAMBMGA1UdJQQMMAoGCCsGAQUFBwMDMB0GA1UdDgQWBBQl/N2J5DPOPa8u
# 44j3tQlWdjglsDANBgkqhkiG9w0BAQsFAAOCAYEAdcwmvx1S8ynouuQh68XvvEEu
# iKQS/KTj7N4cdkeniHuYEm+VwTj4XwZ3TJOztMXxvU719c6JdI60G3x1FPUmg1Ql
# Vd7nm0MugN64aypztMfYUC9Szz6l89E8g4/PPqbjVxfaM82tuoJ9eMdhkpzaqvL3
# 05RsCmVfTgU9SORjAWoQTdh+yGyypdf0TGK2UfiGGMmT3Bjl9vBNZpnVVzhIpU6h
# FtUUi/35yUbvZ4Dh/skxXwA7YAAM9Qi2Iq0QK70f12nkc+Fjk/fhTah0S1ZV3ljb
# 6hGzAkEMR1J8YFlrFdU3OjtJy01RGsPmBdBZpeFA51Lxnw2tL2mwsDFP1zigf0z4
# Dx2n/jRIn4p22nLSour83fzbRFujNxdBRoQNpge9fVFnFa9JXC4RYwajanlcV4Eb
# kyRPM1vwtrhpwh0g01e/UiUC2BL9t/tCcRP24j/vsJsmwy+TQIa5kHADOXNxzqxN
# Q3wzqIkBSthpn1VVv3yHmoGIbcrJ+hlEG59JJgErMYICbjCCAmoCAQEwPDAoMSYw
# JAYDVQQDDB1DSVJBIERldmVsb3BtZW50IENvZGUgU2lnbmluZwIQFRcnw+iyha5E
# 8IrEFDfTrDANBglghkgBZQMEAgEFAKCBhDAYBgorBgEEAYI3AgEMMQowCKACgACh
# AoAAMBkGCSqGSIb3DQEJAzEMBgorBgEEAYI3AgEEMBwGCisGAQQBgjcCAQsxDjAM
# BgorBgEEAYI3AgEVMC8GCSqGSIb3DQEJBDEiBCCtvm4+1un+uVsaQdgBiyYVoWmx
# U7PUEY/dgCl0/xFDfjANBgkqhkiG9w0BAQEFAASCAYBKbMBn3cVyZnxuhbTIXNaM
# 7sVQkjih1UGyqED2xKWxxjrAJH/kbZkAOVp/bVasPGYomsCBoboPtasPYkuL2cgN
# Usz02FvegD//6KvL96SRbdvsx0grCx4KahTv8M/krSgAojTb1EOPN+0PaTYW+ruO
# USXO3OdM+j1kNnIArnHKRY7uxZq8KbV16sjgexNztCQTnjUKgUcB3lhBb2PYjPnj
# UtVLbrhxf0r7l1bDqjvfyZnv0X8lIym5DhmX41PxroT4KzC7lAr6FxyinrknJk4g
# ojLEco1JfXJAu+5pxuOiML35EP10X5jzLWl5v5oA7MLm3pWFbamPXEqDYnvIc+mX
# 6D5CgU9zw8WlXG0ws+8LcJP7vLML+LACXOMCCtwz8XfecAePHkzLd4DwdB+2/n4D
# znL5NcqLtUb9cQwvUquYtK1J5PI2yzdH8LoK2aBJPnRJ4Aecpbh5hN88CswhlAUu
# icDGdRjPQGPwXlYNwIju5rmvf99+emP+1I5RaqgwJu4=
# SIG # End signature block
