# =====================================================================
# TATKAL PROXY - LOCAL SETUP SCRIPT (Windows PowerShell)
# =====================================================================

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   🚀 TATKAL PROXY - AUTOMATED WINDOWS SETUP SCRIPT       " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check Python version
Write-Host "`n[1/6] Checking Python installation..." -ForegroundColor Yellow
$pythonCmd = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} else {
    Write-Host "❌ Error: Python is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.11+ from https://www.python.org/downloads/ and check 'Add Python to PATH'." -ForegroundColor Red
    Exit 1
}

$pyVersion = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "Found Python $pyVersion" -ForegroundColor Green

# 2. Setup Virtual Environment
Write-Host "`n[2/6] Setting up virtual environment..." -ForegroundColor Yellow
if (-not (Test-Path "venv")) {
    Write-Host "Creating venv..." -ForegroundColor Gray
    & $pythonCmd -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Failed to create virtual environment." -ForegroundColor Red
        Exit 1
    }
}
Write-Host "Virtual environment ready." -ForegroundColor Green

# 3. Create required directories
Write-Host "`n[3/6] Ensuring project directories..." -ForegroundColor Yellow
$folders = @("database", "handlers", "services", "keyboards", "webhooks", "utils", "assets", "uploads", "logs", "tests", "deployment")
foreach ($folder in $folders) {
    if (-not (Test-Path $folder)) {
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
    }
}
Write-Host "Directories verified." -ForegroundColor Green

# 4. Install Dependencies
Write-Host "`n[4/6] Installing dependencies..." -ForegroundColor Yellow
$pipPath = ".\venv\Scripts\pip.exe"
& $pipPath install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️ Warning: pip install encountered an issue. Retrying with verbose output..." -ForegroundColor Yellow
    & $pipPath install -r requirements.txt
}
Write-Host "Dependencies installed successfully." -ForegroundColor Green

# 5. Setup .env file
Write-Host "`n[5/6] Verifying environment configuration (.env)..." -ForegroundColor Yellow
$envPath = ".env"
if (-not (Test-Path $envPath)) {
    Write-Host "Creating .env from .env.example..." -ForegroundColor Gray
    Copy-Item ".env.example" $envPath
    
    # Generate new Fernet encryption key using the venv python
    $newKey = & ".\venv\Scripts\python.exe" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    if ($newKey) {
        $envContent = Get-Content $envPath
        $envContent = $envContent -replace "ENCRYPTION_KEY=.*", "ENCRYPTION_KEY=$newKey"
        $envContent | Set-Content $envPath
        Write-Host "Generated unique ENCRYPTION_KEY." -ForegroundColor Green
    }
    Write-Host "Created .env file. Please edit it with your BOT_TOKEN and ADMIN_IDS!" -ForegroundColor Cyan
} else {
    Write-Host ".env file already exists." -ForegroundColor Green
}

# 6. Initialize Database
Write-Host "`n[6/6] Initializing local SQLite database and plans..." -ForegroundColor Yellow
& ".\venv\Scripts\python.exe" -c "from database.connection import init_db; init_db(); print('Database tables and seed plans initialized.')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Database initialization encountered an error." -ForegroundColor Red
    Exit 1
}

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "   ✅ TATKAL PROXY SETUP COMPLETED SUCCESSFULLY!          " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "`nNext steps:" -ForegroundColor White
Write-Host "1. Open .env and fill in:" -ForegroundColor White
Write-Host "   - BOT_TOKEN (from @BotFather)" -ForegroundColor Cyan
Write-Host "   - ADMIN_IDS (your numeric Telegram ID, e.g. from @userinfobot)" -ForegroundColor Cyan
Write-Host "   - UPI_ID (your UPI payment address, e.g. yourname@upi)" -ForegroundColor Cyan
Write-Host "2. Start the local bot with:" -ForegroundColor White
Write-Host "   .\start.ps1" -ForegroundColor Yellow
Write-Host ""
