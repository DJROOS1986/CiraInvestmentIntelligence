#requires -Version 5.1
[CmdletBinding()]
param([int]$Threshold = 10, [switch]$Commit)
$ErrorActionPreference = 'Stop'
if ($Threshold -lt 1) { throw 'Threshold must be positive' }
$Root = Split-Path $PSScriptRoot -Parent
$Root = [IO.Path]::GetFullPath($Root)
$identity = $Root.ToUpperInvariant()
$sha = [Security.Cryptography.SHA256]::Create()
try { $hash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($identity))).Replace('-','') }
finally { $sha.Dispose() }
$mutex = New-Object System.Threading.Mutex($false, ('Local\CIRA-AutoCommit-' + $hash))
$locked = $false
$oldIndex = $env:GIT_INDEX_FILE
$tempIndex = $null
try {
    try { $locked = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) {
        Write-Host 'Another CIRA auto-commit process is running. Skipping this execution.'
        return
    }
    Push-Location $Root
    try {
        if ($oldIndex) { throw 'External GIT_INDEX_FILE is set; refusing to run.' }
        $staged = @(git diff --cached --name-only)
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect staged changes' }
        if ($staged.Count) { throw 'Manually staged changes detected; refusing auto-commit.' }
        $base = (git rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Cannot read HEAD' }
        $branch = (git symbolic-ref -q HEAD).Trim()
        if ($LASTEXITCODE -ne 0 -or !$branch) { throw 'Detached HEAD is not supported' }
        # Git -z output is parsed as bytes so paths with spaces and renames are handled safely.
        $status = @(git -c core.quotepath=false ls-files --modified --others --exclude-standard)
        if ($LASTEXITCODE -ne 0) { throw 'Cannot list changed files' }
        # Include deletions of tracked files; they are safe to stage by exact path.
        $deleted = @(git ls-files --deleted)
        if ($LASTEXITCODE -ne 0) { throw 'Cannot list deleted files' }
        $allowed = @('.py','.ps1','.tf','.bicep','.md','.yml','.yaml')
        $paths = @($status + $deleted | Sort-Object -Unique | Where-Object {
            $p = $_.Replace('\','/')
            $leaf = [IO.Path]::GetFileName($p)
            $ext = [IO.Path]::GetExtension($p).ToLowerInvariant()
            $p -notmatch '(^|/)(\.venv|\.terraform|\.phase55-backups|\.phase55-staging|__pycache__|\.pytest_cache|secrets|reports)(/|$)' -and
            $p -notmatch '^scripts/27-Auto-GitCommit(\.candidate)?\.ps1$' -and
            $leaf -notmatch '(?i)(secret|credential|password|token|private|\.env|\.tfvars|\.tfstate)' -and
            $ext -in $allowed
        })
        Write-Host "Eligible changed files: $($paths.Count)"
        Write-Host "Commit threshold: $Threshold"
        if ($paths.Count -lt $Threshold) { Write-Host 'Waiting for more eligible changes.'; return }
        $patterns = @(
            '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
            '(?i)\b(client_secret|password|api[_-]?key|access[_-]?token|refresh[_-]?token)\b\s*[:=]',
            '(?i)\b(AKIA[0-9A-Z]{16}|ghp_[a-zA-Z0-9]{20,})\b'
        )
        foreach ($p in $paths) {
            if (!(Test-Path -LiteralPath $p -PathType Leaf)) { continue }
            if ((Get-Item -LiteralPath $p).Length -gt 1MB) { throw "File too large for safe auto-commit: $p" }
            $content = [IO.File]::ReadAllText((Join-Path $Root $p))
            foreach ($pattern in $patterns) { if ($content -match $pattern) { throw "Potential secret detected in $p. Commit blocked." } }
        }
        if (-not $Commit) { Write-Host 'DRY RUN: PASS'; $paths | ForEach-Object { Write-Host "  $_" }; return }
        $tempIndex = Join-Path $env:TEMP ('cira-index-' + [guid]::NewGuid().ToString('N'))
        $env:GIT_INDEX_FILE = $tempIndex
        git read-tree $base
        if ($LASTEXITCODE -ne 0) { throw 'Cannot initialize temporary index' }
        foreach ($p in $paths) {
            git add -A -- $p
            if ($LASTEXITCODE -ne 0) { throw "Cannot stage $p" }
        }
        $tree = (git write-tree).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Cannot write tree' }
        $baseTree = (git rev-parse "$base`^{tree}").Trim()
        if ($tree -eq $baseTree) { Write-Host 'No new changes to commit'; return }
        $message = 'chore(cira): automatic checkpoint ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        $newCommit = (git commit-tree $tree -p $base -m $message).Trim()
        if ($LASTEXITCODE -ne 0 -or !$newCommit) { throw 'Cannot create commit object' }
        # Verify normal index remains empty immediately before moving branch.
        $env:GIT_INDEX_FILE = $null
        $stagedAgain = @(git diff --cached --name-only)
        if ($LASTEXITCODE -ne 0 -or $stagedAgain.Count) { throw 'Normal index changed during run; aborting' }
        git update-ref $branch $newCommit $base
        if ($LASTEXITCODE -ne 0) { throw 'Branch changed concurrently; commit not installed' }
        # Restore normal index to new HEAD, preserving working-tree content.
        git read-tree HEAD
        if ($LASTEXITCODE -ne 0) { throw 'Commit succeeded but index synchronization failed; manual review required' }
        Write-Host "AUTOMATIC COMMIT: PASS ($newCommit)"
        Write-Host 'GitHub push: NO; Azure operations: NONE'
    }
    finally { Pop-Location }
}
finally {
    $env:GIT_INDEX_FILE = $oldIndex
    if ($tempIndex -and (Test-Path -LiteralPath $tempIndex)) { Remove-Item -LiteralPath $tempIndex -Force }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
# SIG # Begin signature block
# MIIHPAYJKoZIhvcNAQcCoIIHLTCCBykCAQExDzANBglghkgBZQMEAgEFADB5Bgor
# BgEEAYI3AgEEoGswaTA0BgorBgEEAYI3AgEeMCYCAwEAAAQQH8w7YFlLCE63JNLG
# KX7zUQIBAAIBAAIBAAIBAAIBADAxMA0GCWCGSAFlAwQCAQUABCAz/7KfAwlvp/pf
# yl6KW0LKYuQaRnrX/s0aBSQJWALU8KCCBCQwggQgMIICiKADAgECAhAVFyfD6LKF
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
# BgorBgEEAYI3AgEVMC8GCSqGSIb3DQEJBDEiBCAUpuwUV1UrOLhQ/TetA0K3p9xN
# oxsQUQCGLG1Tc6DgsDANBgkqhkiG9w0BAQEFAASCAYCMUlHgSu1c8kXWxmlzcbL6
# plmPAzXXukN7PKELSWPJnW8VrTuIebVzta/6xOdEofawDJLdhENYBmCAtIe3qpRJ
# ZkDq1Hrlh9bneizfG/xgVstnaK/Kox79ZORRO8Cdb9AhlvJWV7NbZTq2BA/mTZ66
# ro7wm4sCrk8Z49X4m4u9snxnaK1vNm++3QZsCZPIrwVQY74OB9UQX47frCSGORmw
# vnDidcvvW7mtcrUj0ij/7bjbS1N/aHMjpyTEY/sYeVrQY5qDC8rHEQR11iSL5rL5
# CgIC8RSA0mdj1+TKPMeZwa0pMQavThnxqyf9huy/k4LB86UDeNiiwoA3Tt4QpobP
# HwtX8nwmVS80p5yeBXsdYmKaYJLGhOhNLH7tQce5r7WIq+dGFUNydewaSL5HfgSW
# GNtaNtibj4xeS7I/S5eW2VOBJRc357AfviLELm+n5CFmaTA19V7ZxRn4zH0xVTZK
# o2TPahSr4Z8Dv0Q88tG5OLhnBpyOMXRUk42Oq3xks/g=
# SIG # End signature block
