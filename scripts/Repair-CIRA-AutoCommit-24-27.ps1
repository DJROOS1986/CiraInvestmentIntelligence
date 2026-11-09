#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Test','Install','Schedule')][string]$Mode = 'Test',
    [int]$Threshold = 10,
    [int]$Minutes = 5
)
$ErrorActionPreference = 'Stop'
$Root = Join-Path $env:USERPROFILE 'CiraInvestmentIntelligence'
$Installed = Join-Path $Root 'scripts\27-Auto-GitCommit.ps1'
$Candidate = Join-Path $Root 'scripts\27-Auto-GitCommit.candidate.ps1'
$BackupDir = Join-Path $Root '.phase55-backups\source-code'
if (!(Test-Path (Join-Path $Root '.git'))) { throw "CIRA Git repository not found: $Root" }
if ($Threshold -lt 1 -or $Minutes -lt 1) { throw 'Threshold and Minutes must be positive.' }
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
function Assert-Exit($message) { if ($LASTEXITCODE -ne 0) { throw $message } }
function Backup-File($path) {
    if (Test-Path $path) {
        $name = [IO.Path]::GetFileName($path)
        $dest = Join-Path $BackupDir ("$name." + [guid]::NewGuid().ToString('N') + '.bak')
        Copy-Item -LiteralPath $path -Destination $dest
        if ((Get-FileHash $path).Hash -ne (Get-FileHash $dest).Hash) { throw 'Backup integrity failed' }
        Write-Host "Backup verified: $dest"
    }
}
$ScriptBody = @'
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
'@
function New-Sandbox {
    $dir = Join-Path $env:TEMP ('cira-verify-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path (Join-Path $dir 'scripts') -Force | Out-Null
    Copy-Item $Candidate (Join-Path $dir 'scripts\27-Auto-GitCommit.candidate.ps1')
    Push-Location $dir
    try {
        git init -q; Assert-Exit 'Sandbox git init failed'
        git config user.name 'CIRA Sandbox'; git config user.email 'cira@example.invalid'
        git config commit.gpgsign false
        git add --all
        git commit -q -m 'initial sandbox state'; Assert-Exit 'Sandbox initial commit failed'
    } finally { Pop-Location }
    return $dir
}
function Test-Candidate {
    $dir = New-Sandbox
    $script = Join-Path $dir 'scripts\27-Auto-GitCommit.candidate.ps1'
    Push-Location $dir
    try {
        1..10 | ForEach-Object { Set-Content ("test-{0:D2}.md" -f $_) "harmless test $_" }
        & $script -Threshold 10
        & $script -Threshold 10 -Commit
        $files = @(git diff-tree --no-commit-id --name-only -r HEAD)
        if ($files.Count -ne 10 -or @($files | Where-Object { $_ -notmatch '^test-\d\d\.md$' }).Count) { throw "Incorrect committed file set: $($files -join ', ')" }
        if (@(git diff --cached --name-only).Count) { throw 'Normal index not clean' }
        if (@(git status --porcelain).Count) { throw 'Sandbox working tree not clean' }
        Write-Host 'PASS: exactly 10 files committed; index and working tree clean' -ForegroundColor Green
    } finally { Pop-Location }
    $dir2 = New-Sandbox
    $script2 = Join-Path $dir2 'scripts\27-Auto-GitCommit.candidate.ps1'
    Push-Location $dir2
    try {
        1..9 | ForEach-Object { Set-Content ("safe-{0:D2}.md" -f $_) 'safe' }
        Set-Content 'unsafe.md' 'client_secret = "FAKE_NOT_REAL"'
        $before = (git rev-parse HEAD).Trim()
        $blocked = $false
        try { & $script2 -Threshold 10 -Commit } catch { $blocked = $_.Exception.Message -match 'Potential secret' }
        if (!$blocked -or (git rev-parse HEAD).Trim() -ne $before) { throw 'Secret blocking failed' }
        Write-Host 'PASS: fake secret blocked; HEAD unchanged' -ForegroundColor Green
        Remove-Item 'unsafe.md'
        git add safe-01.md; Assert-Exit 'Cannot stage sandbox file'
        $blocked = $false
        try { & $script2 -Threshold 1 -Commit } catch { $blocked = $_.Exception.Message -match 'Manually staged' }
        if (!$blocked) { throw 'Manually staged files were not blocked' }
        Write-Host 'PASS: manual staging protected' -ForegroundColor Green
    } finally { Pop-Location }
    # Mutex contention uses a separate child process. Hold mutex in parent and check child output.
    $identity = [IO.Path]::GetFullPath($dir2).ToUpperInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($identity))).Replace('-','') }
    finally { $sha.Dispose() }
    $mutex = New-Object Threading.Mutex($false, ('Local\CIRA-AutoCommit-' + $hash))
    $acquired = $false
    try {
        $acquired = $mutex.WaitOne(0)
        if (!$acquired) { throw 'Cannot acquire test mutex' }
        $exe = (Get-Process -Id $PID).Path
        $output = & $exe -NoProfile -NonInteractive -File $script2 -Threshold 10 2>&1 | Out-String
        if ($output -notmatch 'Another CIRA auto-commit process is running') { throw "Mutex contention test failed. Child output: $output" }
        Write-Host 'PASS: overlapping process blocked by mutex' -ForegroundColor Green
    } finally { if ($acquired) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
}
Write-Host "CIRA Steps 24-27 | Mode: $Mode" -ForegroundColor Cyan
if ($Mode -eq 'Test') {
    Backup-File $Candidate
    [IO.File]::WriteAllText($Candidate, $ScriptBody, (New-Object Text.UTF8Encoding($false)))
    $tokens = $null; $errors = $null
    [Management.Automation.Language.Parser]::ParseFile($Candidate,[ref]$tokens,[ref]$errors) | Out-Null
    if ($errors.Count) { throw "Candidate syntax errors: $($errors -join '; ')" }
    Write-Host 'Candidate rebuilt and syntax verified; installed Script 27 unchanged.'
    Test-Candidate
    Write-Host 'ALL SANDBOX TESTS PASSED. Run -Mode Install only after reviewing results.' -ForegroundColor Green
} elseif ($Mode -eq 'Install') {
    Write-Host 'Re-running tests before installation...'
    Test-Candidate
    Backup-File $Installed
    Copy-Item $Candidate $Installed -Force
    Write-Host 'Installed verified Script 27. No real project commit or schedule created.' -ForegroundColor Green
} elseif ($Mode -eq 'Schedule') {
    if (!(Test-Path $Installed)) { throw 'Installed script missing. Run -Mode Install first.' }
    if ((Get-FileHash $Installed).Hash -ne (Get-FileHash $Candidate).Hash) { throw 'Installed script differs from candidate; schedule refused.' }
    $taskName = 'CIRA-Safe-AutoCommit'
    $exe = (Get-Process -Id $PID).Path
    $action = New-ScheduledTaskAction -Execute $exe -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $Installed + '" -Threshold ' + $Threshold + ' -Commit')
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $Minutes) -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'Local CIRA Git checkpoint after 10 eligible changes; no push or Azure.' -Force | Out-Null
    Write-Host "Scheduled task installed: $taskName (every $Minutes minutes)." -ForegroundColor Green
}
Write-Host 'CIRA project reports and Azure resources were not accessed.'

# SIG # Begin signature block
# MIIHPAYJKoZIhvcNAQcCoIIHLTCCBykCAQExDzANBglghkgBZQMEAgEFADB5Bgor
# BgEEAYI3AgEEoGswaTA0BgorBgEEAYI3AgEeMCYCAwEAAAQQH8w7YFlLCE63JNLG
# KX7zUQIBAAIBAAIBAAIBAAIBADAxMA0GCWCGSAFlAwQCAQUABCCZf5kItreyD7DW
# DTArAB83X8K5dtDjaBYhymA/N/EJ9KCCBCQwggQgMIICiKADAgECAhAVFyfD6LKF
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
# BgorBgEEAYI3AgEVMC8GCSqGSIb3DQEJBDEiBCCfVM+Dry8UmDsG2nCbh+aODMmU
# 8YHIgVYN1M6xxzFcoTANBgkqhkiG9w0BAQEFAASCAYB1cpchNhP3YYJie2b+EFjS
# Rruw8lAgHSLeOA1wpsr2xJ09z2gIpSKQTe5/GjN7/mFpxOQ1PqYD/YHEpS32lWeA
# 8CS25dkzG3pdAGrkZ1trYFGLRFcStGDm4MX/2OK2/BrEWDJFRX/yHoNqDRBW+Kl2
# LgQCGJ+It/WqI5RKf6PxugZYdCHUmdv55KLsQwogVudGlhLXklCrW9MeEtIWpdYg
# vTU7k4UebzD2wWucQ4ICO4qxBMqZ4AJNp8H178jyuw1lmIGgDz65BmW3lCeFDCH2
# AnMaIGIIozbm4bMQQRTH8J9z6/QIcoN9vut79AlHQW+u1OMsFnm01fti8NB9edEb
# ylp0LTfXKnqvkOu1rnfCdPRVXOW9gXI3CqyUYW0GvgFnDij1kPCAOpP3ziX732eO
# EAJLBxk2DMMhg0OE/8QSizf4RI88XvQlDZeWZyyGeHQaCnqw2SlWQ3yU75F6bcBz
# fkgTwXz9jKBjE/u253Ha0X7D7ZmYtvEX065qwQBhuJY=
# SIG # End signature block
