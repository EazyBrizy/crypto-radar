param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RootDir ".venv\Scripts\python.exe"

function Ensure-Python3Command {
    param([string]$PythonPath)

    $ScriptsDir = Split-Path -Parent $PythonPath
    $Python3Command = Join-Path $ScriptsDir "python3.cmd"
    $Content = "@echo off`r`n""%~dp0python.exe"" %*`r`n"
    Set-Content -LiteralPath $Python3Command -Value $Content -Encoding ascii -NoNewline
}

function Test-BackendPython {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
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

if (-not (Test-BackendPython -Path $Python)) {
    & (Join-Path $PSScriptRoot "setup_backend.ps1")
}

Ensure-Python3Command -PythonPath $Python

if ($PytestArgs.Count -eq 0) {
    $PytestArgs = @("backend/tests", "-q")
}

Push-Location $RootDir
try {
    & $Python -m pytest @PytestArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
