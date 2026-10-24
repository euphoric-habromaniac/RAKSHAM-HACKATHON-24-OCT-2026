param(
    [string]$Target = "test"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PytestExe = Join-Path $ProjectRoot ".venv\Scripts\pytest.exe"

if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
    $PytestExe = "pytest"
}

$env:PYTHONPATH = $ProjectRoot

switch ($Target.ToLower()) {
    "setup" {
        Write-Host "Setting up environment..." -ForegroundColor Cyan
        python -m venv (Join-Path $ProjectRoot ".venv")
        & $PythonExe -m pip install -r (Join-Path $ProjectRoot "requirements-service.txt")
        & $PythonExe -m pip install "numpy>=1.26.4" "scipy>=1.13.1" "soundfile>=0.12.1" "pandas>=2.2.2" "tqdm>=4.66.5"
    }
    "test" {
        Write-Host "Running pytest test suite..." -ForegroundColor Cyan
        & $PytestExe (Join-Path $ProjectRoot "tests") -q
    }
    "smoke" {
        Write-Host "Running smoke test..." -ForegroundColor Cyan
        & $PythonExe (Join-Path $ProjectRoot "tools\smoke.py")
    }
    "demo-reset" {
        Write-Host "Resetting demo state..." -ForegroundColor Cyan
        & $PythonExe (Join-Path $ProjectRoot "tools\demo_reset.py")
    }
    "preflight" {
        Write-Host "Running preflight checks..." -ForegroundColor Cyan
        & $PythonExe (Join-Path $ProjectRoot "tools\preflight.py")
    }
    "run" {
        Write-Host "Starting Asli Awaaz service on http://localhost:8000..." -ForegroundColor Cyan
        & $PythonExe -m uvicorn service.api:app --host 0.0.0.0 --port 8000 --reload
    }
    Default {
        Write-Host "Unknown target: $Target" -ForegroundColor Red
        Write-Host "Available targets: setup, test, smoke, demo-reset, preflight, run"
        exit 1
    }
}
