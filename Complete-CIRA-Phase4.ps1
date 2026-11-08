# CIRA Phase 4 finalization. PowerShell 5.1+.
# Default: read-only preflight and Terraform plan. -TestEvening permits a short active test.
# -Activate enables both workflows through Terraform after explicit typed approval.
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Join-Path $env:USERPROFILE 'CiraInvestmentIntelligence'),
    [switch]$TestEvening,
    [switch]$Activate,
    [int]$ObservationSeconds = 35
)
$ErrorActionPreference = 'Stop'
$Subscription = 'ff9cce9f-71fe-4f87-ae04-e106a1a6ffb1'
$RG = 'rg-cira-dev'
$Job = 'caj-cira-dev'
$Morning = 'logic-cira-daily-dev'
$Evening = 'logic-cira-evening-dev'
$Workflows = @($Morning, $Evening)
$TfDir = Join-Path $ProjectRoot 'infrastructure\terraform'
$LogFile = Join-Path $ProjectRoot ('Phase4-Completion-{0}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$script:EveningTestPassed = $false
$script:EveningTestCount = 0
$script:OriginalSecret = [Environment]::GetEnvironmentVariable('TF_VAR_cira_sec_user_agent', 'Process')
$script:SecretWasSet = $null -ne $script:OriginalSecret

function Invoke-AzJson {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $raw = & az @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI failed: az $($Arguments[0]) $($Arguments[1])`n$($raw -join [Environment]::NewLine)" }
    $joined = ($raw -join "`n").Trim()
    if (-not $joined) { return $null }
    return ($joined | ConvertFrom-Json)
}
function Get-Workflow([string]$Name) {
    $id = "/subscriptions/$Subscription/resourceGroups/$RG/providers/Microsoft.Logic/workflows/$Name"
    Invoke-AzJson -Arguments @('rest','--method','get','--url',"https://management.azure.com${id}?api-version=2019-05-01",'-o','json')
}
function Get-Executions {
    $data = Invoke-AzJson -Arguments @('containerapp','job','execution','list','--name',$Job,'--resource-group',$RG,'-o','json')
    return @($data | Where-Object { $null -ne $_ -and $_.name })
}
function Assert-Disabled {
    foreach ($name in $Workflows) {
        $w = Get-Workflow $name
        Write-Host "$name : $($w.properties.state)"
        if ($w.properties.state -ne 'Disabled') { throw "Safety stop: $name must be Disabled." }
    }
}
function Invoke-Terraform([string[]]$Arguments) {
    & terraform @Arguments
    if ($LASTEXITCODE -ne 0) { throw "terraform $($Arguments[0]) failed (exit $LASTEXITCODE)" }
}
function Read-Plan([string]$Path) {
    $raw = & terraform show -json $Path
    if ($LASTEXITCODE -ne 0) { throw 'Unable to read Terraform plan.' }
    return (($raw -join "`n") | ConvertFrom-Json)
}
function Assert-SafePlan($Plan, [bool]$AllowWorkflowEnable) {
    $changes = @($Plan.resource_changes | Where-Object { $null -ne $_ -and @($_.change.actions) -notcontains 'no-op' })
    foreach ($r in $changes) {
        $actions = @($r.change.actions)
        Write-Host "Terraform change: $($r.address) [$($actions -join ',')]"
        if ($actions.Count -ne 1 -or $actions[0] -ne 'update') {
            throw "Safety stop: non-update change: $($r.address)"
        }
        if (-not $AllowWorkflowEnable -or $r.type -ne 'azurerm_logic_app_workflow' -or $r.name -notin @('cira_scheduler','cira_evening_scheduler')) {
            throw "Safety stop: unexpected Terraform change: $($r.address)"
        }
        if ($r.change.before.enabled -ne $false -or $r.change.after.enabled -ne $true) {
            throw "Safety stop: change is not simply disabled-to-enabled: $($r.address)"
        }
        $before = $r.change.before | ConvertTo-Json -Depth 100 -Compress | ConvertFrom-Json
        $after = $r.change.after | ConvertTo-Json -Depth 100 -Compress | ConvertFrom-Json
        $before.enabled = $true
        if (($before | ConvertTo-Json -Depth 100 -Compress) -ne ($after | ConvertTo-Json -Depth 100 -Compress)) {
            # JSON property ordering may differ, so this is a deliberately conservative safety stop.
            throw "Safety stop: additional workflow attributes changed: $($r.address)"
        }
    }
    return $changes.Count
}
function Set-WorkflowState([string]$Name, [string]$Operation) {
    $id = "/subscriptions/$Subscription/resourceGroups/$RG/providers/Microsoft.Logic/workflows/$Name"
    $null = Invoke-AzJson -Arguments @('rest','--method','post','--url',"https://management.azure.com${id}/${Operation}?api-version=2019-05-01",'--output','json')
}
function Check-EveningTest {
    Write-Host "`n--- Controlled evening test: no manual trigger ---" -ForegroundColor Cyan
    Assert-Disabled
    $before = @(Get-Executions | ForEach-Object { $_.name })
    $enableAttempted = $false
    try {
        $enableAttempted = $true
        Set-WorkflowState $Evening 'enable'
        Start-Sleep -Seconds $ObservationSeconds
    }
    finally {
        if ($enableAttempted) {
            try { Set-WorkflowState $Evening 'disable' }
            catch { Write-Warning "URGENT: Automatic disable failed: $_. Disable $Evening in Azure Portal immediately."; throw }
        }
    }
    Assert-Disabled
    $new = @(Get-Executions | Where-Object { $_.name -notin $before })
    $script:EveningTestCount = $new.Count
    Write-Host "New executions from evening enable-only test: $($new.Count)"
    $new | ForEach-Object { Write-Host "$($_.name) : $($_.properties.status)" }
    if ($new.Count -ne 1) {
        Write-Warning 'Expected exactly one new execution. Activation blocked. Do not manually trigger the recurrence.'
        return
    }
    $target = $new[0].name
    $deadline = (Get-Date).AddMinutes(7)
    do {
        Start-Sleep -Seconds 12
        $matching = @(Get-Executions | Where-Object { $_.name -eq $target })
        if ($matching.Count -eq 1 -and $matching[0].properties.status -in @('Succeeded','Failed','Canceled','Cancelled')) { break }
    } while ((Get-Date) -lt $deadline)
    if ($matching.Count -ne 1 -or $matching[0].properties.status -ne 'Succeeded') {
        Write-Warning 'Job not confirmed Succeeded. Activation blocked.'
        return
    }
    $script:EveningTestPassed = $true
    Write-Host "PASS: Evening workflow started exactly one successful job: $target" -ForegroundColor Green
    Write-Host 'Note: This test does not prove duplicate-free future scheduling or report freshness.'
}

if ($ObservationSeconds -lt 10 -or $ObservationSeconds -gt 120) { throw 'ObservationSeconds must be 10..120.' }
if (-not (Test-Path $TfDir)) { throw "Terraform directory missing: $TfDir" }
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { $env:PATH = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin;$env:PATH" }
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'Azure CLI not found.' }
if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) { throw 'Terraform not found. Put Terraform 1.17.0 on PATH.' }
$version = (& terraform version -json | ConvertFrom-Json).terraform_version
if ($LASTEXITCODE -ne 0 -or ([version]$version -lt [version]'1.5.0')) { throw "Terraform 1.5+ required, found $version" }
$acct = Invoke-AzJson -Arguments @('account','show','-o','json')
if ($acct.id -ne $Subscription) { throw "Wrong Azure subscription: $($acct.id)" }
$cfgPath = Join-Path $ProjectRoot 'ingestion\config.json'
if (-not (Test-Path $cfgPath)) { throw 'Missing ingestion/config.json with SEC User-Agent.' }
$cfg = Get-Content -Raw $cfgPath | ConvertFrom-Json
if (-not $cfg.sec_user_agent) { throw 'Missing sec_user_agent in ingestion/config.json.' }
$env:TF_VAR_cira_sec_user_agent = [string]$cfg.sec_user_agent
$phase4File = Join-Path $TfDir 'phase4_logic_app_scheduler.tf'
$eveningFile = Join-Path $TfDir 'phase4_evening_scheduler.tf'
if (-not (Test-Path $phase4File) -or -not (Test-Path $eveningFile)) { throw 'Phase 4 Terraform files not found.' }

Push-Location $TfDir
try {
    Start-Transcript -Path $LogFile -ErrorAction Stop | Out-Null
    Write-Host "CIRA Phase 4 completion: $(Get-Date -Format o)" -ForegroundColor Cyan
    Write-Host "Terraform: $version | Subscription: $Subscription"
    Write-Host 'No Azure changes by default. Use -TestEvening for an active test; -Activate requires approval.'
    Assert-Disabled
    foreach ($name in $Workflows) {
        $w = Get-Workflow $name
        if ($w.identity.type -ne 'SystemAssigned' -or -not $w.identity.principalId) { throw "Managed identity missing: $name" }
    }
    Invoke-Terraform -Arguments @('init','-input=false','-lock-timeout=5m')
    Invoke-Terraform -Arguments @('validate','-no-color')
    $baseline = Join-Path $TfDir 'phase4-baseline.tfplan'
    Invoke-Terraform -Arguments @('plan','-input=false','-lock-timeout=5m','-out',$baseline,'-no-color')
    $baselinePlan = Read-Plan $baseline
    $baselineChanges = Assert-SafePlan $baselinePlan $false
    if ($baselineChanges -ne 0) { throw 'Baseline Terraform plan must be zero-change.' }
    Write-Host 'PASS: Terraform baseline is zero-change.' -ForegroundColor Green
    if ($TestEvening) { Check-EveningTest }
    if ($Activate) {
        if (-not $TestEvening -or -not $script:EveningTestPassed) {
            throw 'Activation blocked: run -TestEvening -Activate together and require exactly one successful execution.'
        }
        Write-Warning 'Prior morning test produced two runs because enable and manual trigger were both used. Root cause not conclusively proven.'
        Write-Warning 'Activation changes the workflows to ENABLED and incurs ongoing cloud costs (two schedules per day).'
        $answer = Read-Host 'Type ENABLE-CIRA-PHASE4 to approve Terraform activation (anything else cancels)'
        if ($answer -cne 'ENABLE-CIRA-PHASE4') { throw 'Activation cancelled by user.' }
        # Only edit the explicit enabled flag within the two named workflow resources.
        $original = @{}
        foreach ($file in @($phase4File,$eveningFile)) { $original[$file] = Get-Content -Raw $file }
        try {
            foreach ($file in @($phase4File,$eveningFile)) {
                $content = $original[$file]
                $pattern = '(?m)^(\s*enabled\s*=\s*)false(\s*(?:#.*)?)$'
                $matches = [regex]::Matches($content,$pattern)
                if ($matches.Count -ne 1) { throw "Expected exactly one enabled=false in $file, found $($matches.Count)." }
                $updated = [regex]::Replace($content,$pattern,'${1}true${2}')
                [System.IO.File]::WriteAllText($file,$updated,[System.Text.UTF8Encoding]::new($false))
            }
            Invoke-Terraform -Arguments @('fmt','-check','-no-color')
            Invoke-Terraform -Arguments @('validate','-no-color')
            $activationPlan = Join-Path $TfDir 'phase4-activation.tfplan'
            Invoke-Terraform -Arguments @('plan','-input=false','-lock-timeout=5m','-out',$activationPlan,'-no-color')
            $plan = Read-Plan $activationPlan
            $count = Assert-SafePlan $plan $true
            if ($count -ne 2) { throw "Expected two workflow-only updates, found $count." }
            $confirm = Read-Host 'Plan is two workflow-only updates, zero creates/destroys. Type APPLY to proceed'
            if ($confirm -cne 'APPLY') { throw 'Terraform apply cancelled.' }
            Invoke-Terraform -Arguments @('apply','-input=false','-lock-timeout=5m','-no-color',$activationPlan)
            $script:ApplyCompleted = $true
            foreach ($name in $Workflows) {
                $w = Get-Workflow $name
                Write-Host "$name : $($w.properties.state)"
                if ($w.properties.state -ne 'Enabled') { throw "Post-apply verification failed: $name" }
            }
            Write-Host 'PASS: Both scheduled workflows enabled by Terraform.' -ForegroundColor Green
        }
        catch {
            # Restore local files only if Terraform apply did not run successfully.
            # After an apply, keep Terraform code aligned with deployed state.
            if (-not $script:ApplyCompleted) {
                foreach ($file in $original.Keys) { [System.IO.File]::WriteAllText($file,$original[$file],[System.Text.UTF8Encoding]::new($false)) }
            }
            throw
        }
    }
    else { Write-Host 'Schedules remain disabled. To test and activate: .\Complete-CIRA-Phase4.ps1 -TestEvening -Activate' }
    Write-Host "Phase 4 report: $LogFile"
}
finally {
    if ($script:SecretWasSet) { $env:TF_VAR_cira_sec_user_agent = $script:OriginalSecret }
    else { Remove-Item Env:\TF_VAR_cira_sec_user_agent -ErrorAction SilentlyContinue }
    try { Stop-Transcript | Out-Null } catch {}
    Pop-Location
}
