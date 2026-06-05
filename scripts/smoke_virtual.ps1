param()

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Test-PythonExecutable {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $false
    }
    try {
        & $Path -c "import pytest, fastapi, sqlalchemy" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

$PythonCandidates = @(
    (Join-Path $RootDir "backend\.venv\Scripts\python.exe"),
    (Join-Path $RootDir ".venv\Scripts\python.exe"),
    (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
    (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
    (Get-Command py -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
)

$Python = $PythonCandidates | Where-Object { Test-PythonExecutable -Path $_ } | Select-Object -First 1
if (-not $Python) {
    throw "Python was not found. Create backend\.venv or install Python."
}

$Corepack = Get-Command corepack -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
if (-not $Corepack) {
    throw "Corepack was not found. Install Node.js with Corepack to run frontend smoke tests."
}

Push-Location $RootDir
try {
    $PreviousPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = @(
        (Join-Path $RootDir "backend"),
        $RootDir,
        $PreviousPythonPath
    ) -join ";"

    & $Python -m pytest backend/tests/test_virtual_trading_api_realtime_smoke.py
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    Push-Location (Join-Path $RootDir "frontend")
    try {
        & $Corepack pnpm test src/realtime/event-router.test.ts src/features/app-shell/RadarRoute.test.ts
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
    Pop-Location
}
