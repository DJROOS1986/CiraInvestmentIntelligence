#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Collect,
    [switch]$Report,
    [switch]$InstallReport,
    [string]$ProjectRoot = (Join-Path $env:USERPROFILE 'CiraInvestmentIntelligence')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ExpectedScript31Hash = '85ECA5541AD9A30CC4E8393972B393ABD9151F1AC28FB3B3985FE1147E9CF893'
$ExpectedScript30Hash = '609FFE039E72FD65758351369C766426744BC5FAA1BF77736532C19E0327965D'
$Root = [IO.Path]::GetFullPath($ProjectRoot)
$Scripts = Join-Path $Root 'scripts'
$History = Join-Path $Root 'monitoring\history'
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Script30 = Join-Path $Scripts '30-CIRA-Operational-Health.py'
$Script31 = Join-Path $Scripts '31-CIRA-Monitoring-History.py'
$Script32 = Join-Path $Scripts '32-CIRA-Monitoring-Report.py'
$ReportSource = Join-Path $PSScriptRoot '32-CIRA-Monitoring-Report.py'

function Assert-SafePath([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($true) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Reparse point is prohibited: $current"
            }
        }
        $parent = Split-Path -Path $current -Parent
        if (-not $parent -or $parent -eq $current) { break }
        $current = $parent
    }
}
function Assert-Hash([string]$Path, [string]$Hash) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing file: $Path" }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Hash) { throw "Integrity mismatch: $Path" }
}
function Invoke-Python([string[]]$Arguments) {
    $result = & $Python @Arguments 2>&1
    $exit = $LASTEXITCODE
    if ($exit -ne 0) { throw "Python exited $exit : $($result -join ' ')" }
    return ($result -join "`n")
}

if (($Collect -and $InstallReport) -or ($Report -and $InstallReport)) {
    throw 'InstallReport must be run separately from collection/reporting.'
}
foreach ($path in @($Root, $Scripts, $History, $Python, $Script30, $Script31, $Script32)) { Assert-SafePath $path }
foreach ($directory in @($Root, $Scripts, $History)) {
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) { throw "Missing directory: $directory" }
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Project Python environment is missing.' }
Assert-Hash $Script30 $ExpectedScript30Hash
Assert-Hash $Script31 $ExpectedScript31Hash

if (-not ($Collect -or $Report -or $InstallReport)) {
    Write-Host 'CIRA Phase 5.7 — DRY RUN (no changes)' -ForegroundColor Cyan
    Write-Host 'Script 30 and Script 31: verified'
    Write-Host "Script 32 installed: $(Test-Path -LiteralPath $Script32 -PathType Leaf)"
    Write-Host 'Use -InstallReport to install Script 32, -Collect to capture one snapshot, -Report to summarize history.'
    Write-Host 'No schedules, Git commits, Azure, promotion or recovery.'
    return
}

if ($InstallReport) {
    Assert-SafePath $ReportSource
    if (-not (Test-Path -LiteralPath $ReportSource -PathType Leaf)) { throw 'Script 32 source must be beside the orchestrator.' }
    if (Test-Path -LiteralPath $Script32) { throw 'Script 32 already exists; refusing overwrite.' }
    $sourceHash = (Get-FileHash -LiteralPath $ReportSource -Algorithm SHA256).Hash
    $stream = $null
    try {
        $stream = [IO.File]::Open($Script32, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $bytes = [IO.File]::ReadAllBytes($ReportSource)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally { if ($stream) { $stream.Dispose() } }
    if ((Get-FileHash -LiteralPath $Script32 -Algorithm SHA256).Hash -ne $sourceHash) { throw 'Script 32 copy integrity mismatch.' }
    Write-Host 'Script 32 installed. No scripts executed.' -ForegroundColor Green
    return
}

if ($Collect) {
    # Script 30 is expected to emit exactly one JSON snapshot on stdout.
    # If it emits text or an unexpected schema, no history is saved.
    $raw = Invoke-Python @($Script30, '--root', $Root)
    try { $snapshot = $raw | ConvertFrom-Json -ErrorAction Stop }
    catch { throw 'Script 30 did not emit a single JSON snapshot. No history saved.' }
    if ($snapshot.mode -ne 'read_only' -or $snapshot.phase -ne '5.6' -or $snapshot.recovery_authorized -ne $false -or @($snapshot.checks).Count -ne 9) {
        throw 'Unexpected Script 30 monitoring contract. No history saved.'
    }
    $temp = Join-Path ([IO.Path]::GetTempPath()) ('cira-monitor-' + [guid]::NewGuid().ToString('N') + '.json')
    try {
        [IO.File]::WriteAllText($temp, $raw, (New-Object System.Text.UTF8Encoding($false)))
        $saved = Invoke-Python @($Script31, '--input', $temp, '--save', '--history-dir', $History)
        Write-Output $saved
    } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force } }
}
if ($Report) {
    if (-not (Test-Path -LiteralPath $Script32 -PathType Leaf)) { throw 'Script 32 not installed. Run -InstallReport first.' }
    Write-Output (Invoke-Python @($Script32, '--history-dir', $History))
}

# SIG # Begin signature block
# MIIHPAYJKoZIhvcNAQcCoIIHLTCCBykCAQExDzANBglghkgBZQMEAgEFADB5Bgor
# BgEEAYI3AgEEoGswaTA0BgorBgEEAYI3AgEeMCYCAwEAAAQQH8w7YFlLCE63JNLG
# KX7zUQIBAAIBAAIBAAIBAAIBADAxMA0GCWCGSAFlAwQCAQUABCD1sjR+uJ9faLeQ
# 3fqtZb/YxcU/+2tr9RRXrqC4evQTaKCCBCQwggQgMIICiKADAgECAhAVFyfD6LKF
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
# BgorBgEEAYI3AgEVMC8GCSqGSIb3DQEJBDEiBCBzNcNcxRrV3s8jAPqQIbtriL81
# RObMjfvJjiSZVB37YTANBgkqhkiG9w0BAQEFAASCAYCvITfbnhAnOPXSTqzY0mo+
# jz94Hq3/3HL59E3rWyh4XZxWCtl5JQAjoowZNHbREPr/2Z2rnzJWEtgvTzYVL6ez
# emrmsA0jupUuxlyd+vvV/uCV0vxfV1ht0/Pl7zMbrJm4M4vfZvTzgH2bGxE2B8+E
# qlU2YXc6RxITcR+mq8d8eJirgdqTxAQ2y/P3LqCcusBTdg9dA75rMlGGcixsNE83
# fr2O1G4GOua+XBw5RFmAkovQQb5aRBZ2A8PI+8ELOpetPFPNx31zeQzuhtKOwQLi
# vRKmZadVa6dAaSyH+X+xOn0wHHRfLGW8qVKpFCIJ5jR93ssoU+Nm91u44gK2Zfzi
# yuxnlr+vq26cMFMVLUcfvqMrTv9ouUr86miJf+QaCb270BTaRlxPlgsOYYSf6mO7
# PiIDmpXI1wJbjY9x09BR6ic/J6L3HhJJKRV80vUVzn9+O0ZYDbkSoBb8sRzWBiKD
# By2qN2uF+sjESqlCiKwujR7ocXdg6Ke5ffahC5D+bLs=
# SIG # End signature block
