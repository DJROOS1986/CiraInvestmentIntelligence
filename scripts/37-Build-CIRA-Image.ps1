<#
.SYNOPSIS
    Builds a CIRA container image reproducibly in Azure Container Registry and records it in the repo.

.DESCRIPTION
    1. Preflight: clean Git tree (so the image matches a commit), Dockerfile present,
       registry reachable, tag not already used (tags are never overwritten).
    2. Shows the plan and waits for you to type BUILD.
    3. Builds with `az acr build` (cloud build, no local Docker needed; small ACR Tasks cost).
    4. Verifies the new tag exists in the registry.
    5. Appends a record to docs/IMAGE-BUILDS.md and sets the Terraform variable default
       to the new tag (skip with -SkipTerraformUpdate).

    It does NOT deploy. Roll out with infrastructure\terraform\Invoke-CIRA-Terraform.ps1, then commit.

    Tag convention: <kind>-<yyyyMMdd>-<git short sha>, e.g. research-20261111-de0b947

    Image mapping (research Dockerfile is inferred from the deployed image's contents):
        research  -> cira-financial-intelligence  from Dockerfile.phase5   -> var cira_pipeline_image_tag
        dashboard -> cira-dashboard               from Dockerfile.dashboard -> var cira_dashboard_image_tag

.EXAMPLE
    .\scripts\37-Build-CIRA-Image.ps1 -Image research
.EXAMPLE
    .\scripts\37-Build-CIRA-Image.ps1 -Image dashboard -SkipTerraformUpdate
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('research', 'dashboard')][string]$Image,
    [string]$Registry = 'acrciradeva2pjnb',
    [switch]$SkipTerraformUpdate
)

$ErrorActionPreference = 'Stop'

$map = @{
    research  = @{ Repo = 'cira-financial-intelligence'; Dockerfile = 'Dockerfile.phase5';    TfVar = 'cira_pipeline_image_tag' }
    dashboard = @{ Repo = 'cira-dashboard';              Dockerfile = 'Dockerfile.dashboard'; TfVar = 'cira_dashboard_image_tag' }
}
$cfg = $map[$Image]

function Write-Step([string]$Text) { Write-Host "`n=== $Text ===" -ForegroundColor Cyan }

$top = git rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) { throw 'Not inside a Git repository.' }
$repo = (Resolve-Path $top).Path
Push-Location $repo
try {
    Write-Step '1/5 Preflight'
    $dirty = @(git status --porcelain)
    if ($dirty.Count -gt 0) { $dirty; throw 'Working tree is not clean. Commit or restore first, so the image matches a commit exactly.' }
    if (-not (Test-Path -LiteralPath $cfg.Dockerfile)) { throw "$($cfg.Dockerfile) not found in repo root." }

    $sha    = (git rev-parse --short HEAD).Trim()
    $tag    = '{0}-{1}-{2}' -f $Image, (Get-Date).ToUniversalTime().ToString('yyyyMMdd'), $sha
    $target = '{0}:{1}' -f $cfg.Repo, $tag

    $null = az acr show --name $Registry --query name -o tsv
    if ($LASTEXITCODE -ne 0) { throw "Registry $Registry not reachable with current az login." }
    $existing = @(az acr repository show-tags --name $Registry --repository $cfg.Repo -o tsv)
    if ($existing -contains $tag) { throw "Tag $tag already exists. Make a new commit first; tags are never overwritten." }

    $tfFiles = @(Get-ChildItem -Path 'infrastructure/terraform' -Filter *.tf -File)
    $varPattern = '(variable\s+"' + [regex]::Escape($cfg.TfVar) + '"\s*\{[^}]*?default\s*=\s*")([^"]*)(")'
    $tfHits = @($tfFiles | Where-Object { [regex]::IsMatch([IO.File]::ReadAllText($_.FullName), $varPattern) })
    $currentTag = ''
    if ($tfHits.Count -eq 1) { $currentTag = [regex]::Match([IO.File]::ReadAllText($tfHits[0].FullName), $varPattern).Groups[2].Value }
    if (-not $SkipTerraformUpdate -and $tfHits.Count -ne 1) { throw "Expected exactly one variable `"$($cfg.TfVar)`" with a default in infrastructure/terraform, found $($tfHits.Count). Use -SkipTerraformUpdate." }

    Write-Host "Commit      : $sha (clean tree)"
    Write-Host "Dockerfile  : $($cfg.Dockerfile)"
    Write-Host "Registry    : $Registry"
    Write-Host "New image   : $target"
    Write-Host "Current tag : $currentTag  (Terraform variable $($cfg.TfVar))"

    Write-Step '2/5 Confirm'
    $answer = Read-Host 'Type BUILD to build this image in ACR (anything else cancels)'
    if ($answer -cne 'BUILD') { Write-Host 'Cancelled. Nothing built.'; return }

    Write-Step '3/5 Build (az acr build)'
    az acr build --registry $Registry --image $target --file $cfg.Dockerfile .
    if ($LASTEXITCODE -ne 0) { throw 'az acr build failed. Nothing recorded, Terraform unchanged.' }

    Write-Step '4/5 Verify'
    $after = @(az acr repository show-tags --name $Registry --repository $cfg.Repo -o tsv)
    if ($after -notcontains $tag) { throw "Build reported success but tag $tag is not in the registry." }
    Write-Host "Verified: $target exists in $Registry." -ForegroundColor Green

    Write-Step '5/5 Record'
    $log = 'docs/IMAGE-BUILDS.md'
    if (-not (Test-Path -LiteralPath $log)) {
        $header = "# CIRA image builds`n`nEvery image built with scripts/37-Build-CIRA-Image.ps1. Tag = <kind>-<yyyyMMdd UTC>-<commit>.`n`n| Built (UTC) | Kind | Image | Dockerfile | Commit |`n|---|---|---|---|---|`n"
        [IO.File]::WriteAllText((Join-Path $repo $log), $header, [Text.UTF8Encoding]::new($false))
    }
    $line = '| {0} | {1} | `{2}` | {3} | {4} |' -f (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm'), $Image, $target, $cfg.Dockerfile, $sha
    [IO.File]::AppendAllText((Join-Path $repo $log), $line + "`n", [Text.UTF8Encoding]::new($false))
    Write-Host "Recorded in $log"

    if ($SkipTerraformUpdate) { Write-Host 'Terraform not changed (-SkipTerraformUpdate).' }
    if (-not $SkipTerraformUpdate) {
        $file = $tfHits[0].FullName
        $raw  = [IO.File]::ReadAllText($file)
        $new  = [regex]::Replace($raw, $varPattern, { param($m) $m.Groups[1].Value + $tag + $m.Groups[3].Value })
        [IO.File]::WriteAllText($file, $new, [Text.UTF8Encoding]::new($false))
        Write-Host "Terraform default $($cfg.TfVar): $currentTag -> $tag  ($($tfHits[0].Name))"
    }

    Write-Host "`nNext:" -ForegroundColor Yellow
    Write-Host '  1. .\infrastructure\terraform\Invoke-CIRA-Terraform.ps1          (expect 1 to change)'
    Write-Host '  2. .\infrastructure\terraform\Invoke-CIRA-Terraform.ps1 -Apply   (type APPLY)'
    Write-Host '  3. Verify, then: git add -A docs/IMAGE-BUILDS.md infrastructure/terraform ; git commit'
    Write-Host "  Rollback: set $($cfg.TfVar) default back to '$currentTag' and apply."
}
finally {
    Pop-Location
}
