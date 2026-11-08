[CmdletBinding()]
param(
    [switch]$TestEvening,
    [switch]$Activate,
    [ValidateRange(10,120)][int]$ObservationSeconds = 120
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot '../infrastructure/terraform/Complete-CIRA-Phase4.ps1') @PSBoundParameters
