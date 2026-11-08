[CmdletBinding()]
param(
    [switch]$TestEvening,
    [switch]$Activate,
    [ValidateRange(10,120)][int]$ObservationSeconds = 120
)
$ErrorActionPreference = 'Stop'
$originalSecret = $env:TF_VAR_cira_sec_user_agent
$originalSubscription = $env:ARM_SUBSCRIPTION_ID
$originalFiles = @{}
$applyStarted = $false
$localTerraform = Join-Path $PSScriptRoot '../../.tools/terraform-1.13.5/terraform.exe'
$terraformCommand = 'terraform'
if (Test-Path -LiteralPath $localTerraform) { $terraformCommand = (Resolve-Path $localTerraform).Path }
function Invoke-AzJson([string[]]$Arguments) {
    $output = & az @Arguments --only-show-errors -o json
    if ($LASTEXITCODE -ne 0) { throw "Azure command failed: $($Arguments[0])" }
    if ($output) { return ($output -join "`n" | ConvertFrom-Json) }
}
function Invoke-Tf([string[]]$Arguments) {
    & $terraformCommand @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Terraform failed: $($Arguments[0])" }
}
function Read-Plan([string]$Path) {
    $output = & $terraformCommand show -json $Path
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read Terraform plan.' }
    return ($output -join "`n" | ConvertFrom-Json)
}
function Get-Changes($Plan) {
    @($Plan.resource_changes | Where-Object { ($_.change.actions -join ',') -ne 'no-op' })
}
function Get-Workflow([string]$Id) {
    Invoke-AzJson @('rest','--method','get','--url',"https://management.azure.com${Id}?api-version=2019-05-01")
}
function Set-Workflow([string]$Id,[string]$Action) {
    $null = Invoke-AzJson @('rest','--method','post','--url',"https://management.azure.com${Id}/${Action}?api-version=2019-05-01")
}
function Get-Executions {
    @(Invoke-AzJson @('containerapp','job','execution','list','--name','caj-cira-dev','--resource-group','rg-cira-dev'))
}
Push-Location $PSScriptRoot
try {
    $cfg = Get-Content (Join-Path $PSScriptRoot '../../ingestion/config.json') -Raw | ConvertFrom-Json
    if (-not $cfg.sec_user_agent) { throw 'Missing sec_user_agent in ingestion/config.json.' }
    $env:TF_VAR_cira_sec_user_agent = $cfg.sec_user_agent
    $varFile = Join-Path $PSScriptRoot 'environments/dev.tfvars'
    $varText = Get-Content $varFile -Raw
    $subMatch = [regex]::Match($varText,'(?m)^subscription_id\s*=\s*"([^"]+)"')
    if (-not $subMatch.Success) { throw 'Missing subscription_id in dev.tfvars.' }
    $account = Invoke-AzJson @('account','show')
    if ($account.id -ne $subMatch.Groups[1].Value) { throw 'Azure CLI subscription does not match dev.tfvars.' }
    $env:ARM_SUBSCRIPTION_ID = $account.id
    Invoke-Tf @('init','-input=false','-lock-timeout=5m')
    Invoke-Tf @('validate','-no-color')
    $baselinePath = Join-Path $PSScriptRoot 'phase4-baseline.tfplan'
    Invoke-Tf @('plan',"-var-file=$varFile",'-input=false','-lock-timeout=5m',"-out=$baselinePath",'-no-color')
    $baseline = Read-Plan $baselinePath
    if (@(Get-Changes $baseline).Count -ne 0) { throw 'Baseline must have zero changes. Resolve drift before activation.' }
    $resources = @($baseline.planned_values.root_module.resources)
    $addresses = @('azurerm_logic_app_workflow.cira_scheduler','azurerm_logic_app_workflow.cira_evening_scheduler')
    $workflows = @($resources | Where-Object { $_.address -in $addresses })
    $job = @($resources | Where-Object { $_.address -eq 'azurerm_container_app_job.cira' })
    if ($workflows.Count -ne 2 -or $job.Count -ne 1) { throw 'Expected two workflows and one container job in plan.' }
    $script:jobId = $job[0].values.id
    foreach ($w in $workflows) {
        $live = Get-Workflow $w.values.id
        if ($live.identity.type -ne 'SystemAssigned' -or -not $live.identity.principalId) { throw "Missing managed identity: $($w.values.name)" }
    }
    $disabled = @($workflows | Where-Object { -not $_.values.enabled })
    if ($disabled.Count -eq 0) { Write-Host 'Both schedules are already enabled; no activation needed.'; return }
    if ($disabled.Count -ne 2) { throw 'Expected both workflows disabled before testing.' }
    if ($TestEvening) {
        $evening = ($workflows | Where-Object { $_.address -eq $addresses[1] }).values.id
        $before = @(Get-Executions | ForEach-Object { $_.name })
        try {
            Write-Host "Enabling evening workflow for up to $ObservationSeconds seconds; no manual trigger will be sent."
            Set-Workflow $evening 'enable'
            $deadline = (Get-Date).AddSeconds($ObservationSeconds)
            do {
                Start-Sleep -Seconds 10
                $new = @(Get-Executions | Where-Object { $_.name -notin $before })
            } while ($new.Count -eq 0 -and (Get-Date) -lt $deadline)
        } finally {
            Set-Workflow $evening 'disable'
            if ((Get-Workflow $evening).properties.state -ne 'Disabled') { throw 'URGENT: Evening workflow could not be confirmed disabled.' }
        }
        $new = @(Get-Executions | Where-Object { $_.name -notin $before })
        if ($new.Count -ne 1) { throw "Expected exactly one new job execution, found $($new.Count). Schedules remain disabled." }
        $target = $new[0].name
        $deadline = (Get-Date).AddMinutes(7)
        do {
            $matching = @(Get-Executions | Where-Object { $_.name -notin $before })
            if ($matching.Count -ne 1) { throw 'Unexpected execution count during test; activation blocked.' }
            $status = $matching[0].properties.status
            Write-Host "Evening test: $target : $status"
            if ($status -in @('Succeeded','Failed','Canceled','Cancelled')) { break }
            Start-Sleep -Seconds 12
        } while ((Get-Date) -lt $deadline)
        if ($status -ne 'Succeeded') { throw "Evening test did not succeed: $status" }
        Write-Host 'PASS: Exactly one successful evening execution.'
    }
    if (-not $Activate) { Write-Host 'Validation complete. Schedules remain disabled.'; return }
    if (-not $TestEvening) { throw 'Activation requires -TestEvening together with -Activate.' }
    foreach ($file in @('phase4_logic_app_scheduler.tf','phase4_evening_scheduler.tf')) {
        $path = Join-Path $PSScriptRoot $file
        $content = Get-Content $path -Raw
        $originalFiles[$path] = $content
        $pattern = '(?m)^(\s*enabled\s*=\s*)false(\s*(?:#.*)?)$'
        if ([regex]::Matches($content,$pattern).Count -ne 1) { throw "Expected one enabled=false in $file." }
        [IO.File]::WriteAllText($path,[regex]::Replace($content,$pattern,'${1}true${2}'),[Text.UTF8Encoding]::new($false))
    }
    Invoke-Tf @('validate','-no-color')
    $activationPath = Join-Path $PSScriptRoot 'phase4-activation.tfplan'
    Invoke-Tf @('plan',"-var-file=$varFile",'-input=false','-lock-timeout=5m',"-out=$activationPath",'-no-color')
    $changes = @(Get-Changes (Read-Plan $activationPath))
    if ($changes.Count -ne 2) { throw 'Activation plan must contain exactly two updates.' }
    foreach ($change in $changes) {
        if ($change.address -notin $addresses -or ($change.change.actions -join ',') -ne 'update') { throw 'Unexpected activation resource or action.' }
        if ($change.change.before.enabled -ne $false -or $change.change.after.enabled -ne $true) { throw 'Unexpected enabled transition.' }
        foreach ($property in $change.change.before.PSObject.Properties.Name) {
            if ($property -eq 'enabled') { continue }
            $old = ConvertTo-Json -InputObject $change.change.before.$property -Depth 100 -Compress
            $newValue = ConvertTo-Json -InputObject $change.change.after.$property -Depth 100 -Compress
            if ($old -cne $newValue) { throw "Unexpected property change: $property" }
        }
    }
    $applyStarted = $true
    Invoke-Tf @('apply','-input=false','-lock-timeout=5m','-no-color',$activationPath)
    foreach ($w in $workflows) {
        $live = Get-Workflow $w.values.id
        Write-Host "$($w.values.name): $($live.properties.state)"
        if ($live.properties.state -ne 'Enabled') { throw 'Post-apply verification failed.' }
    }
    Write-Host 'PASS: Both schedules enabled: 09:00 and 21:30 Copenhagen time.'
} finally {
    if (-not $applyStarted) {
        foreach ($path in $originalFiles.Keys) { [IO.File]::WriteAllText($path,$originalFiles[$path],[Text.UTF8Encoding]::new($false)) }
    }
    $env:TF_VAR_cira_sec_user_agent = $originalSecret
    $env:ARM_SUBSCRIPTION_ID = $originalSubscription
    Pop-Location
}

