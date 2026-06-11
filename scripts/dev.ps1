param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [string]$BackendHost = "127.0.0.1",
    [string]$FrontendHost = "127.0.0.1",
    [switch]$WithInfra,
    [switch]$NoScanner
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$BackendVenvDir = Join-Path $RootDir ".venv"
$BackendVenvPython = Join-Path $BackendVenvDir "Scripts\python.exe"
$BackendRequirements = Join-Path $BackendDir "requirements.txt"
$BackendDevRequirements = Join-Path $BackendDir "requirements-dev.txt"
$BackendDependencyStamp = Join-Path $BackendVenvDir ".crypto-radar-deps.stamp"
$BackendPython = $BackendVenvPython
$ComposeFile = Join-Path $RootDir "infra\docker-compose.yml"
$CmdExe = if ($env:ComSpec) { $env:ComSpec } else { Join-Path $env:SystemRoot "System32\cmd.exe" }

function Write-Info {
    param([string]$Message)
    Write-Host "[dev] $Message" -ForegroundColor Cyan
}

function Write-WarningLine {
    param([string]$Message)
    Write-Host "[dev] $Message" -ForegroundColor Yellow
}

function Assert-Command {
    param(
        [string]$Name,
        [string]$InstallHint
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. $InstallHint"
    }
}

function Test-PortBusy {
    param([int]$Port)

    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    return $null -ne $connection
}

function Test-PythonExecutable {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }

    try {
        $nativePreference = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
        if ($nativePreference) {
            $previousNativePreference = $PSNativeCommandUseErrorActionPreference
            $PSNativeCommandUseErrorActionPreference = $false
        }

        & $Path -c "import sys; raise SystemExit(0)" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
    finally {
        if ($nativePreference) {
            $PSNativeCommandUseErrorActionPreference = $previousNativePreference
        }
    }
}

function Get-BundledPythonCandidates {
    $WorkspaceUserDir = Split-Path (Split-Path $RootDir -Parent) -Parent
    return @(
        (Join-Path $WorkspaceUserDir ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
        (Join-Path ([Environment]::GetFolderPath("UserProfile")) ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
    )
}

function Resolve-HostPython {
    $PathPython = Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
    $candidates = @(
        $env:CRYPTO_RADAR_BACKEND_PYTHON,
        $PathPython
    )

    foreach ($candidate in ($candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        if (Test-PythonExecutable -Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Resolve-BundledPython {
    foreach ($candidate in (Get-BundledPythonCandidates)) {
        if (Test-PythonExecutable -Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Invoke-VenvCreationWithPython {
    param([string]$PythonPath)

    try {
        & $PythonPath -m venv $BackendVenvDir
        return $LASTEXITCODE -eq 0
    }
    catch {
        Write-WarningLine "Could not create .venv with $PythonPath`: $($_.Exception.Message)"
        return $false
    }
}

function Invoke-PyLauncherVenv {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        return $false
    }

    try {
        & py -3.12 -c "import sys; raise SystemExit(0)" *> $null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        & py -3.12 -m venv $BackendVenvDir
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function New-BackendVenv {
    if (Test-Path -LiteralPath $BackendVenvDir) {
        $resolvedVenvDir = (Resolve-Path -LiteralPath $BackendVenvDir).Path
        if (-not $resolvedVenvDir.StartsWith($RootDir, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove path outside workspace: $resolvedVenvDir"
        }

        Write-WarningLine "Removing broken backend environment at $resolvedVenvDir..."
        Remove-Item -LiteralPath $resolvedVenvDir -Recurse -Force
    }

    $HostPython = Resolve-HostPython
    if ($HostPython) {
        Write-Info "Creating backend environment: $BackendVenvDir"
        if (Invoke-VenvCreationWithPython -PythonPath $HostPython) {
            return
        }
    }

    Write-Info "Trying Python Launcher for Python 3.12..."
    if (Invoke-PyLauncherVenv) {
        return
    }

    $BundledPython = Resolve-BundledPython
    if ($BundledPython) {
        Write-Info "Creating backend environment with bundled Python: $BackendVenvDir"
        if (Invoke-VenvCreationWithPython -PythonPath $BundledPython) {
            return
        }
    }

    throw "Could not create .venv. Install Python 3.12 or set CRYPTO_RADAR_BACKEND_PYTHON to a runnable python.exe."
}

function Get-DependencyFingerprint {
    $files = @($BackendRequirements, $BackendDevRequirements)
    $lines = foreach ($file in $files) {
        if (-not (Test-Path -LiteralPath $file)) {
            throw "Dependency file was not found: $file"
        }

        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $file
        "$([System.IO.Path]::GetFileName($file)):$($hash.Hash)"
    }

    return ($lines -join "`n")
}

function Test-BackendDependencies {
    if (-not (Test-PythonExecutable -Path $BackendVenvPython)) {
        return $false
    }

    try {
        & $BackendVenvPython -c "import alembic, fastapi, pytest, pydantic_settings, sqlalchemy, uvicorn; raise SystemExit(0)" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Sync-BackendDependencies {
    $fingerprint = Get-DependencyFingerprint
    $stampMatches = $false

    if (Test-Path -LiteralPath $BackendDependencyStamp) {
        $stampMatches = ((Get-Content -Raw -LiteralPath $BackendDependencyStamp).Trim() -eq $fingerprint.Trim())
    }

    if ($stampMatches -and (Test-BackendDependencies)) {
        return
    }

    Write-Info "Installing backend dependencies into $BackendVenvDir..."
    & $BackendVenvPython -m pip install -r $BackendDevRequirements
    if ($LASTEXITCODE -ne 0) {
        throw "Backend dependency installation failed with exit code $LASTEXITCODE."
    }

    Set-Content -LiteralPath $BackendDependencyStamp -Value $fingerprint -Encoding utf8
}

function Initialize-BackendEnvironment {
    if (-not (Test-PythonExecutable -Path $BackendVenvPython)) {
        Write-WarningLine ".venv Python is not runnable; recreating the single backend environment."
        New-BackendVenv
    }

    Sync-BackendDependencies
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }

    return $false
}

function Stop-ProcessTree {
    param([System.Diagnostics.Process]$Process)

    if ($null -eq $Process -or $Process.HasExited) {
        return
    }

    Write-WarningLine "Stopping process tree PID $($Process.Id)..."
    try {
        $nativePreference = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
        if ($nativePreference) {
            $previousNativePreference = $PSNativeCommandUseErrorActionPreference
            $PSNativeCommandUseErrorActionPreference = $false
        }

        & taskkill.exe /PID $Process.Id /T /F *> $null
    }
    catch {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
    finally {
        if ($nativePreference) {
            $PSNativeCommandUseErrorActionPreference = $previousNativePreference
        }
    }
}

function Join-ProcessArguments {
    param([string[]]$Arguments)

    $quoted = foreach ($argument in $Arguments) {
        if ($null -eq $argument) {
            continue
        }

        $value = [string]$argument
        if ($value.Length -eq 0) {
            '""'
        }
        elseif ($value -match '[\s"]') {
            '"' + ($value -replace '"', '\"') + '"'
        }
        else {
            $value
        }
    }

    return ($quoted -join " ")
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [hashtable]$Environment = @{},
        [ConsoleColor]$Color = [ConsoleColor]::Gray
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    $startInfo.Arguments = Join-ProcessArguments -Arguments $Arguments

    $processEnvironment = $startInfo.Environment
    if ($null -eq $processEnvironment) {
        $processEnvironment = $startInfo.EnvironmentVariables
    }
    Normalize-PathEnvironment -Environment $processEnvironment

    foreach ($key in $Environment.Keys) {
        $processEnvironment[$key] = [string]$Environment[$key]
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $process.EnableRaisingEvents = $true

    $stdoutEvent = Register-ObjectEvent -InputObject $process -EventName OutputDataReceived -MessageData @{
        Name = $Name
        Color = $Color
    } -Action {
        if ([string]::IsNullOrWhiteSpace($EventArgs.Data)) {
            return
        }

        $meta = $Event.MessageData
        Write-Host "[$($meta.Name)] $($EventArgs.Data)" -ForegroundColor $meta.Color
    }

    $stderrEvent = Register-ObjectEvent -InputObject $process -EventName ErrorDataReceived -MessageData @{
        Name = $Name
        Color = [ConsoleColor]::DarkYellow
    } -Action {
        if ([string]::IsNullOrWhiteSpace($EventArgs.Data)) {
            return
        }

        $meta = $Event.MessageData
        Write-Host "[$($meta.Name)] $($EventArgs.Data)" -ForegroundColor $meta.Color
    }

    [void]$process.Start()
    $process.BeginOutputReadLine()
    $process.BeginErrorReadLine()

    return [pscustomobject]@{
        Name = $Name
        Process = $process
        Events = @($stdoutEvent, $stderrEvent)
    }
}

function Normalize-PathEnvironment {
    param($Environment)

    $pathKeys = @($Environment.Keys | Where-Object { [string]$_ -ieq "PATH" })
    if ($pathKeys.Count -le 1) {
        return
    }

    $preferredKey = ($pathKeys | Where-Object { [string]$_ -ceq "Path" } | Select-Object -First 1)
    if (-not $preferredKey) {
        $preferredKey = $pathKeys[0]
    }
    $preferredValue = [string]$Environment[$preferredKey]

    foreach ($pathKey in $pathKeys) {
        if ([string]$pathKey -cne [string]$preferredKey) {
            [void]$Environment.Remove($pathKey)
        }
    }

    $Environment[$preferredKey] = $preferredValue
}

function Invoke-BackendCommand {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [hashtable]$Environment = @{}
    )

    Write-Info $Name
    $previousEnvironment = @{}
    foreach ($key in $Environment.Keys) {
        $previousEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
    }

    Push-Location $BackendDir
    try {
        & $BackendPython @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previousEnvironment[$key], "Process")
        }
    }
}

Initialize-BackendEnvironment

Assert-Command -Name "node" -InstallHint "Install Node.js 24.x and open a new PowerShell."
Assert-Command -Name "corepack" -InstallHint "Corepack should come with Node.js. Check your Node.js installation."

if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "node_modules"))) {
    throw "frontend\node_modules was not found. Install dependencies: cd frontend; corepack pnpm install"
}

if (Test-PortBusy -Port $BackendPort) {
    throw "Backend port $BackendPort is already busy. Stop the old process or run: .\scripts\dev.ps1 -BackendPort 8001"
}

if (Test-PortBusy -Port $FrontendPort) {
    throw "Frontend port $FrontendPort is already busy. Stop the old process or run: .\scripts\dev.ps1 -FrontendPort 3001"
}

if ($WithInfra) {
    Assert-Command -Name "docker" -InstallHint "Install Docker Desktop and wait until Docker Engine is running."
    Write-Info "Starting PostgreSQL, Redis, NATS JetStream and ClickHouse..."
    & docker compose -f $ComposeFile --profile infra up -d postgres redis nats clickhouse
}

$backendEnv = @{
    PYTHONUNBUFFERED = "1"
    MAX_SCANNER_PAIRS = "20"
    TRUNCATE_SCANNER_PAIRS_OVER_LIMIT = "false"
    SCANNER_WARMUP_CONCURRENCY = "2"
    SCANNER_WARMUP_TIMEOUT_SECONDS = "8"
    EXCHANGE_INSTRUMENT_SYNC_ENABLED = "false"
    DERIVATIVE_SNAPSHOT_SYNC_ENABLED = "false"
    ORDERBOOK_SNAPSHOT_SYNC_ENABLED = "false"
    REAL_POSITION_SYNC_ENABLED = "false"
    ENABLE_LIVE_TRADING = "false"
    ENABLE_BYBIT_LIVE_ORDER_PLACEMENT = "false"
    ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT = "false"
    REQUIRE_PROTECTIVE_STOP_FOR_LIVE_ENTRY = "true"
}

if ($NoScanner) {
    $backendEnv["CRYPTO_RADAR_SCANNER_ENABLED"] = "false"
}
else {
    $backendEnv["CRYPTO_RADAR_SCANNER_ENABLED"] = "true"
}

Invoke-BackendCommand `
    -Name "Applying database migrations..." `
    -Arguments @("-m", "alembic", "upgrade", "head") `
    -Environment $backendEnv

$frontendEnv = @{
    NEXT_DEV_HOST = $FrontendHost
    PORT = [string]$FrontendPort
    NEXT_PUBLIC_FASTAPI_HTTP_URL = "http://$BackendHost`:$BackendPort"
    NEXT_PUBLIC_FASTAPI_WS_URL = "ws://$BackendHost`:$BackendPort/api/v1/realtime/ws"
    NEXT_PUBLIC_FASTAPI_TIMEOUT_MS = "8000"
}

$managed = @()

try {
    Write-Info "Starting backend: http://$BackendHost`:$BackendPort"
    $managed += Start-ManagedProcess `
        -Name "backend" `
        -FilePath $BackendPython `
        -Arguments @("-m", "uvicorn", "app.main:app", "--reload", "--host", $BackendHost, "--port", [string]$BackendPort) `
        -WorkingDirectory $BackendDir `
        -Environment $backendEnv `
        -Color Green

    $healthUrl = "http://$BackendHost`:$BackendPort/health"
    if (Wait-HttpOk -Url $healthUrl -TimeoutSeconds 30) {
        Write-Info "Backend is ready: $healthUrl"
    }
    else {
        Write-WarningLine "Backend did not respond within 30 seconds. Check logs below."
    }

    Write-Info "Starting frontend: http://$FrontendHost`:$FrontendPort"
    $frontendCommand = "corepack pnpm run dev --hostname $FrontendHost --port $FrontendPort"
    $managed += Start-ManagedProcess `
        -Name "frontend" `
        -FilePath $CmdExe `
        -Arguments @("/d", "/s", "/c", $frontendCommand) `
        -WorkingDirectory $FrontendDir `
        -Environment $frontendEnv `
        -Color Magenta

    Write-Info "Ready. Frontend: http://$FrontendHost`:$FrontendPort | Backend docs: http://$BackendHost`:$BackendPort/docs"
    Write-Info "Stop: Ctrl+C"

    while ($true) {
        Start-Sleep -Seconds 1

        foreach ($item in $managed) {
            if ($item.Process.HasExited) {
                throw "$($item.Name) exited with code $($item.Process.ExitCode)."
            }
        }
    }
}
finally {
    foreach ($item in $managed) {
        Stop-ProcessTree -Process $item.Process

        foreach ($event in $item.Events) {
            Unregister-Event -SourceIdentifier $event.Name -ErrorAction SilentlyContinue
            Remove-Job -Id $event.Id -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Info "Local dev run stopped."
}
