#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Run,
    [string]$ProjectRoot = (Join-Path $env:USERPROFILE 'CiraInvestmentIntelligence')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-PathSafe([string]$Path) {
    $p = [IO.Path]::GetFullPath($Path)
    while ($true) {
        if (Test-Path -LiteralPath $p) {
            $item = Get-Item -LiteralPath $p -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Reparse point rejected: $p"
            }
        }
        $parent = Split-Path -Path $p -Parent
        if (-not $parent -or $parent -eq $p) { break }
        $p = $parent
    }
}
function Assert-Config($Config) {
    $keys = @('phase','enabled','frequency','local_time','operation','timeout_seconds','log_retention_days','run_if_missed','allow_overlapping_runs','allow_azure_operations','allow_promotion_recovery')
    $actual = @($Config.PSObject.Properties.Name)
    if (@($actual | Where-Object { $_ -notin $keys }).Count -gt 0 -or @($keys | Where-Object { $_ -notin $actual }).Count -gt 0) { throw 'Unexpected configuration fields.' }
    if ($Config.phase -cne '5.8' -or $Config.enabled -isnot [bool] -or $Config.enabled -ne $false -or
        $Config.frequency -cne 'daily' -or $Config.local_time -cnotmatch '^([01][0-9]|2[0-3]):[0-5][0-9]$' -or
        $Config.operation -cne 'collect' -or $Config.timeout_seconds -isnot [int] -or $Config.timeout_seconds -ne 120 -or
        $Config.log_retention_days -isnot [int] -or $Config.log_retention_days -ne 30 -or
        $Config.run_if_missed -isnot [bool] -or $Config.run_if_missed -or
        $Config.allow_overlapping_runs -isnot [bool] -or $Config.allow_overlapping_runs -or
        $Config.allow_azure_operations -isnot [bool] -or $Config.allow_azure_operations -or
        $Config.allow_promotion_recovery -isnot [bool] -or $Config.allow_promotion_recovery) {
        throw 'Configuration violates the approved Phase 5.8 safety profile.'
    }
}
function Write-Record([string]$Kind, [string]$Status, [int]$ExitCode, [int]$DurationMs, [string]$Detail) {
    $record = [ordered]@{
        phase = '5.8'; timestamp_utc = [DateTime]::UtcNow.ToString('o'); event = $Kind
        status = $Status; exit_code = $ExitCode; duration_ms = $DurationMs; detail = $Detail
    }
    $json = ConvertTo-Json -InputObject $record -Compress
    $name = 'cira-run-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ') + '-' + [guid]::NewGuid().ToString('N') + '.json'
    $dest = Join-Path $Logs $name
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($json)
    $fs = [IO.File]::Open($dest, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $fs.Write($bytes, 0, $bytes.Length); $fs.Flush($true) } finally { $fs.Dispose() }
    Write-Host "$Kind : $Status ($ExitCode)"
}

$Root = [IO.Path]::GetFullPath($ProjectRoot)
$ConfigFile = Join-Path $PSScriptRoot 'phase58-config.json'
$Orchestrator = Join-Path $Root 'cira_phase57\Invoke-CIRA-Phase57.ps1'
$Monitoring = Join-Path $Root 'monitoring'
$Logs = Join-Path $Monitoring 'logs'
$LockFile = Join-Path $Logs 'phase58.lock'
foreach ($path in @($Root, $PSScriptRoot, $ConfigFile, $Orchestrator, $Monitoring, $Logs, $LockFile)) { Assert-PathSafe $path }
if (-not (Test-Path -LiteralPath $Root -PathType Container)) { throw 'Project root missing.' }
if (-not (Test-Path -LiteralPath $ConfigFile -PathType Leaf)) { throw 'Configuration missing.' }
$Config = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Config $Config
if (-not (Test-Path -LiteralPath $Orchestrator -PathType Leaf)) { throw 'Phase 5.7 orchestrator missing.' }
$signature = Get-AuthenticodeSignature -LiteralPath $Orchestrator
if ($signature.Status -ne 'Valid') { throw 'Phase 5.7 orchestrator signature is not valid.' }
if (-not $Run) {
    Write-Host 'CIRA Phase 5.8 DESIGN DRY RUN — no files changed.'
    Write-Host 'Configuration: daily 09:00 local, collect, 120s timeout, 30d log retention.'
    Write-Host 'No task registration; no snapshot collection; no log writes.'
    return
}
# Manual -Run is the only execution gate. The enabled=false setting prohibits any automatic scheduling.
if (-not (Test-Path -LiteralPath $Monitoring -PathType Container)) { throw 'Monitoring directory missing.' }
if (-not (Test-Path -LiteralPath $Logs -PathType Container)) { [void](New-Item -ItemType Directory -Path $Logs) }
Assert-PathSafe $Logs
$lock = $null
try {
    try {
        $lock = [IO.File]::Open($LockFile, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] {
        Write-Host 'SKIP: another Phase 5.8 run owns the lock.'
        return
    }
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    $process = $null
    $status = 'FAIL'
    $code = -1
    $detail = 'unknown'
    try {
        $shell = Join-Path $PSHOME 'powershell.exe'
        if (-not (Test-Path -LiteralPath $shell -PathType Leaf)) { throw 'Windows PowerShell executable missing.' }
        $psi = New-Object Diagnostics.ProcessStartInfo
        $psi.FileName = $shell
        $psi.Arguments = '-NoProfile -NonInteractive -File "' + $Orchestrator + '" -Collect -ProjectRoot "' + $Root + '"'
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $process = New-Object Diagnostics.Process
        $process.StartInfo = $psi
        if (-not $process.Start()) { throw 'Unable to start monitoring child process.' }
        if (-not $process.WaitForExit(120000)) {
            try { $process.Kill() } catch { }
            [void]$process.WaitForExit(5000)
            $status = 'TIMEOUT'; $code = 124; $detail = 'monitoring exceeded 120 seconds'
        } else {
            $code = $process.ExitCode
            $status = if ($code -eq 0) { 'PASS' } else { 'FAIL' }
            $detail = if ($code -eq 0) { 'collection process completed; inspect monitoring history for health status' } else { 'collection process returned a nonzero exit code' }
        }
    } catch {
        $status = 'FAIL'; $code = 1; $detail = 'runner or child-process failure'
    } finally {
        $stopwatch.Stop()
        if ($process) { $process.Dispose() }
    }
    Write-Record 'manual_collection' $status $code ([int]$stopwatch.ElapsedMilliseconds) $detail
    # Retention applies only to this runner's own JSON execution logs; never history.
    $cutoff = [DateTime]::UtcNow.AddDays(-30)
    Get-ChildItem -LiteralPath $Logs -Filter 'cira-run-*.json' -File | ForEach-Object {
        Assert-PathSafe $_.FullName
        if ($_.LastWriteTimeUtc -lt $cutoff) { Remove-Item -LiteralPath $_.FullName -Force }
    }
    if ($status -ne 'PASS') { throw "Phase 5.8 collection $status (exit $code)." }
} finally {
    if ($lock) { $lock.Dispose() }
}

# SIG # Begin signature block
# MIIHPAYJKoZIhvcNAQcCoIIHLTCCBykCAQExDzANBglghkgBZQMEAgEFADB5Bgor
# BgEEAYI3AgEEoGswaTA0BgorBgEEAYI3AgEeMCYCAwEAAAQQH8w7YFlLCE63JNLG
# KX7zUQIBAAIBAAIBAAIBAAIBADAxMA0GCWCGSAFlAwQCAQUABCBa8F/cF0pRX3KW
# eGKzCQHTiWmoZGn/vCALAqDdUT4SeqCCBCQwggQgMIICiKADAgECAhAVFyfD6LKF
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
# BgorBgEEAYI3AgEVMC8GCSqGSIb3DQEJBDEiBCBqXlN5tXjDM5tINEaPOJxvbhb0
# ZaTxbpe19gEDIha5JjANBgkqhkiG9w0BAQEFAASCAYBXV7UFZ8bjQ192PJxdjTOT
# uAA8CcwS0VcPgNUXgm247zoSdhoEZrqNXZl9z4hZ/wmK4tkbqV6AUMyuzwIWsIAq
# vJ0hzZ7Qyvk52On5xISH/YsOJyuMeMidE1T/7MHIU1hRCFmdgmPdVhDG2SxbzPG9
# WUn/mIOHrkrxkZWyI1yqEtrjl5wqrM9Iz38RS54OOffGMjmCuYJH+KCN4fesAohN
# 83SAom2kLx3ze6RDshJUt0WZ/9XlXEfq0EhaQyXn5rnSF6P3cowGz6nmPh3VtRqK
# 57ak2W4h6bL9+yAbJhI+UWaFH9PmeD7V18g+iNSUUiw474oipRM14SG5HWi31Vr9
# NnI+/bCfuc4AWOnxFR3cJulYIeo4zx+gJRLcDPt1eNkBs2nRQ2RZPMaeYQXQ+tHn
# 30kOVT7x81pNu8b2y0OgmSY2BhiQUy3ne/K8zKFoECvNdT7co2B3ULY40nKg2LwI
# FCxkNHUseSTmg7FYKjrL4rsUeXrA+JyRTZlQpf7XlOs=
# SIG # End signature block
