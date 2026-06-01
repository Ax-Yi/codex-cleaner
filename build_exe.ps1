$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "======================================="
Write-Host " WindowsCleanerAssistant Build Script"
Write-Host "======================================="

# 1. Check Python
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "Python was not found. Please install Python 3.10 or later."
    exit 1
}

Write-Host "Python found:"
python --version

# 2. Clean old build files
Write-Host "Cleaning old build files..."

$itemsToRemove = @(
    "build",
    "dist",
    "WindowsCleanerAssistant.spec"
)

foreach ($item in $itemsToRemove) {
    $path = Join-Path $ProjectRoot $item
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force
        Write-Host "Removed: $item"
    }
}

# 3. Create virtual environment
$venvPath = Join-Path $ProjectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
} else {
    Write-Host "Virtual environment already exists."
}

# 4. Upgrade pip
Write-Host "Upgrading pip..."
& $venvPython -m pip install --upgrade pip

# 5. Install requirements
$requirementsPath = Join-Path $ProjectRoot "requirements.txt"
if (Test-Path $requirementsPath) {
    Write-Host "Installing requirements..."
    & $venvPython -m pip install -r requirements.txt
} else {
    Write-Host "requirements.txt was not found."
    exit 1
}

# 6. Make sure PyInstaller is installed
Write-Host "Checking PyInstaller..."
& $venvPython -m pip install pyinstaller

# 7. Build exe
Write-Host "Building exe..."

& $venvPython -m PyInstaller `
    --onefile `
    --noconsole `
    --name WindowsCleanerAssistant `
    run.py

# 8. Check output
$exePath = Join-Path $ProjectRoot "dist\WindowsCleanerAssistant.exe"

if (Test-Path $exePath) {
    Write-Host "======================================="
    Write-Host "Build completed successfully."
    Write-Host "Output:"
    Write-Host $exePath
    Write-Host "======================================="
} else {
    Write-Host "Build failed. EXE file was not found."
    exit 1
}