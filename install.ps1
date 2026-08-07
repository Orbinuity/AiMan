$ErrorActionPreference = "Stop"

$Repo = "Orbinuity/AiMan"
$AppId = "aiman"
$AppName = "AiMan"
$BinaryName = "$AppId.exe"
$InstallDir = "$env:LOCALAPPDATA\Programs\$AppName"
$TargetBinary = "$InstallDir\$BinaryName"
$InstallerVersion = "1.0-windows"

function Write-Header ($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Success ($msg) { Write-Host "[✓] $msg" -ForegroundColor Green }
function Write-Info ($msg)    { Write-Host "[*] $msg" -ForegroundColor DarkCyan }
function Write-Warn ($msg)    { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err ($msg)     { Write-Host "[✗] $msg" -ForegroundColor Red; exit 1 }

Write-Header "$AppName installer v$InstallerVersion"

Write-Info "Checking GitHub for the latest release..."
try {
    $Release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "PowerShell" }
    $LatestTag = $Release.tag_name
} catch {
    Write-Err "Failed to reach GitHub API: $_"
}

if (Test-Path $TargetBinary) {
    try {
        $LocalVersion = & $TargetBinary --version 2>$null
    } catch {
        $LocalVersion = ""
    }

    if ($LocalVersion -and $LocalVersion.Contains($LatestTag)) {
        Write-Success "$AppName is already installed and up to date ($LatestTag)!"
        Write-Host ""
        exit 0
    } else {
        Write-Warn "Existing installation detected. Upgrading to $LatestTag..."
    }
}

$Asset = $Release.assets | Where-Object { $_.name -like "*windows*" -or $_.name -like "*.exe" } | Select-Object -First 1

if (-not $Asset) {
    Write-Err "No Windows executable found in release $LatestTag"
}

Write-Info "Downloading $AppName $LatestTag..."
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
}

try {
    Invoke-WebRequest -Uri $Asset.browser_download_url -OutFile $TargetBinary
    Write-Success "Binary successfully saved to $InstallDir"
} catch {
    Write-Err "Failed to download binary: $_"
}

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$InstallDir*") {
    Write-Info "Adding $InstallDir to User PATH..."
    $NewPath = "$UserPath;$InstallDir"
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    Write-Warn "PATH updated. Restart open terminals for changes to take effect."
}

Write-Success "Installation complete!"
Write-Host "`nRun '$AppId' to launch.`n" -ForegroundColor Green