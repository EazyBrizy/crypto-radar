param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [switch]$KillExisting,
    [switch]$Headed,
    [switch]$KeepOpen,
    [string]$Screenshot = ".codex-app-smoke.png"
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SmokeScript = Join-Path $PSScriptRoot "app-smoke.mjs"

function Test-NodeExecutable {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $false
    }
    try {
        & $Path --version *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

$NodeCandidates = @(
    $env:CRYPTO_RADAR_NODE,
    (Join-Path ([Environment]::GetFolderPath("UserProfile")) ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"),
    (Get-Command node -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
)

$Node = $NodeCandidates | Where-Object { Test-NodeExecutable -Path $_ } | Select-Object -First 1
if (-not $Node) {
    throw "Node.js was not found. Install Node.js or set CRYPTO_RADAR_NODE."
}

$Arguments = @(
    $SmokeScript,
    "--backend-port", [string]$BackendPort,
    "--frontend-port", [string]$FrontendPort,
    "--screenshot", $Screenshot
)

if ($KillExisting) {
    $Arguments += "--kill-existing"
}
if ($Headed) {
    $Arguments += "--headed"
}
if ($KeepOpen) {
    $Arguments += "--keep-open"
}

Push-Location $RootDir
try {
    & $Node $Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
