[CmdletBinding()]
param(
    [switch]$Prepare,
    [switch]$Execute,
    [switch]$Serve,
    [string]$DataRoot = "D:\InfinityResearchAI",
    [string]$Distribution = "",
    [string]$ExpectedCommit = "",
    [ValidateRange(1024, 65535)][int]$Port = 8000
)
$ErrorActionPreference = "Stop"
$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if ($null -eq $wsl) {
    Write-Host "[BLOCKED] WSL2 + Linux distribution aur Docker WSL integration required hain. docs/COMPANY_HOST_SETUP.md dekho."
    exit 2
}
if ($DataRoot -notmatch '^[A-Za-z]:[\\/]' -or [string]::IsNullOrWhiteSpace($DataRoot)) {
    Write-Host "[BLOCKED] DataRoot absolute Windows path hona chahiye."
    exit 2
}
$driveRoot = [System.IO.Path]::GetPathRoot($DataRoot)
if ($DataRoot.TrimEnd('\', '/') -eq $driveRoot.TrimEnd('\', '/') -or -not (Test-Path -LiteralPath $driveRoot -PathType Container)) {
    Write-Host "[BLOCKED] Existing data drive par ek folder chuno; drive root allowed nahi hai."
    exit 2
}
if ($ExpectedCommit -and $ExpectedCommit -notmatch '^[0-9a-fA-F]{40}$') {
    Write-Host "[BLOCKED] ExpectedCommit full Git SHA hona chahiye."
    exit 2
}
$distroArgs = @()
if (-not [string]::IsNullOrWhiteSpace($Distribution)) { $distroArgs += @("--distribution", $Distribution) }
# Direct argv throughout: paths/user input never become shell command text.
$repoLinux = & $wsl.Source @distroArgs --exec wslpath -a -u $PSScriptRoot
if ($LASTEXITCODE -ne 0 -or -not $repoLinux) { Write-Host "[BLOCKED] Linux distribution/path conversion unavailable."; exit 2 }
$dataLinux = & $wsl.Source @distroArgs --exec wslpath -a -u $DataRoot
if ($LASTEXITCODE -ne 0 -or -not $dataLinux) { Write-Host "[BLOCKED] Data drive Linux mein available nahi hai."; exit 2 }
$driveLinux = & $wsl.Source @distroArgs --exec wslpath -a -u $driveRoot
if ($LASTEXITCODE -ne 0 -or -not $driveLinux) { Write-Host "[BLOCKED] Data drive conversion failed."; exit 2 }
& $wsl.Source @distroArgs --exec mountpoint -q -- ([string]$driveLinux)
if ($LASTEXITCODE -ne 0) { Write-Host "[BLOCKED] Chuni hui drive WSL mein mounted nahi hai. Koi fallback drive use nahi hogi."; exit 2 }
$arguments = @("--cd", [string]$repoLinux, "--exec", "python3", "scripts/run_company_host.py", "--data-root", [string]$dataLinux, "--port", [string]$Port)
if ($Prepare) { $arguments += "--prepare" }
if ($Execute) { $arguments += @("--execute-host", "--check-local-api", "--execute-live") }
if ($Serve) { $arguments += "--serve" }
if ($ExpectedCommit) { $arguments += @("--expected-commit", $ExpectedCommit) }
& $wsl.Source @distroArgs @arguments
exit $LASTEXITCODE
