param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RootDir ".venv\Scripts\python.exe"
$Requirements = Join-Path $RootDir "backend\requirements-dev.txt"

function Ensure-Python3Command {
    param([string]$PythonPath)

    $ScriptsDir = Split-Path -Parent $PythonPath
    $Python3Command = Join-Path $ScriptsDir "python3.cmd"
    $Content = "@echo off`r`n""%~dp0python.exe"" %*`r`n"
    Set-Content -LiteralPath $Python3Command -Value $Content -Encoding ascii -NoNewline
}

if (-not (Test-Path -LiteralPath $Python)) {
    & (Join-Path $PSScriptRoot "setup_backend.ps1")
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found. Install uv first and open a new PowerShell."
}

Push-Location $RootDir
try {
    uv pip install --python $Python -r $Requirements
}
finally {
    Pop-Location
}

Ensure-Python3Command -PythonPath $Python

if ($PytestArgs.Count -eq 0) {
    $PytestArgs = @("backend/tests")
}

Push-Location $RootDir
try {
    & $Python -m pytest @PytestArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
