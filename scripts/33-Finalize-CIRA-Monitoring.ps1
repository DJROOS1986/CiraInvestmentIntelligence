#requires -Version 5.1
#requires -RunAsAdministrator
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$rootPath = Split-Path $PSScriptRoot -Parent
$resultPath = Join-Path $rootPath '.tools/monitoring-deployment.json'
try {
    $wrapper = Join-Path $rootPath 'cira_phase58_hardened_v2/Invoke-CIRA-Phase58.ps1'
    foreach ($path in @($PSCommandPath,$wrapper)) {
        if ((Get-AuthenticodeSignature -LiteralPath $path).Status -ne 'Valid') { throw "Signature invalid: $path" }
    }
    $task = Get-ScheduledTask -TaskName 'CIRA-Daily-Monitoring'
    $expectedArguments = '-NoProfile -NonInteractive -ExecutionPolicy AllSigned -File "' + $wrapper + '" -Run -ProjectRoot "' + $rootPath + '"'
    if (@($task.Actions).Count -ne 1 -or $task.Actions[0].Arguments -cne $expectedArguments) { throw 'Monitoring action differs from reviewed deployment.' }
    $userId = $task.Principal.UserId
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType S4U -RunLevel Limited
    $task.Principal = $principal
    $task.Description = 'Signed local CIRA monitoring daily at 09:00 Copenhagen time, including while logged out. PC must be on. Azure handles ingestion.'
    $null = Set-ScheduledTask -InputObject $task
    $before = (Get-ScheduledTaskInfo -TaskName $task.TaskName).LastRunTime
    Start-ScheduledTask -TaskName $task.TaskName
    $deadline = (Get-Date).AddSeconds(40)
    do {
        Start-Sleep -Seconds 2
        $info = Get-ScheduledTaskInfo -TaskName $task.TaskName
        $live = Get-ScheduledTask -TaskName $task.TaskName
        if ($info.LastRunTime -gt $before -and $live.State -ne 'Running') { break }
    } while ((Get-Date) -lt $deadline)
    if ($info.LastRunTime -le $before -or $live.State -eq 'Running' -or $info.LastTaskResult -ne 0) { throw "Logged-out monitoring test failed: $($info.LastTaskResult)" }
    $old = Get-ScheduledTask -TaskName 'CIRA-Daily-Investment-Intelligence' -ErrorAction SilentlyContinue
    if ($old) {
        if (@($old.Actions).Count -ne 1 -or $old.Actions[0].Arguments -notlike '*scripts\11-Run-All.ps1*') { throw 'Old task differs from reviewed pipeline action.' }
        $null = Disable-ScheduledTask -TaskName $old.TaskName
    }
    $record = @{status='PASS'; timestamp_utc=[DateTime]::UtcNow.ToString('o'); logon_type='S4U'; last_task_result=$info.LastTaskResult; old_pipeline_task_disabled=$true}
    [IO.File]::WriteAllText($resultPath,($record | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
} catch {
    $record = @{status='FAIL'; timestamp_utc=[DateTime]::UtcNow.ToString('o'); error=$_.Exception.Message}
    [IO.File]::WriteAllText($resultPath,($record | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    throw
}

# SIG # Begin signature block
# MIIHPAYJKoZIhvcNAQcCoIIHLTCCBykCAQExDzANBglghkgBZQMEAgEFADB5Bgor
# BgEEAYI3AgEEoGswaTA0BgorBgEEAYI3AgEeMCYCAwEAAAQQH8w7YFlLCE63JNLG
# KX7zUQIBAAIBAAIBAAIBAAIBADAxMA0GCWCGSAFlAwQCAQUABCCJRYMTlckT77iC
# DPMXw90KZk8nki/8RGbtaUVUJIsm8aCCBCQwggQgMIICiKADAgECAhAVFyfD6LKF
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
# BgorBgEEAYI3AgEVMC8GCSqGSIb3DQEJBDEiBCCyeEs1/kjMjvJMy3KV1KPW9Aje
# bej5E3RKvgf/VwWtOzANBgkqhkiG9w0BAQEFAASCAYBoGvzwRADAassFVruIk0Ru
# gZftlCrUD2z05poZU7nZtrFC0h5Awy+y5lO9wDiaB0XoRcKaUTP+1hA9U3cJmMZl
# SlbewK2s+5jTSitkWCNCO9/R61TVsU2J4i6wZTMxdGREyPMalbo/XcAknCUqLrEM
# h1/hhCR2D0cBdpP9CYQGYY2MvQavMaCK5l67SpdwJBsz2WLWtpzv7zy2JgQXZEpW
# n8ycDh9FFEPjp2DsPpcjqpTTCQgSFqwaL29sTWb8MOv/w0OpleqKLx1ej8ma2b3D
# slE7RANx7J78a4fDVeoraMOsLfeMMH4UmbXXqmBpJ3BVD5fGQt4WrH1nBGfc2qfW
# vuiBUUAtExCtOJqJH8v8Fq0w6hrK3IVSumgGKFTWYg94LXyGoGoo1HRsW6K7GN8+
# Zq9SpjpJN95IrIMQdI3goUkmu6ExeHvwm5KaUw6xqpATR2ZE4PS6CuTbIwXo2c60
# mznJa9SE8xUkFTR1f3JQkrFYmiWN+9XiNTfH4Gsj/2U=
# SIG # End signature block
