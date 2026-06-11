param(
    [string]$PythonVersion = "3.12"
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonInstallDir = Join-Path $RootDir ".uv-python"
$UvCacheDir = Join-Path $RootDir ".uv-cache"
$VenvDir = Join-Path $RootDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $RootDir "backend\requirements-dev.txt"

function Ensure-Python3Command {
    param([string]$PythonPath)

    $ScriptsDir = Split-Path -Parent $PythonPath
    $Python3Command = Join-Path $ScriptsDir "python3.cmd"
    $Content = "@echo off`r`n""%~dp0python.exe"" %*`r`n"
    Set-Content -LiteralPath $Python3Command -Value $Content -Encoding ascii -NoNewline
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found. Install uv first and open a new PowerShell."
}

$previousUvCacheDir = $env:UV_CACHE_DIR
$previousUvPythonInstallDir = $env:UV_PYTHON_INSTALL_DIR

try {
    $env:UV_CACHE_DIR = $UvCacheDir
    $env:UV_PYTHON_INSTALL_DIR = $PythonInstallDir

    Push-Location $RootDir
    try {
        uv python install $PythonVersion --install-dir $PythonInstallDir --no-bin
        uv venv --python $PythonVersion --clear $VenvDir
        uv pip install --python $VenvPython -r $Requirements
        Ensure-Python3Command -PythonPath $VenvPython
        & $VenvPython -c "import sys; print(f'Backend Python: {sys.executable} ({sys.version.split()[0]})')"
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:UV_CACHE_DIR = $previousUvCacheDir
    $env:UV_PYTHON_INSTALL_DIR = $previousUvPythonInstallDir
}
