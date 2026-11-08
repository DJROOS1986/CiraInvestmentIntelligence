param(
    [switch]$Upload,
    [switch]$OverwriteChanged
)

$ErrorActionPreference = "Stop"

$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Generator = Join-Path $Root "scripts\07-Generate-Financial-Reports.py"

$StorageAccount = "stciradeva2pjnb"
$ResourceGroup = "rg-cira-dev"
$Container = "reports"
$ExpectedSubscription = "ff9cce9f-71fe-4f87-ae04-e106a1a6ffb1"

$RunId = Get-Date -Format "yyyyMMdd-HHmmss"
$ReportDir = Join-Path $Root "reports\pipeline"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$Results = New-Object System.Collections.ArrayList
$Started = Get-Date
$Status = "SUCCESS"
$Failure = $null

function Add-Result {
    param(
        [string]$Step,
        [string]$Status,
        [string]$Details
    )

    [void]$Results.Add([pscustomobject]@{
        Step = $Step
        Status = $Status
        Details = $Details
        Time = (Get-Date).ToString("o")
    })

    Write-Host "[$Status] $Step - $Details"
}

function Assert-Exit {
    param([string]$Message)

    if ($LASTEXITCODE -ne 0) {
        throw "$Message (exit code $LASTEXITCODE)"
    }
}

function Get-LocalMD5 {
    param([string]$Path)

    return (Get-FileHash -Path $Path -Algorithm MD5).Hash.ToLowerInvariant()
}

function Test-BlobFinancialContent {
    param(
        [string]$LocalPath,
        [string]$BlobName
    )

    $Temp = Join-Path $env:TEMP (
        "cira-blob-" + [guid]::NewGuid().ToString("N") + ".json"
    )

    try {
        az storage blob download `
            --account-name $StorageAccount `
            --container-name $Container `
            --name $BlobName `
            --file $Temp `
            --auth-mode login `
            --overwrite true `
            --only-show-errors `
            --output none

        Assert-Exit "Could not download Azure blob: $BlobName"

        $Local = Get-Content $LocalPath -Raw |
            ConvertFrom-Json

        $Remote = Get-Content $Temp -Raw |
            ConvertFrom-Json

        # Ignore only the report-generation timestamp.
        $Local.PSObject.Properties.Remove("generated_at_utc")
        $Remote.PSObject.Properties.Remove("generated_at_utc")

        $LocalJson = $Local | ConvertTo-Json -Depth 100 -Compress
        $RemoteJson = $Remote | ConvertTo-Json -Depth 100 -Compress

        return ($LocalJson -ceq $RemoteJson)
    }
    finally {
        Remove-Item $Temp -Force -ErrorAction SilentlyContinue
    }
}
function Get-BlobMD5 {
    param([string]$BlobName)

    $Raw = az storage blob show `
        --account-name $StorageAccount `
        --container-name $Container `
        --name $BlobName `
        --auth-mode login `
        --output json `
        --only-show-errors

    Assert-Exit "Could not read Azure blob: $BlobName"

    $Blob = $Raw | ConvertFrom-Json
    $Base64 = $Blob.properties.contentSettings.contentMd5

    if (-not $Base64) {
        throw "Azure MD5 is missing for $BlobName"
    }

    $Bytes = [Convert]::FromBase64String($Base64)

    return [BitConverter]::ToString($Bytes).Replace("-", "").ToLowerInvariant()
}

try {
    Write-Host "============================================="
    Write-Host " CIRA INVESTMENT INTELLIGENCE PIPELINE"
    Write-Host "============================================="

    # STEP 1: Prerequisites

    if (-not (Test-Path $Python)) {
        throw "Python virtual environment not found"
    }

    if (-not (Test-Path $Generator)) {
        throw "Financial report generator not found"
    }

    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        throw "Azure CLI not found"
    }

    Add-Result "Prerequisites" "PASS" "Python, generator and Azure CLI found"

    # STEP 2: Tests

    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"

    try {
        & $Python -m pytest `
            ".\tests" -v -p no:cacheprovider

        Assert-Exit "Automated tests failed"
    }
    finally {
        Remove-Item Env:\PYTEST_DISABLE_PLUGIN_AUTOLOAD `
            -ErrorAction SilentlyContinue
    }

    Add-Result "Automated tests" "PASS" "Project test suite passed"

    # STEP 3: Generate reports

    & $Python $Generator
    Assert-Exit "Financial report generation failed"

    Add-Result "Report generation" "PASS" "Financial reports generated"

    # STEP 4: Validate financial reports

    $ReportFiles = @(
        @{
            Ticker = "AAPL"
            File = Join-Path $Root "reports\financial\AAPL-financial-report.json"
            Blob = "financial/AAPL-financial-report.json"
        },
        @{
            Ticker = "MSFT"
            File = Join-Path $Root "reports\financial\MSFT-financial-report.json"
            Blob = "financial/MSFT-financial-report.json"
        }
    )

    foreach ($Item in $ReportFiles) {

        if (-not (Test-Path $Item.File)) {
            throw "Missing financial report: $($Item.File)"
        }

        $Data = Get-Content $Item.File -Raw | ConvertFrom-Json
        $Metrics = $Data.metrics_usd

        if ($Data.ticker -ne $Item.Ticker) {
            throw "Incorrect ticker in $($Item.File)"
        }

        if (-not $Data.period_end -or $Data.currency -ne "USD") {
            throw "Invalid financial report metadata: $($Item.Ticker)"
        }

        foreach ($Metric in @(
            "revenue",
            "net_income",
            "total_assets",
            "total_liabilities",
            "operating_cash_flow",
            "capital_expenditure",
            "free_cash_flow"
        )) {
            if ($null -eq $Metrics.$Metric) {
                throw "Missing $Metric for $($Item.Ticker)"
            }
        }

        $ExpectedFCF = [decimal]$Metrics.operating_cash_flow -
                       [decimal]$Metrics.capital_expenditure

        if ([decimal]$Metrics.free_cash_flow -ne $ExpectedFCF) {
            throw "Free cash flow mismatch for $($Item.Ticker)"
        }

        Add-Result "Validate $($Item.Ticker)" "PASS" `
            "Revenue=$($Metrics.revenue); FCF=$($Metrics.free_cash_flow)"
    }

    # STEP 5: Verify existing Azure infrastructure

    $AccountJson = az account show --output json --only-show-errors
    Assert-Exit "Azure login unavailable"

    $Account = $AccountJson | ConvertFrom-Json

    if ($Account.id -ne $ExpectedSubscription) {
        throw "Wrong Azure subscription selected: $($Account.id)"
    }

    $StorageJson = az storage account show `
        --resource-group $ResourceGroup `
        --name $StorageAccount `
        --output json `
        --only-show-errors

    Assert-Exit "Existing storage account not accessible"

    $Storage = $StorageJson | ConvertFrom-Json

    if ($Storage.name -ne $StorageAccount) {
        throw "Unexpected storage account"
    }

    $ContainerJson = az storage container show `
        --account-name $StorageAccount `
        --name $Container `
        --auth-mode login `
        --output json `
        --only-show-errors

    Assert-Exit "Existing reports container not accessible"

    $ContainerInfo = $ContainerJson | ConvertFrom-Json

    if ($ContainerInfo.name -ne $Container) {
        throw "Unexpected container"
    }

    Add-Result "Azure infrastructure" "PASS" `
        "Existing subscription, storage account and container verified"

    # STEP 6: Upload and verify reports

    foreach ($Item in $ReportFiles) {

        $LocalHash = Get-LocalMD5 $Item.File

        $ExistsRaw = az storage blob exists `
            --account-name $StorageAccount `
            --container-name $Container `
            --name $Item.Blob `
            --auth-mode login `
            --query exists `
            --output tsv `
            --only-show-errors

        Assert-Exit "Blob existence check failed: $($Item.Blob)"

        $Exists = "$ExistsRaw".Trim().ToLowerInvariant() -eq "true"

        if ($Exists) {
            $RemoteHash = Get-BlobMD5 $Item.Blob

            if ($LocalHash -eq $RemoteHash) {
                Add-Result "Azure $($Item.Ticker)" "PASS" `
                    "Existing blob matches local report"
                continue
            }

            if (Test-BlobFinancialContent `
                    -LocalPath (Join-Path $Root ("reports\financial\" + $Item.Ticker + "-financial-report.json")) `
                    -BlobName $Item.Blob) {

                Add-Result "Azure $($Item.Ticker)" "PASS" `
                    "Financial content matches; timestamp differs"
                continue
            }

            if (-not $Upload -or -not $OverwriteChanged) {
                throw "Financial data differs for $($Item.Ticker). Use -Upload -OverwriteChanged to replace it."
            }
        }

        if (-not $Exists -and -not $Upload) {
            Add-Result "Azure $($Item.Ticker)" "SKIPPED" `
                "Blob missing; read-only mode"
            continue
        }

        $Overwrite = "false"

        if ($Exists) {
            $Overwrite = "true"
        }

        az storage blob upload `
            --account-name $StorageAccount `
            --container-name $Container `
            --name $Item.Blob `
            --file $Item.File `
            --auth-mode login `
            --overwrite $Overwrite `
            --content-type "application/json" `
            --output none `
            --only-show-errors

        Assert-Exit "Upload failed: $($Item.Blob)"

        $RemoteHash = Get-BlobMD5 $Item.Blob

        if ($LocalHash -ne $RemoteHash) {
            throw "Uploaded content verification failed: $($Item.Ticker)"
        }

        Add-Result "Azure $($Item.Ticker)" "PASS" `
            "Report uploaded and verified"
    }
}
catch {
    $Status = "FAILED"
    $Failure = $_.Exception.Message

    Add-Result "Pipeline error" "FAIL" $Failure
}
finally {
    $Finished = Get-Date

    $Summary = [pscustomobject]@{
        Pipeline = "CiraInvestmentIntelligence"
        RunId = $RunId
        Status = $Status
        Started = $Started.ToString("o")
        Finished = $Finished.ToString("o")
        AzureStorageAccount = $StorageAccount
        AzureContainer = $Container
        UploadEnabled = [bool]$Upload
        Steps = @($Results.ToArray())
        Error = $Failure
    }

    $JsonPath = Join-Path $ReportDir "pipeline-$RunId.json"
    $TextPath = Join-Path $ReportDir "pipeline-$RunId.txt"

    $Summary | ConvertTo-Json -Depth 8 |
        Set-Content -Path $JsonPath -Encoding UTF8

    $TextLines = @(
        "CIRA INVESTMENT INTELLIGENCE"
        "Run ID: $RunId"
        "Status: $Status"
        "Started: $Started"
        "Finished: $Finished"
        ""
    )

    $TextLines += $Results |
        ForEach-Object {
            "[$($_.Status)] $($_.Step): $($_.Details)"
        }

    $TextLines | Set-Content -Path $TextPath -Encoding UTF8

    Write-Host ""
    Write-Host "============================================="
    Write-Host " PIPELINE STATUS: $Status"
    Write-Host "============================================="
    Write-Host "JSON report: $JsonPath"
    Write-Host "Text report: $TextPath"
}

if ($Status -ne "SUCCESS") {
    exit 1
}


