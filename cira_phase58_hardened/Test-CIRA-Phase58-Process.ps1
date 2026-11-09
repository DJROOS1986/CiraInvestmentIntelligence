#requires -Version 5.1
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$helper = Join-Path $PSScriptRoot 'Phase58Process.cs'
if ((Get-AuthenticodeSignature -LiteralPath $PSCommandPath).Status -ne 'Valid') { throw 'Test script must be signed.' }
if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) { throw 'Missing helper.' }
Add-Type -TypeDefinition ([IO.File]::ReadAllText($helper)) -Language CSharp
$shell = Join-Path $PSHOME 'powershell.exe'
function Assert-Result($test, $actual, $expected) {
    if ($actual -cne $expected) { throw "$test expected $expected but got $actual" }
    Write-Host "PASS: $test"
}
# These tests spawn only synthetic local child processes, never CIRA monitoring.
$success = [Phase58Process]::Run($shell, '-NoProfile -NonInteractive -Command "Write-Output fixture-ok; exit 0"', 10000)
Assert-Result 'success status' $success.Status 'PASS'
if ($success.Output -notmatch 'fixture-ok') { throw 'Missing captured stdout.' }
Write-Host 'PASS: asynchronous output capture'
$failure = [Phase58Process]::Run($shell, '-NoProfile -NonInteractive -Command "exit 7"', 10000)
Assert-Result 'failure status' $failure.Status 'FAIL'
Assert-Result 'failure exit code' $failure.ExitCode 7
$timeout = [Phase58Process]::Run($shell, '-NoProfile -NonInteractive -Command "Start-Sleep -Seconds 15"', 1000)
Assert-Result 'timeout status' $timeout.Status 'TIMEOUT'
Assert-Result 'timeout exit code' $timeout.ExitCode 124
Write-Host 'Synthetic process tests passed. No monitoring, scheduling or project writes.'

# SIG # Begin signature block
# MIIHPAYJKoZIhvcNAQcCoIIHLTCCBykCAQExDzANBglghkgBZQMEAgEFADB5Bgor
# BgEEAYI3AgEEoGswaTA0BgorBgEEAYI3AgEeMCYCAwEAAAQQH8w7YFlLCE63JNLG
# KX7zUQIBAAIBAAIBAAIBAAIBADAxMA0GCWCGSAFlAwQCAQUABCAE/6WpDWDx3HrR
# SnxX5wLWrBwcTAWSGgRb47h5icgFnKCCBCQwggQgMIICiKADAgECAhAVFyfD6LKF
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
# BgorBgEEAYI3AgEVMC8GCSqGSIb3DQEJBDEiBCDMzJg/XBmg/CjIootI8JZcr716
# 5Uya92L1R+RloFA7NTANBgkqhkiG9w0BAQEFAASCAYAypEFuZyWqxRugm/mBh1ku
# 7C3/JF8PMgx+rwABGnH6A2w1qJ612nkM/2wSczX4VWdTWBxr5RhkklVuSAlpZ6j2
# 16GhPl1ANOH+vOCesqcXP+VTYxjgYLfCzqJAngP3C/IhhuVY03IvYekDcxUYtUcr
# kLpu3EVa2u52N4NBO7Zd4RUmNNaduRhosaz6eKQR8TUiIHCWXKjLKslpuA+ji/NB
# MlcK2Ezxph18/UAqnz87zxEa0f/gD+rWNxUdX02NMX2Ei2xO4RCppwhs7pvpxO3a
# Qbrhh1byO+Xi2lac2FvZZyDTsDyyEqjz0A/eVN+ASMXoajUReLYtZkS/Jz71cKQd
# gfSS/Gff2cvJbttrZtYre+FqyXrJDdLqP2xflsGFOxV9KOD6smtfOLDzQjsyLKAX
# ibK8MEilccBxbr4Q8Ci6jOsXgrqEmQGJ2KI7d+UwsXX1p+PwOawRiAtfeuVXYP68
# MKRjWTBzoq9JElk2n3NkPF0znSN38ETjZx0VWUYjaYc=
# SIG # End signature block
