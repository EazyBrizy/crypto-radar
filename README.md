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
- [Frontend guide](docs/FRONTEND.md)

## Prerequisites

- Python 3.12
- Node.js 24.x with Corepack
- pnpm 10.x through Corepack
- Docker Desktop for local infra

## Run backend tests

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test_backend.ps1
```

If `make` is available, the equivalent wrapper is:

```powershell
make test-backend
```

Both commands install `backend/requirements-dev.txt` into the local `.venv` and run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests
```

## Local MVP Virtual Trading Runbook

Use this order for a clean local check of scanner plus virtual trading. Keep the backend, strategy-test worker, and frontend commands in separate PowerShell terminals once they start long-running processes.

1. Install dependencies:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_backend.ps1

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

5. Start the durable strategy-test worker in a separate terminal:

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.workers.strategy_test_worker
```

Historical backtests require `strategy-test-worker`: without it, the API only enqueues `strategy_test_runs` and they stay queued. `forward_virtual` requires both `strategy-test-worker` and scanner/market data: the worker starts and heartbeats the run, while scanner ticks/signals drive the forward runtime. With scanner disabled, `forward_virtual` can correctly remain in `waiting_for_market_data`.

6. Start frontend:

```powershell
cd frontend
$env:NEXT_PUBLIC_FASTAPI_HTTP_URL="http://127.0.0.1:8000"
$env:NEXT_PUBLIC_FASTAPI_WS_URL="ws://127.0.0.1:8000/api/v1/realtime/ws"
$env:NEXT_PUBLIC_FASTAPI_SSE_URL="http://127.0.0.1:8000/api/v1/realtime/events"
$env:NEXT_PUBLIC_FASTAPI_TIMEOUT_MS="8000"
corepack pnpm dev
```

Frontend URL: `http://127.0.0.1:3000`

7. Verify `/health`:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected for the local MVP profile: storage is `ok`, `scanner_running` is `false`, optional sync workers are disabled, and `real_position_sync_enabled` is `false`.

8. Verify `/api/v1/radar/status`:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/radar/status
```

Expected before scanner start: `scanner_running=false`, `scanner_pairs_count` is small, and `max_scanner_pairs=20`.

9. Start scanner explicitly:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/radar/scanner/start
Invoke-RestMethod http://127.0.0.1:8000/api/v1/radar/status
```

Expected after start: `scanner_running=true`; `stage` moves through `warming_up`, `listening`, or `degraded` if optional external market data is unavailable.

10. Run virtual trading smoke:

```powershell
make smoke-virtual
```

Equivalent PowerShell command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_virtual.ps1
```

## One-Command Dev

After backend and frontend dependencies are installed, this command starts infra, applies Alembic migrations, starts backend, starts `strategy-test-worker`, and starts frontend:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

Use `-NoScanner` when you want the API to start without scanner autostart. Historical backtests require `strategy-test-worker`; `scripts\dev.ps1` starts that worker for local dev. `forward_virtual` requires `strategy-test-worker` plus scanner/market data, so with `-NoScanner` it can be `waiting_for_market_data` until scanner ticks are flowing. Use `-NoInfra` only when PostgreSQL, Redis, NATS and ClickHouse are already managed outside the script.

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
powershell -ExecutionPolicy Bypass -File .\scripts\test_backend.ps1
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

Strategy backtest/forward Docker smoke:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_strategy_tests.ps1
```

Linux/macOS wrapper, when PowerShell is available:

```sh
./scripts/smoke_strategy_tests.sh
```

The strategy smoke runs through Docker Compose, not local Python. It starts infra with `--profile infra`, applies Alembic from the Docker backend image, seeds demo identity and duplicate OHLCV candles, starts `backend-dev` plus `strategy-test-worker`, then verifies a historical backtest and forward virtual pending-fill/cancel chain. Timeouts and seed sizing are configurable with `SMOKE_RUN_TIMEOUT_SECONDS`, `SMOKE_FORWARD_TIMEOUT_SECONDS`, `SMOKE_BACKEND_HEALTH_TIMEOUT_SECONDS`, `SMOKE_POLL_INTERVAL_SECONDS`, `SMOKE_CANDLES_PER_TIMEFRAME`, `SMOKE_WARMUP_CANDLES`, `SMOKE_START_AT`, and `SMOKE_LOG_TAIL_LINES`.

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
