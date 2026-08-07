$AppName = "AiMan"
$InstallDir = "$env:LOCALAPPDATA\Programs\$AppName"
$UninstallerVersion = "1.0-windows"

Write-Host "`n=== $AppName Uninstaller v$UninstallerVersion ===" -ForegroundColor Cyan

if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir
    Write-Host "[✓] AiMan has been uninstalled." -ForegroundColor Green
} else {
    Write-Host "[!] AiMan was not found." -ForegroundColor Yellow
}