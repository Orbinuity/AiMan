$InstallDir = "$env:LOCALAPPDATA\Programs\AiMan"

if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir
    Write-Host "[✓] AiMan has been uninstalled." -ForegroundColor Green
} else {
    Write-Host "[!] AiMan was not found." -ForegroundColor Yellow
}