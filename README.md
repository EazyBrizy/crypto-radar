# Crypto Radar

Crypto Radar is a realtime crypto market radar and trading control plane. The backend ingests exchange data, builds strategy signals, tracks pending entries, simulates trades, records outcomes, and gates real execution through backend-owned risk and safety checks. The frontend is a Next.js dashboard for viewing state and sending user intents.

## Current Stack

- Backend: Python, FastAPI, Pydantic, SQLAlchemy, Alembic, Redis, ClickHouse, NATS-ready infrastructure.
- Frontend: Next.js App Router, React, TypeScript, pnpm, TanStack Query, Zustand, OpenAPI-generated client.
- Storage: PostgreSQL for application state, Redis for hot/realtime state, ClickHouse for market and analytics data.
- Infra: Docker Compose for local PostgreSQL, Redis, NATS JetStream, ClickHouse, Grafana, Prometheus, Loki, OTEL collector.

## Project Docs

- [Project structure](docs/PROJECT_STRUCTURE.md)
- [Backend guide](docs/BACKEND.md)
- [Database guide](docs/DATABASE.md)
- [Frontend guide](docs/frontend.md)
- [Strategies guide](docs/STRATEGIES.md)
- [Workers guide](docs/WORKERS.md)

## Prerequisites

- Python 3.12
- Node.js 24.x with Corepack
- pnpm 10.x through Corepack
- Docker Desktop for local infra

## Local MVP Virtual Trading Runbook

Use this order for a clean local check of scanner plus virtual trading. Keep the backend and frontend commands in separate PowerShell terminals once they start long-running servers.

1. Install dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt

cd frontend
corepack enable
corepack pnpm install

cd ..
```

2. Start DB/Redis and local supporting stores:

```powershell
docker compose -f infra\docker-compose.yml --profile infra up -d postgres redis nats clickhouse
```

3. Apply migrations:

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m alembic current
..\.venv\Scripts\python.exe -m alembic heads
cd ..
```

`alembic current` must match `alembic heads`. The current head includes the fix 3.0 migrations `add_soft_delete_to_exchange_connections` and `add_exchange_connection_execution_safety`. Backend startup also logs a warning when it can verify that the database is not at Alembic head.

4. Start backend with the local MVP scanner profile:

```powershell
cd backend
$env:CRYPTO_RADAR_SCANNER_ENABLED="false"
$env:MAX_SCANNER_PAIRS="20"
$env:TRUNCATE_SCANNER_PAIRS_OVER_LIMIT="false"
$env:SCANNER_WARMUP_CONCURRENCY="2"
$env:SCANNER_WARMUP_TIMEOUT_SECONDS="8"
$env:EXCHANGE_INSTRUMENT_SYNC_ENABLED="false"
$env:DERIVATIVE_SNAPSHOT_SYNC_ENABLED="false"
$env:ORDERBOOK_SNAPSHOT_SYNC_ENABLED="false"
$env:REAL_POSITION_SYNC_ENABLED="false"
$env:ENABLE_LIVE_TRADING="false"
$env:ENABLE_BYBIT_LIVE_ORDER_PLACEMENT="false"
$env:ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT="false"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

5. Start frontend:

```powershell
cd frontend
$env:NEXT_PUBLIC_FASTAPI_HTTP_URL="http://127.0.0.1:8000"
$env:NEXT_PUBLIC_FASTAPI_WS_URL="ws://127.0.0.1:8000/api/v1/realtime/ws"
$env:NEXT_PUBLIC_FASTAPI_SSE_URL="http://127.0.0.1:8000/api/v1/realtime/events"
$env:NEXT_PUBLIC_FASTAPI_TIMEOUT_MS="8000"
corepack pnpm dev
```

Frontend URL: `http://127.0.0.1:3000`

6. Verify `/health`:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected for the local MVP profile: storage is `ok`, `scanner_running` is `false`, optional sync workers are disabled, and `real_position_sync_enabled` is `false`.

7. Verify `/api/v1/radar/status`:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/radar/status
```

Expected before scanner start: `scanner_running=false`, `scanner_pairs_count` is small, and `max_scanner_pairs=20`.

8. Start scanner explicitly:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/radar/scanner/start
Invoke-RestMethod http://127.0.0.1:8000/api/v1/radar/status
```

Expected after start: `scanner_running=true`; `stage` moves through `warming_up`, `listening`, or `degraded` if optional external market data is unavailable.

9. Run virtual trading smoke:

```powershell
make smoke-virtual
```

Equivalent PowerShell command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_virtual.ps1
```

## Operator Guide

Use the Strategy Testing panel in Dashboard Settings for new strategy-test work. The supported API path is `/api/v1/strategy-tests`; `strategy_lab` is legacy compatibility and should not be used for new backtest, forward-test, report, or calibration flows.

### Run A Historical Strategy Test

1. Open Dashboard Settings and find Strategy Testing.
2. Select the Historical backtest tab.
3. Choose strategies, pairs, timeframes, historical start/end dates, mode, same-candle policy, and advanced parameters.
4. Start the run. Historical runs execute through `/api/v1/strategy-tests/runs` with `test_type="historical_backtest"`.
5. Review the final report, conversion funnel, signals, trades, metrics, PnL, and equity curve.

### Run A Forward Virtual Test

1. Select the Forward test tab.
2. Choose start/end or a duration preset and confirm the isolated virtual-account warning.
3. Start the run. Forward runs use `test_type="forward_virtual"` and background processing through the strategy forward test worker.
4. Watch the compact live dashboard from `/api/v1/strategy-tests/runs/{run_id}/status`.
5. Cancel running forward tests from the runs table when needed.

Forward virtual tests never place real orders, arm real pending entries, or publish every test signal into the main radar feed.

### Publish Calibration

1. Wait until a strategy test run is completed.
2. Open its report and choose "Use this run for calibration".
3. The backend publishes eligibility profiles and returns eligible/blocked counts.
4. New radar signals can then receive edge statuses from strategy-test profiles: `unknown`, `insufficient_sample`, `positive`, or `negative`.

### Understand Why `execution_ready` Is 0

`execution_ready` is intentionally strict. Check these in order:

- Radar filter: blocked low-score ideas are diagnostics and appear only in the blocked/diagnostics view.
- Signal details: `execution_gate.reasons` explains blockers such as forming candle, trigger not confirmed, trade plan incomplete, risk/reward failure, regime incompatibility, dedup suppression, or negative edge.
- Strategy trigger: each strategy has its own trigger rules; high score alone is not enough.
- Market regime: strategies only pass in compatible regimes.
- Calibration: missing or insufficient strategy-test profiles can keep edge unknown or insufficient, especially in strict walk-forward mode.
- Notifications: duplicate execution notifications are suppressed by Redis bucketed idempotency within `NOTIFICATION_DEDUP_WINDOW_SECONDS`.

## One-Command Dev

After backend and frontend dependencies are installed, this command starts infra, applies Alembic migrations, starts backend with scanner disabled, and starts frontend:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -WithInfra -NoScanner
```

Remove `-NoScanner` when you want the scanner to autostart with the bounded local profile.

## Environment Defaults

Use `.env.example` as the safe local template: copy it to `.env` in the repository root. Do not commit real exchange credentials.

Important backend defaults for the local MVP:

```env
CRYPTO_RADAR_SCANNER_ENABLED=false
MAX_SCANNER_PAIRS=20
TRUNCATE_SCANNER_PAIRS_OVER_LIMIT=false
SCANNER_WARMUP_CONCURRENCY=2
SCANNER_WARMUP_TIMEOUT_SECONDS=8
EXCHANGE_INSTRUMENT_SYNC_ENABLED=false
DERIVATIVE_SNAPSHOT_SYNC_ENABLED=false
ORDERBOOK_SNAPSHOT_SYNC_ENABLED=false
REAL_POSITION_SYNC_ENABLED=false
ENABLE_LIVE_TRADING=false
ENABLE_BYBIT_LIVE_ORDER_PLACEMENT=false
ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT=false
```

Important frontend defaults:

```env
NEXT_PUBLIC_FASTAPI_HTTP_URL=http://127.0.0.1:8000
NEXT_PUBLIC_FASTAPI_WS_URL=ws://127.0.0.1:8000/api/v1/realtime/ws
NEXT_PUBLIC_FASTAPI_SSE_URL=http://127.0.0.1:8000/api/v1/realtime/events
NEXT_PUBLIC_FASTAPI_TIMEOUT_MS=8000
```

Optional workers are external-data helpers. Keep them disabled for the fast local virtual flow. Enable exchange instrument sync, derivative snapshot sync, or orderbook snapshot sync only when validating exchange-rule, derivative-context, orderbook, or real-execution readiness behavior.

## Migrations

PostgreSQL schema changes must go through Alembic:

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic revision -m "describe_change"
..\.venv\Scripts\python.exe -m alembic upgrade head
```

Check local migration state:

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic current
..\.venv\Scripts\python.exe -m alembic heads
```

Make targets are available for the same checks:

```powershell
make migrate
make migrations-current
make migrations-heads
```

Update SQLAlchemy models in `backend/app/models/` and keep migrations in `backend/alembic/versions/`.

## Tests

Backend:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
```

Frontend:

```powershell
cd frontend
corepack pnpm test
corepack pnpm lint
```

Full-stack smoke:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1
```

Virtual trading mechanics smoke:

```powershell
make smoke-virtual
```

## Virtual, Testnet, Mainnet

- Virtual pending execution is implemented. The local MVP flow should use virtual mode and the scanner tick path to validate pending-entry behavior.
- Real pending execution from scanner tick triggers is not implemented. Do not treat real pending entries as live trigger automation.
- Real order placement is disabled unless `ENABLE_LIVE_TRADING=true`, `ENABLE_BYBIT_LIVE_ORDER_PLACEMENT=true`, the exchange connection allows live placement, and all backend risk/safety checks pass.
- Mainnet order placement additionally requires `ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT=true` and explicit mainnet opt-in on the exchange connection.
- Testnet and mainnet are separate exchange connection environments. Local virtual smoke checks do not require exchange credentials and do not place orders.
- Notifications are not proof that the Radar signal feed works. Use `/health`, `/api/v1/radar/status`, scanner status, and `make smoke-virtual` as the local proof points.

## Current Limitations

- Email and Telegram notification providers are stubbed; WebSocket/SSE delivery is active.
- NATS is provisioned in local and deploy infra, while current realtime fanout uses Redis Pub/Sub plus WebSocket/SSE.
- Mainnet order placement requires explicit backend flags and an exchange connection configured for live placement.
