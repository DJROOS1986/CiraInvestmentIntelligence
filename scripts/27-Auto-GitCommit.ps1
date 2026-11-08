param(
    [int]$Threshold = 10
)

$ErrorActionPreference = "Stop"

$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

if ($Threshold -lt 1) {
    throw "Threshold must be at least 1."
}

git rev-parse --is-inside-work-tree *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Not a Git repository."
}

# Exclude generated files, backups, credentials and local state.
$Excluded = @(
    ".venv/"
    ".terraform/"
    ".phase55-backups/"
    ".phase55-staging/"
    "__pycache__/"
    ".pytest_cache/"
    ".env"
    "*.tfstate"
    "*.tfstate.*"
    "*.tfvars"
    "*.tfvars.json"
    "*.pem"
    "*.pfx"
    "*.key"
    "secrets/"
)

# Git status in porcelain v1, including untracked files.
$Entries = @(git -c core.quotepath=false status --porcelain=v1 -uall)

if ($LASTEXITCODE -ne 0) {
    throw "Unable to read Git status."
}

$Eligible = @(
    foreach ($Entry in $Entries) {
        if ($Entry.Length -lt 4) { continue }

        $Path = $Entry.Substring(3).Trim('"')
        if ($Path -match ' -> ') {
            $Path = ($Path -split ' -> ')[-1]
        }

        $Normalized = $Path.Replace('\', '/')
        $Skip = $false

        foreach ($Pattern in $Excluded) {
            if ($Pattern.EndsWith('/')) {
                if ($Normalized.StartsWith(
                    $Pattern,
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                    $Skip = $true
                    break
                }
            }
            elseif ($Normalized -like $Pattern) {
                $Skip = $true
                break
            }
        }

        if (-not $Skip) {
            $Path
        }
    }
)

$Eligible = @($Eligible | Sort-Object -Unique)

Write-Host "Eligible changed files: $($Eligible.Count)"
Write-Host "Commit threshold: $Threshold"

if ($Eligible.Count -lt $Threshold) {
    Write-Host "Waiting for more changes."
    exit 0
}

# Stage only the eligible files.
foreach ($Path in $Eligible) {
    git add -- $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stage: $Path"
    }
}

# Commit the staged changes.
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$Message = "chore(cira): automatic checkpoint $Timestamp"

git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "No staged changes to commit."
    exit 0
}

git commit -m $Message

if ($LASTEXITCODE -ne 0) {
    throw "Git commit failed."
}

Write-Host "AUTOMATIC COMMIT: PASS" -ForegroundColor Green
Write-Host "Committed eligible changes: $($Eligible.Count)"
Write-Host "GitHub push: NO"
Write-Host "Azure operations: NONE"