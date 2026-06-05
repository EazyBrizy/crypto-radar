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

## Local Infra

Start only storage and messaging dependencies:

```powershell
docker compose -f infra\docker-compose.yml --profile infra up -d postgres redis nats clickhouse
```

Optional observability:

```powershell
docker compose -f infra\docker-compose.yml --profile observability up -d
```

Full app containers are also available:

```powershell
docker compose -f infra\docker-compose.yml --profile app up --build
```

## Backend

Install dependencies:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Apply migrations:

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Run the API:

```powershell
cd backend
$env:CRYPTO_RADAR_SCANNER_ENABLED="false"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Useful URLs:

- API: `http://127.0.0.1:8000`
- FastAPI docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

## Frontend

Install dependencies:

```powershell
cd frontend
corepack enable
corepack pnpm install
```

Run Next.js:

```powershell
cd frontend
$env:NEXT_PUBLIC_FASTAPI_HTTP_URL="http://127.0.0.1:8000"
$env:NEXT_PUBLIC_FASTAPI_WS_URL="ws://127.0.0.1:8000/api/v1/realtime/ws"
$env:NEXT_PUBLIC_FASTAPI_SSE_URL="http://127.0.0.1:8000/api/v1/realtime/events"
corepack pnpm dev
```

Frontend URL: `http://127.0.0.1:3000`

## One-Command Dev

After backend and frontend dependencies are installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -WithInfra -NoScanner
```

Remove `-NoScanner` when you want the market scanner to start with the API.

## Environment

Use `.env.example` as the safe template. Do not commit real exchange credentials.

Important backend variables:

```env
DATABASE_URL=postgresql://crypto_radar:crypto_radar@localhost:5432/crypto_radar
REDIS_URL=redis://localhost:6379/0
NATS_URL=nats://localhost:4222
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=8123
CLICKHOUSE_DATABASE=crypto_radar
CRYPTO_RADAR_SCANNER_ENABLED=true
```

Important frontend variables:

```env
NEXT_PUBLIC_FASTAPI_HTTP_URL=http://127.0.0.1:8000
NEXT_PUBLIC_FASTAPI_WS_URL=ws://127.0.0.1:8000/api/v1/realtime/ws
NEXT_PUBLIC_FASTAPI_SSE_URL=http://127.0.0.1:8000/api/v1/realtime/events
NEXT_PUBLIC_FASTAPI_TIMEOUT_MS=8000
```

## Migrations

PostgreSQL schema changes must go through Alembic:

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic revision -m "describe_change"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Update SQLAlchemy models in `backend/app/models/` and keep migrations in `backend/alembic/versions/`.

## Tests

Backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
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

Equivalent PowerShell command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_virtual.ps1
```

## Live Trading Safety

Live order placement is disabled by default. Keep these defaults unless you are deliberately testing live execution in a controlled environment:

```env
ENABLE_LIVE_TRADING=false
ENABLE_BYBIT_LIVE_ORDER_PLACEMENT=false
ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT=false
REQUIRE_PROTECTIVE_STOP_FOR_LIVE_ENTRY=true
EXCHANGE_ACCOUNT_SNAPSHOT_TTL_SECONDS=15
MAX_SCANNER_PAIRS=200
TRUNCATE_SCANNER_PAIRS_OVER_LIMIT=false
```

Real execution must pass backend risk checks, exchange connection checks, account snapshot freshness, instrument rules, idempotency, and protective-order requirements before an adapter can place orders.

## Current Limitations

- Real pending-entry execution from tick triggers is not implemented; pending entry is currently virtual-only.
- Email and Telegram notification providers are stubbed; WebSocket/SSE delivery is active.
- NATS is provisioned in local and deploy infra, while current realtime fanout uses Redis Pub/Sub plus WebSocket/SSE.
- Mainnet order placement requires explicit backend flags and an exchange connection configured for live placement.
