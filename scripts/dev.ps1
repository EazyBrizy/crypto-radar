param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [string]$BackendHost = "127.0.0.1",
    [string]$FrontendHost = "127.0.0.1",
    [switch]$WithInfra,
    [switch]$NoInfra,
    [switch]$NoScanner
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$BackendVenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"
$BackendPython = $BackendVenvPython
$BackendPythonPath = $null
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

function Invoke-DockerCompose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $baseArgs = @("compose", "-f", $ComposeFile)
    & docker @baseArgs @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        $commandLine = ($baseArgs + $Arguments) -join " "
        throw "docker $commandLine failed with exit code $exitCode."
    }

    return $exitCode -eq 0
}

function Remove-DockerDevAppContainers {
    Write-Info "Clearing Docker dev app containers that can occupy local app ports..."
    Invoke-DockerCompose -Arguments @("--profile", "dev", "rm", "-f", "-s", "backend-dev", "frontend-dev", "strategy-test-worker") -AllowFailure | Out-Null
}

if (Test-PythonExecutable -Path $BackendVenvPython) {
    $BackendPython = $BackendVenvPython
}
else {
    $WorkspaceUserDir = Split-Path (Split-Path $RootDir -Parent) -Parent
    $BundledCandidates = @(
        $env:CRYPTO_RADAR_BACKEND_PYTHON,
        (Join-Path $WorkspaceUserDir ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
        (Join-Path ([Environment]::GetFolderPath("UserProfile")) ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    $BundledPython = $BundledCandidates | Where-Object { Test-PythonExecutable -Path $_ } | Select-Object -First 1

    if ($BundledPython) {
        $BackendPython = $BundledPython
        $BackendPythonPath = @(
            (Join-Path $RootDir ".venv\Lib\site-packages"),
            $BackendDir
        ) -join ";"
        Write-WarningLine ".venv Python is not runnable; using bundled Python with .venv site-packages."
    }
    else {
        throw ".venv was not found or is not runnable. Create it first: powershell -ExecutionPolicy Bypass -File .\scripts\setup_backend.ps1"
    }
}

Assert-Command -Name "node" -InstallHint "Install Node.js 24.x and open a new PowerShell."
Assert-Command -Name "corepack" -InstallHint "Corepack should come with Node.js. Check your Node.js installation."

if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "node_modules"))) {
    throw "frontend\node_modules was not found. Install dependencies: cd frontend; corepack pnpm install"
}

$StartInfra = $WithInfra -or -not $NoInfra

if ($StartInfra) {
    Assert-Command -Name "docker" -InstallHint "Install Docker Desktop and wait until Docker Engine is running."
    Remove-DockerDevAppContainers
    Write-Info "Starting PostgreSQL, Redis, NATS JetStream and ClickHouse..."
    Invoke-DockerCompose -Arguments @("--profile", "infra", "up", "-d", "postgres", "redis", "nats", "clickhouse") | Out-Null
}

if (Test-PortBusy -Port $BackendPort) {
    throw "Backend port $BackendPort is already busy. Stop the old process or run: .\scripts\dev.ps1 -BackendPort 8001"
}

if (Test-PortBusy -Port $FrontendPort) {
    throw "Frontend port $FrontendPort is already busy. Stop the old process or run: .\scripts\dev.ps1 -FrontendPort 3001"
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

if ($BackendPythonPath) {
    $backendEnv["PYTHONPATH"] = $BackendPythonPath
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

    Write-Info "Starting strategy-test-worker"
    $managed += Start-ManagedProcess `
        -Name "strategy-test-worker" `
        -FilePath $BackendPython `
        -Arguments @("-m", "app.workers.strategy_test_worker") `
        -WorkingDirectory $BackendDir `
        -Environment $backendEnv `
        -Color Cyan

    Write-Info "Starting frontend: http://$FrontendHost`:$FrontendPort"
    $frontendCommand = "corepack pnpm run dev --hostname $FrontendHost --port $FrontendPort"
    $managed += Start-ManagedProcess `
        -Name "frontend" `
        -FilePath $CmdExe `
        -Arguments @("/d", "/s", "/c", $frontendCommand) `
        -WorkingDirectory $FrontendDir `
        -Environment $frontendEnv `
        -Color Magenta

    Write-Info "Ready. Frontend: http://$FrontendHost`:$FrontendPort | Backend docs: http://$BackendHost`:$BackendPort/docs | Worker: strategy-test-worker"
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
