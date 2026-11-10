<#
.SYNOPSIS
    Finds leftover files and folders in the CIRA repo root and archives them OUTSIDE the repo.

.DESCRIPTION
    Default (report only): classifies every item in the repo root. Changes nothing.
        KEEP     core project item (allow-list below)
        REVIEW   tracked by Git, or its name is referenced in tracked files -> never moved automatically
        ARCHIVE  untracked by Git and not referenced anywhere -> safe candidate

    -Archive : after you type ARCHIVE, moves only ARCHIVE candidates to
               ..\CiraInvestmentIntelligence_archive\<timestamp>\ and writes manifest.csv there.
               The archive sits outside the repo, so VS Code AI tools no longer read stale copies.
               Nothing is deleted.

    -RestoreFrom <folder> : moves every item listed in that archive's manifest.csv back.

    Never touches files tracked by Git. Never commits.

.EXAMPLE
    .\scripts\36-Archive-Root-Leftovers.ps1
.EXAMPLE
    .\scripts\36-Archive-Root-Leftovers.ps1 -Archive
.EXAMPLE
    .\scripts\36-Archive-Root-Leftovers.ps1 -RestoreFrom 'C:\Users\45298\CiraInvestmentIntelligence_archive\20261110-230000'
#>
[CmdletBinding()]
param(
    [switch]$Archive,
    [string]$RestoreFrom
)

$ErrorActionPreference = 'Stop'

$top = git rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) { throw 'Not inside a Git repository.' }
$repo = (Resolve-Path $top).Path
$archiveRoot = Join-Path (Split-Path $repo -Parent) ((Split-Path $repo -Leaf) + '_archive')

if ($RestoreFrom) {
    $manifest = Join-Path $RestoreFrom 'manifest.csv'
    if (-not (Test-Path -LiteralPath $manifest)) { throw "manifest.csv not found in $RestoreFrom" }
    foreach ($row in Import-Csv -LiteralPath $manifest) {
        $target = Join-Path $repo $row.Name
        if (Test-Path -LiteralPath $target) { Write-Warning "Skipped $($row.Name): already exists in the repo."; continue }
        Move-Item -LiteralPath (Join-Path $RestoreFrom $row.Name) -Destination $target
        Write-Host "Restored $($row.Name)"
    }
    return
}

$keep = @(
    '.git', '.github', '.tools', '.venv', '.pytest_cache',
    'agents', 'dashboard', 'docs', 'infrastructure', 'ingestion', 'monitoring',
    'portfolio-engine', 'reports', 'scripts', 'tests',
    '.dockerignore', '.gitignore', 'config.json', 'README.md', 'requirements-dev.txt',
    'Dockerfile', 'Dockerfile.dashboard', 'Dockerfile.phase5'
)
$tracked = @(git -C $repo ls-files)

function Get-Decision([string]$Name) {
    if ($keep -contains $Name) { return [pscustomobject]@{ Decision = 'KEEP'; Reason = 'core project item' } }

    $prefix = "$Name/"
    $isTracked = @($tracked | Where-Object { $_ -eq $Name -or $_.StartsWith($prefix) } | Select-Object -First 1).Count -gt 0
    if ($isTracked) { return [pscustomobject]@{ Decision = 'REVIEW'; Reason = 'tracked by Git (remove deliberately with git rm)' } }

    $refs = @(git -C $repo --no-pager grep -l -F -- $Name)
    if ($LASTEXITCODE -eq 0) { return [pscustomobject]@{ Decision = 'REVIEW'; Reason = "name referenced in: $(($refs | Select-Object -First 3) -join ', ')" } }

    return [pscustomobject]@{ Decision = 'ARCHIVE'; Reason = 'untracked and not referenced' }
}

$rows = foreach ($item in Get-ChildItem -LiteralPath $repo -Force) {
    $d = Get-Decision $item.Name
    $sizeKb = ''
    if ($d.Decision -ne 'KEEP') {
        $bytes = ($item | Get-ChildItem -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
        if (-not $item.PSIsContainer) { $bytes = $item.Length }
        $sizeKb = [math]::Round(($bytes / 1KB), 1)
    }
    $type = 'file'
    if ($item.PSIsContainer) { $type = 'folder' }
    [pscustomobject]@{ Decision = $d.Decision; Name = $item.Name; Type = $type; SizeKB = $sizeKb; Reason = $d.Reason }
}

$rows | Sort-Object @{ Expression = { @('ARCHIVE', 'REVIEW', 'KEEP').IndexOf($_.Decision) } }, Name |
    Format-Table -AutoSize -Wrap

$candidates = @($rows | Where-Object { $_.Decision -eq 'ARCHIVE' })
Write-Host ("Summary: {0} ARCHIVE, {1} REVIEW, {2} KEEP" -f $candidates.Count,
    @($rows | Where-Object { $_.Decision -eq 'REVIEW' }).Count,
    @($rows | Where-Object { $_.Decision -eq 'KEEP' }).Count)

if ($candidates.Count -eq 0) { Write-Host 'Nothing to archive.' -ForegroundColor Green; return }
if (-not $Archive) { Write-Host "`nReport only, nothing moved. Re-run with -Archive to move the ARCHIVE items." -ForegroundColor Yellow; return }

$dest = Join-Path $archiveRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
Write-Host "`nWill MOVE $($candidates.Count) item(s) to: $dest"
$answer = Read-Host 'Type ARCHIVE to move them (anything else cancels)'
if ($answer -cne 'ARCHIVE') { Write-Host 'Cancelled. Nothing moved.'; return }

New-Item -ItemType Directory -Path $dest -Force | Out-Null
$moved = New-Object System.Collections.Generic.List[object]
try {
    foreach ($c in $candidates) {
        Move-Item -LiteralPath (Join-Path $repo $c.Name) -Destination (Join-Path $dest $c.Name)
        $moved.Add([pscustomobject]@{ Name = $c.Name; Type = $c.Type; SizeKB = $c.SizeKB; MovedAt = (Get-Date -Format s) })
        Write-Host "Moved $($c.Name)"
    }
}
finally {
    if ($moved.Count -gt 0) { $moved | Export-Csv -LiteralPath (Join-Path $dest 'manifest.csv') -NoTypeInformation }
}

Write-Host "`nArchived $($moved.Count) item(s). To undo:" -ForegroundColor Green
Write-Host "  .\scripts\36-Archive-Root-Leftovers.ps1 -RestoreFrom '$dest'"
