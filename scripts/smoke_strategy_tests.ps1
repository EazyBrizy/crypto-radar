param(
    [string]$ComposeFile = $(Join-Path $PSScriptRoot "..\infra\docker-compose.yml"),
    [string]$BackendUrl = $env:SMOKE_BACKEND_URL
)

$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$ComposeFile = (Resolve-Path $ComposeFile).Path

function Get-EnvOrDefault {
    param([string]$Name, [string]$Default)
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }
    return $value
}

$PollIntervalSeconds = [double](Get-EnvOrDefault -Name "SMOKE_POLL_INTERVAL_SECONDS" -Default "2")
$RunTimeoutSeconds = [int](Get-EnvOrDefault -Name "SMOKE_RUN_TIMEOUT_SECONDS" -Default "180")
$ForwardTimeoutSeconds = [int](Get-EnvOrDefault -Name "SMOKE_FORWARD_TIMEOUT_SECONDS" -Default "90")
$BackendHealthTimeoutSeconds = [int](Get-EnvOrDefault -Name "SMOKE_BACKEND_HEALTH_TIMEOUT_SECONDS" -Default "300")
$LogTailLines = [int](Get-EnvOrDefault -Name "SMOKE_LOG_TAIL_LINES" -Default "160")
$CandlesPerTimeframe = [int](Get-EnvOrDefault -Name "SMOKE_CANDLES_PER_TIMEFRAME" -Default "12")
$WarmupCandles = [int](Get-EnvOrDefault -Name "SMOKE_WARMUP_CANDLES" -Default "3")
$SmokeStartAt = Get-EnvOrDefault -Name "SMOKE_START_AT" -Default "2026-01-01T00:00:00+00:00"
$BackendDevHostPort = Get-EnvOrDefault -Name "SMOKE_BACKEND_DEV_HOST_PORT" -Default "18000"
$FrontendDevHostPort = Get-EnvOrDefault -Name "SMOKE_FRONTEND_DEV_HOST_PORT" -Default "13000"
$KeepAppContainers = (Get-EnvOrDefault -Name "SMOKE_KEEP_APP_CONTAINERS" -Default "false").ToLowerInvariant() -in @("1", "true", "yes")

$PreviousBackendDevHostPort = [Environment]::GetEnvironmentVariable("BACKEND_DEV_HOST_PORT", "Process")
$PreviousFrontendDevHostPort = [Environment]::GetEnvironmentVariable("FRONTEND_DEV_HOST_PORT", "Process")

$env:CRYPTO_RADAR_SCANNER_ENABLED = "false"
$env:EXCHANGE_INSTRUMENT_SYNC_ENABLED = "false"
$env:DERIVATIVE_SNAPSHOT_SYNC_ENABLED = "false"
$env:ORDERBOOK_SNAPSHOT_SYNC_ENABLED = "false"
$env:REAL_POSITION_SYNC_ENABLED = "false"
$env:ENABLE_LIVE_TRADING = "false"
$env:ENABLE_BYBIT_LIVE_ORDER_PLACEMENT = "false"
$env:ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT = "false"
$env:BACKEND_DEV_HOST_PORT = $BackendDevHostPort
$env:FRONTEND_DEV_HOST_PORT = $FrontendDevHostPort

function Write-Info {
    param([string]$Message)
    Write-Host "[strategy-smoke] $Message" -ForegroundColor Cyan
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$AllowFailure,
        [switch]$Capture
    )

    $baseArgs = @("compose", "-f", $ComposeFile)
    if ($Capture) {
        $output = & docker @baseArgs @Arguments
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0 -and -not $AllowFailure) {
            $commandLine = ($baseArgs + $Arguments) -join " "
            throw "docker $commandLine failed with exit code $exitCode"
        }
        return ($output -join "`n")
    }

    & docker @baseArgs @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        $commandLine = ($baseArgs + $Arguments) -join " "
        throw "docker $commandLine failed with exit code $exitCode"
    }
}

function Invoke-BackendDevRun {
    param([Parameter(Mandatory = $true)][string]$Command, [switch]$Capture)
    $args = @(
        "--profile", "dev",
        "run", "--rm", "--no-deps",
        "backend-dev",
        "sh", "-lc",
        "python -m pip install --quiet --no-cache-dir -r requirements.txt >/dev/null && $Command"
    )
    if ($Capture) {
        return Invoke-Compose -Arguments $args -Capture
    }
    Invoke-Compose -Arguments $args
}

function Invoke-BackendDevExec {
    param([Parameter(Mandatory = $true)][string]$Command, [switch]$Capture)
    $args = @(
        "--profile", "dev",
        "exec", "-T",
        "backend-dev",
        "sh", "-lc",
        $Command
    )
    if ($Capture) {
        return Invoke-Compose -Arguments $args -Capture
    }
    Invoke-Compose -Arguments $args
}

function Remove-SmokeAppContainers {
    if ($KeepAppContainers) {
        Write-Info "Keeping backend-dev and strategy-test-worker containers because SMOKE_KEEP_APP_CONTAINERS is enabled"
        return
    }

    Write-Info "Removing smoke app containers"
    Invoke-Compose -Arguments @("--profile", "dev", "rm", "-f", "-s", "backend-dev", "strategy-test-worker") -AllowFailure
}

function Restore-SmokePortEnvironment {
    [Environment]::SetEnvironmentVariable("BACKEND_DEV_HOST_PORT", $PreviousBackendDevHostPort, "Process")
    [Environment]::SetEnvironmentVariable("FRONTEND_DEV_HOST_PORT", $PreviousFrontendDevHostPort, "Process")
}

function Convert-JsonOutput {
    param([Parameter(Mandatory = $true)][string]$Output)
    $start = $Output.IndexOf("{")
    $end = $Output.LastIndexOf("}")
    if ($start -lt 0 -or $end -lt $start) {
        throw "Command output did not contain a JSON object: $Output"
    }
    $json = $Output.Substring($start, $end - $start + 1)
    return $json | ConvertFrom-Json
}

function Invoke-Api {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body = $null,
        [switch]$QuietErrors
    )
    if (-not [string]::IsNullOrWhiteSpace($BackendUrl)) {
        $uri = "$BackendUrl$Path"
        $headers = @{ "x-dev-user" = "usr_demo" }
        if ($null -eq $Body) {
            return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -TimeoutSec 15
        }
        $json = $Body | ConvertTo-Json -Depth 16
        return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -ContentType "application/json" -Body $json -TimeoutSec 30
    }

    $payload = ""
    if ($null -ne $Body) {
        $payload = $Body | ConvertTo-Json -Depth 16 -Compress
    }
    $baseArgs = @(
        "compose", "-f", $ComposeFile,
        "--profile", "dev",
        "exec", "-T",
        "backend-dev",
        "python", "-m", "app.tools.api_request", $Method, $Path
    )
    if ($QuietErrors) {
        $baseArgs += "--quiet-errors"
    }
    if ($payload) {
        $output = $payload | & docker @baseArgs
    } else {
        $output = & docker @baseArgs
    }
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Container API $Method $Path failed with exit code $exitCode"
    }
    return ($output -join "`n") | ConvertFrom-Json
}

function Wait-Until {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Condition,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [Parameter(Mandatory = $true)][string]$Description,
        [string]$RunId = ""
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $last = $null
    while ((Get-Date) -lt $deadline) {
        try {
            $last = & $Condition
            if ($last) {
                return $last
            }
        } catch {
            $last = $_
        }
        Start-Sleep -Seconds $PollIntervalSeconds
    }
    Write-Diagnostics -RunId $RunId
    throw "Timed out after ${TimeoutSeconds}s waiting for $Description. Last value: $last"
}

function Wait-BackendHealth {
    Wait-Until -TimeoutSeconds $BackendHealthTimeoutSeconds -Description "backend /health" -Condition {
        try {
            $health = Invoke-Api -Method Get -Path "/health" -QuietErrors
            if ($health.storage.status -eq "ok" -and $health.scanner_running -eq $false) {
                return $health
            }
        } catch {
            return $false
        }
        return $false
    } | Out-Null
}

function Wait-RunTerminal {
    param([Parameter(Mandatory = $true)][string]$RunId, [Parameter(Mandatory = $true)][int]$TimeoutSeconds)
    return Wait-Until -TimeoutSeconds $TimeoutSeconds -Description "strategy run $RunId terminal status" -RunId $RunId -Condition {
        $detail = Invoke-Api -Method Get -Path "/api/v1/strategy-tests/runs/$RunId"
        $status = [string]$detail.run.status
        if ($status -in @("completed", "failed", "cancelled")) {
            return $detail
        }
        return $false
    }
}

function Wait-RunState {
    param(
        [Parameter(Mandatory = $true)][string]$RunId,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [Parameter(Mandatory = $true)][scriptblock]$Predicate,
        [Parameter(Mandatory = $true)][string]$Description
    )
    return Wait-Until -TimeoutSeconds $TimeoutSeconds -Description $Description -RunId $RunId -Condition {
        $detail = Invoke-Api -Method Get -Path "/api/v1/strategy-tests/runs/$RunId"
        if (& $Predicate $detail) {
            return $detail
        }
        return $false
    }
}

function Assert-True {
    param([bool]$Condition, [string]$Message, [string]$RunId = "")
    if (-not $Condition) {
        Write-Diagnostics -RunId $RunId
        throw $Message
    }
}

function Assert-RunNotStale {
    param(
        [Parameter(Mandatory = $true)][object]$Detail,
        [Parameter(Mandatory = $true)][string]$RunId,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $heartbeatValue = $Detail.run.last_heartbeat_at
    if ($null -eq $heartbeatValue) {
        $heartbeatValue = $Detail.run.runtime_state.last_heartbeat_at
    }
    Assert-True -Condition ($null -ne $heartbeatValue) -Message "$Label run has no heartbeat timestamp" -RunId $RunId
    $heartbeat = [DateTimeOffset]::Parse(
        [string]$heartbeatValue,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AssumeUniversal
    ).ToUniversalTime()
    $thresholdSeconds = [int]$Detail.run.runtime_state.stale_threshold_seconds
    if ($thresholdSeconds -le 0) {
        $thresholdSeconds = 1
    }
    $ageSeconds = ([DateTimeOffset]::UtcNow - $heartbeat).TotalSeconds
    Assert-True -Condition ($ageSeconds -le $thresholdSeconds) -Message "$Label run heartbeat is stale. age_seconds=$ageSeconds threshold_seconds=$thresholdSeconds" -RunId $RunId
}

function Write-Diagnostics {
    param([string]$RunId = "")
    Write-Host ""
    Write-Host "==== strategy smoke diagnostics ====" -ForegroundColor Yellow
    if (-not [string]::IsNullOrWhiteSpace($RunId)) {
        Write-Host "---- run detail $RunId ----"
        try {
            $detail = Invoke-Api -Method Get -Path "/api/v1/strategy-tests/runs/$RunId"
            $detail | ConvertTo-Json -Depth 16
        } catch {
            Write-Host "run detail unavailable: $($_.Exception.Message)"
        }
    }

    Write-Host "---- docker compose ps ----"
    Invoke-Compose -Arguments @("ps") -AllowFailure

    Write-Host "---- backend logs tail ----"
    Invoke-Compose -Arguments @("logs", "--tail", "$LogTailLines", "backend-dev") -AllowFailure

    Write-Host "---- worker logs tail ----"
    Invoke-Compose -Arguments @("logs", "--tail", "$LogTailLines", "strategy-test-worker") -AllowFailure

    if (-not [string]::IsNullOrWhiteSpace($RunId)) {
        Write-Host "---- clickhouse run counts ----"
        $query = @"
SELECT 'strategy_test_trades' AS table_name, count() AS rows FROM analytics.strategy_test_trades WHERE run_id = toUUID('$RunId')
UNION ALL SELECT 'strategy_test_signals', count() FROM analytics.strategy_test_signals WHERE run_id = toUUID('$RunId')
UNION ALL SELECT 'strategy_test_metrics', count() FROM analytics.strategy_test_metrics WHERE run_id = toUUID('$RunId')
FORMAT PrettyCompact
"@
        Invoke-Compose -Arguments @(
            "exec", "-T", "clickhouse",
            "clickhouse-client",
            "--user", "crypto_radar",
            "--password", "crypto_radar",
            "--query", $query
        ) -AllowFailure
    }
}

function Assert-PaginatedEndpoint {
    param([string]$RunId, [string]$Path)
    $first = Invoke-Api -Method Get -Path "$Path`?limit=1&offset=0"
    $second = Invoke-Api -Method Get -Path "$Path`?limit=1&offset=1"
    Assert-True -Condition ($first -is [array] -or $first.Count -ge 0) -Message "$Path did not return a collection" -RunId $RunId
    Assert-True -Condition ($second -is [array] -or $second.Count -ge 0) -Message "$Path offset pagination failed" -RunId $RunId
}

function Clear-PreviousSmokeRun {
    $active = Invoke-Api -Method Get -Path "/api/v1/strategy-tests/runs/active"
    if ($null -eq $active.active_run -or [bool]$active.can_run) {
        return
    }

    $tags = @($active.active_run.requested_matrix.tags)
    $activeRunId = [string]$active.active_run.run_id
    if ($tags -notcontains "docker_smoke") {
        throw "Active non-smoke strategy test run blocks smoke: $activeRunId"
    }

    Write-Info "Cancelling previous docker_smoke active run $activeRunId"
    Invoke-Api -Method Post -Path "/api/v1/strategy-tests/runs/$activeRunId/cancel" | Out-Null
    Invoke-BackendDevExec -Command "python -m app.tools.strategy_smoke forward-heartbeat" | Out-Null
    Wait-RunState -RunId $activeRunId -TimeoutSeconds $ForwardTimeoutSeconds -Description "previous docker_smoke run cancelled" -Predicate {
        param($detail)
        return [string]$detail.run.status -eq "cancelled"
    } | Out-Null
}

Push-Location $RootDir
try {
    Write-Info "Starting infra services"
    Invoke-Compose -Arguments @("--profile", "infra", "up", "-d", "postgres", "redis", "nats", "clickhouse")

    Write-Info "Running Alembic migrations inside backend-dev image"
    Invoke-BackendDevRun -Command "python -m alembic upgrade head"

    Write-Info "Seeding PostgreSQL demo identity through bootstrap path"
    Invoke-BackendDevRun -Command "python -m app.tools.strategy_smoke bootstrap-seed"

    Write-Info "Seeding ClickHouse OHLCV with intentional duplicate timestamps"
    Invoke-BackendDevRun -Command "python -m app.tools.strategy_smoke ensure-analytics-schema"
    $seedOutput = Invoke-BackendDevRun -Command "python -m app.tools.strategy_smoke seed-candles --candles-per-timeframe $CandlesPerTimeframe --warmup-candles $WarmupCandles --start-at $SmokeStartAt" -Capture
    $seed = Convert-JsonOutput -Output $seedOutput
    Write-Info "Seeded $($seed.rows_written) OHLCV rows; deduped candles=$($seed.deduped_candles_total); expected bars=$($seed.expected_bars_total)"

    Write-Info "Starting smoke backend-dev on host port $BackendDevHostPort and strategy-test-worker"
    Invoke-Compose -Arguments @("--profile", "dev", "up", "-d", "--build", "--force-recreate", "backend-dev", "strategy-test-worker")
    Wait-BackendHealth
    Clear-PreviousSmokeRun

    $historicalPayload = @{
        test_type = "historical_backtest"
        strategies = @("trend_pullback_continuation")
        pairs = @(@{ exchange = "bybit"; symbol = "BTCUSDT" })
        timeframes = @("5m", "15m")
        start_at = $seed.start_at
        end_at = $seed.end_at
        mode = "research_virtual"
        initial_capital = "1000"
        fee_rate = "0.001"
        slippage_bps = "0"
        same_candle_policy = "conservative_stop_first"
        params = @{
            warmup_candles = $WarmupCandles
            rolling_window_candles = $WarmupCandles
            historical_pending_entries_enabled = $true
            pending_entry_max_wait_bars = 4
            auto_publish_calibration = $false
        }
        metric_set = @("trades_count", "signals_count", "expectancy_r")
        tags = @("docker_smoke", "backtest")
    }

    Write-Info "Estimating historical backtest matrix"
    $estimate = Invoke-Api -Method Post -Path "/api/v1/strategy-tests/runs/estimate" -Body $historicalPayload
    Assert-True -Condition ([int]$estimate.scenario_count -eq 2) -Message "Estimate scenario_count mismatch. expected=2 actual=$($estimate.scenario_count)"
    Assert-True -Condition ([int]$estimate.total_bars -ge [int]$seed.expected_bars_total) -Message "Estimate total_bars should be theoretical and at least the seeded executable bars. expected_min=$($seed.expected_bars_total) actual=$($estimate.total_bars)"
    foreach ($scenario in $estimate.scenarios) {
        Assert-True -Condition ($null -eq $scenario.raw_rows) -Message "Estimate should not query raw OHLCV rows for $($scenario.timeframe)"
        Assert-True -Condition ($null -eq $scenario.duplicate_rows) -Message "Estimate should not query duplicate OHLCV rows for $($scenario.timeframe)"
        Assert-True -Condition ([int]$scenario.bars_total -ge 0) -Message "Estimate scenario bars_total is negative for $($scenario.timeframe)"
    }

    Write-Info "Posting historical_backtest smoke run"
    $historicalRun = Invoke-Api -Method Post -Path "/api/v1/strategy-tests/runs" -Body $historicalPayload
    $historicalRunId = [string]$historicalRun.run_id
    $historicalDetail = Wait-RunTerminal -RunId $historicalRunId -TimeoutSeconds $RunTimeoutSeconds
    Assert-True -Condition ($historicalDetail.run.status -eq "completed") -Message "historical_backtest did not complete: $($historicalDetail.run.status)" -RunId $historicalRunId
    $scenarioBarsTotal = 0
    foreach ($scenario in @($historicalDetail.run.summary.scenarios)) {
        $scenarioBarsTotal += [int]$scenario.bars_total
    }
    Assert-True -Condition ($scenarioBarsTotal -eq [int]$seed.expected_bars_total) -Message "Historical summary bars_total was not deduped. expected=$($seed.expected_bars_total) actual=$scenarioBarsTotal" -RunId $historicalRunId
    Assert-RunNotStale -Detail $historicalDetail -RunId $historicalRunId -Label "Historical"

    $report = Invoke-Api -Method Get -Path "/api/v1/strategy-tests/reports/$historicalRunId"
    Assert-True -Condition ([string]$report.run_id -eq $historicalRunId) -Message "Historical report was not returned" -RunId $historicalRunId

    $funnel = Invoke-Api -Method Get -Path "/api/v1/strategy-tests/runs/$historicalRunId/funnel"
    Assert-True -Condition ([int]$funnel.execution_candidates -le [int]$funnel.signals_count) -Message "Funnel candidates exceed signals" -RunId $historicalRunId
    Assert-True -Condition ([int]$funnel.filled -le [int]$funnel.entry_touched) -Message "Funnel filled exceeds entry_touched" -RunId $historicalRunId
    Assert-True -Condition ([int]$funnel.closed -le [int]$funnel.filled) -Message "Funnel closed exceeds filled" -RunId $historicalRunId
    Assert-PaginatedEndpoint -RunId $historicalRunId -Path "/api/v1/strategy-tests/runs/$historicalRunId/trades"
    Assert-PaginatedEndpoint -RunId $historicalRunId -Path "/api/v1/strategy-tests/runs/$historicalRunId/signals"

    $forwardPayload = @{
        test_type = "forward_virtual"
        strategies = @("trend_pullback_continuation")
        pairs = @(@{ exchange = "bybit"; symbol = "BTCUSDT" })
        timeframes = @("15m")
        start_at = (Get-Date).ToUniversalTime().AddMinutes(-15).ToString("o")
        end_at = (Get-Date).ToUniversalTime().AddHours(1).ToString("o")
        mode = "research_virtual"
        initial_capital = "1000"
        fee_rate = "0.001"
        slippage_bps = "0"
        same_candle_policy = "conservative_stop_first"
        params = @{
            execution_policy = @{ mode = "pending_retest" }
            max_concurrent_positions = 3
            risk_settings = @{
                max_price_deviation_bps = 10000
                max_open_risk_percent = 100
                max_daily_loss_percent = 50
                max_account_drawdown_percent = 90
            }
        }
        metric_set = @("trades_count", "signals_count", "expectancy_r")
        tags = @("docker_smoke", "forward")
    }

    Write-Info "Posting forward_virtual smoke run"
    $forwardRun = Invoke-Api -Method Post -Path "/api/v1/strategy-tests/runs" -Body $forwardPayload
    $forwardRunId = [string]$forwardRun.run_id
    $forwardStarted = Wait-RunState -RunId $forwardRunId -TimeoutSeconds $ForwardTimeoutSeconds -Description "forward run listening or waiting" -Predicate {
        param($detail)
        $status = [string]$detail.run.status
        $runtimeStatus = [string]$detail.run.runtime_state.status
        return $status -eq "running" -and $runtimeStatus -in @("listening", "waiting_for_market_data")
    }
    Assert-RunNotStale -Detail $forwardStarted -RunId $forwardRunId -Label "Forward"

    Write-Info "Feeding forward tick, pending signal, then fill tick through backend runtime helper"
    Invoke-BackendDevExec -Command "python -m app.tools.strategy_smoke forward-tick --price 105 --timestamp 1781000000" | Out-Null
    $afterTick = Wait-RunState -RunId $forwardRunId -TimeoutSeconds $ForwardTimeoutSeconds -Description "forward tick processing" -Predicate {
        param($detail)
        return [int]$detail.run.runtime_state.processed_ticks -ge 1
    }
    Assert-True -Condition ([string]$afterTick.run.runtime_state.last_heartbeat_reason -eq "market_data_received") -Message "Forward tick did not update heartbeat reason" -RunId $forwardRunId

    Invoke-BackendDevExec -Command "python -m app.tools.strategy_smoke forward-signal" | Out-Null
    $afterSignal = Wait-RunState -RunId $forwardRunId -TimeoutSeconds $ForwardTimeoutSeconds -Description "forward pending signal" -Predicate {
        param($detail)
        return [int]$detail.run.runtime_state.processed_signals -ge 1 -and [int]$detail.run.runtime_state.pending_entries_armed -ge 1
    }
    Assert-True -Condition ([string]$afterSignal.run.runtime_state.last_forward_event -eq "signal_pending") -Message "Forward signal did not arm pending entry" -RunId $forwardRunId

    Invoke-BackendDevExec -Command "python -m app.tools.strategy_smoke forward-tick --price 100.5 --timestamp 1781000060" | Out-Null
    $afterFill = Wait-RunState -RunId $forwardRunId -TimeoutSeconds $ForwardTimeoutSeconds -Description "forward pending fill" -Predicate {
        param($detail)
        $pending = @($detail.run.runtime_state.pending_entries)
        $filled = $pending | Where-Object { $_.status -eq "filled" }
        $positions = @($detail.run.runtime_state.forward_positions)
        return [int]$detail.run.runtime_state.opened_trades -ge 1 -and [int]$detail.run.runtime_state.trades_written -ge 1 -and @($filled).Count -ge 1 -and @($positions).Count -ge 1
    }
    Assert-True -Condition ([string]$afterFill.run.runtime_state.last_forward_event -eq "trade_opened") -Message "Forward fill did not open a trade" -RunId $forwardRunId

    Write-Info "Cancelling forward run"
    $cancel = Invoke-Api -Method Post -Path "/api/v1/strategy-tests/runs/$forwardRunId/cancel"
    Assert-True -Condition ($cancel.status -in @("stopping", "cancelled")) -Message "Forward cancel returned unexpected status $($cancel.status)" -RunId $forwardRunId
    Invoke-BackendDevExec -Command "python -m app.tools.strategy_smoke forward-heartbeat" | Out-Null
    $cancelled = Wait-RunState -RunId $forwardRunId -TimeoutSeconds $ForwardTimeoutSeconds -Description "forward cancelled" -Predicate {
        param($detail)
        return [string]$detail.run.status -eq "cancelled"
    }
    Assert-True -Condition ([string]$cancelled.run.status -eq "cancelled") -Message "Forward run was not cancelled" -RunId $forwardRunId

    Write-Info "Strategy smoke completed. historical=$historicalRunId forward=$forwardRunId"
} catch {
    Write-Diagnostics
    throw
} finally {
    Remove-SmokeAppContainers
    Restore-SmokePortEnvironment
    Pop-Location
}
