[CmdletBinding()]
param(
    [switch]$Execute,
    [string]$DataRoot = "D:\InfinityResearchAI",
    [string]$Receipt = "",
    [ValidateSet("MAXIMUM", "MARATHON")]
    [string]$DepthMode = "MAXIMUM"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    Write-Host "[BLOCKED] DataRoot khaali nahi ho sakta." -ForegroundColor Yellow
    exit 2
}

$venvPython = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $pythonCommand = $venvPython
} else {
    $pythonLookup = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonLookup) {
        Write-Host "[BLOCKED] Python nahi mila. Pehle project venv/Python setup karo." -ForegroundColor Yellow
        exit 2
    }
    $pythonCommand = $pythonLookup.Source
}

$gateArguments = @(
    "scripts\run_live_zero_cost_gate.py",
    "--data-root",
    $DataRoot,
    "--depth-mode",
    $DepthMode.ToUpperInvariant()
)
if ($Execute) {
    $gateArguments += "--execute"
}
if (-not [string]::IsNullOrWhiteSpace($Receipt)) {
    $gateArguments += @("--receipt", $Receipt)
}

Write-Host "Checking strict confirmed-zero-cost live prerequisites..."
& $pythonCommand @gateArguments
$gateExitCode = $LASTEXITCODE

if ($gateExitCode -eq 0) {
    Write-Host ""
    Write-Host "Live gate command safely complete hua." -ForegroundColor Green
} elseif ($gateExitCode -eq 2) {
    Write-Host ""
    Write-Host "Live calls block kar di gayi. Upar wale preflight blockers theek karo." -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Live gate chala, lekin release checks pass nahi hue." -ForegroundColor Red
}

exit $gateExitCode
