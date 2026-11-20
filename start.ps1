# =====================================================================
# TATKAL PROXY - APPLICATION LAUNCHER (Windows PowerShell)
# =====================================================================

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   🚀 STARTING TATKAL PROXY (Premium Proxy Store)        " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Check if venv exists
if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "Virtual environment not found! Running setup.ps1 first..." -ForegroundColor Yellow
    .\setup.ps1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Setup failed. Cannot start application." -ForegroundColor Red
        Exit 1
    }
}

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env. Please configure BOT_TOKEN and ADMIN_IDS in .env before running!" -ForegroundColor Cyan
}

# Check if BOT_TOKEN is configured
$botToken = (Get-Content ".env" | Select-String "^BOT_TOKEN=").Line
if ($botToken -match "BOT_TOKEN=1234567890:" -or $botToken -eq "BOT_TOKEN=") {
    Write-Host "`n⚠️ NOTICE: BOT_TOKEN is not set or still default in .env!" -ForegroundColor Yellow
    Write-Host "Please edit .env and set your Telegram BOT_TOKEN from @BotFather." -ForegroundColor Yellow
    Write-Host "Example: BOT_TOKEN=7123456789:AAHabcdefghij_klmnopqrstuvwxyz" -ForegroundColor White
    $confirm = Read-Host "`nDo you still want to attempt starting the bot? (y/N)"
    if ($confirm -ne "y" -and $confirm -ne "Y") {
        Write-Host "Startup aborted. Edit .env and re-run .\start.ps1." -ForegroundColor Gray
        Exit 0
    }
}

Write-Host "`nStarting Tatkal Proxy Bot & Services..." -ForegroundColor Green
& ".\venv\Scripts\python.exe" bot.py
