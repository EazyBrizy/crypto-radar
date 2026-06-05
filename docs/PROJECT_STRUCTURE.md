# PROJECT_STRUCTURE

Codex source of truth for repository layout. Keep this file short and update it when folders, stacks, or ownership boundaries change.

## Root

```text
backend/      FastAPI application, domain services, SQLAlchemy models, Alembic migrations, tests
frontend/     Next.js App Router dashboard, API client, realtime client, UI state, tests
infra/        Docker Compose, ClickHouse init SQL, Helm, Terraform, observability configs
scripts/      Local dev, smoke, seed, and strategy baseline scripts
docs/         Compact Codex-facing project docs only
```

## Backend Map

- API routes: `backend/app/api/v1/`
- API router: `backend/app/api/v1/router.py`
- App entrypoint and lifespan workers: `backend/app/main.py`
- Settings: `backend/app/core/config.py`
- Database session/base: `backend/app/core/database.py`
- Redis client: `backend/app/core/redis_client.py`
- ClickHouse client: `backend/app/core/clickhouse_client.py`
- SQLAlchemy models: `backend/app/models/`
- Pydantic schemas: `backend/app/schemas/`
- Repositories: `backend/app/repositories/`
- Business services: `backend/app/services/`
- Strategy engine and strategy modules: `backend/app/strategies/`
- Exchange adapters: `backend/app/exchanges/`
- Background workers: `backend/app/workers/`
- Migrations: `backend/alembic/versions/`
- Backend tests: `backend/tests/`

## Frontend Map

- Next routes: `frontend/src/app/`
- Dashboard shell and page controllers: `frontend/src/features/app-shell/`
- Server-state queries and mutations: `frontend/src/features/server-state/`
- API wrappers: `frontend/src/api/`
- OpenAPI generated files: `frontend/src/api/generated/`
- Realtime gateway and router: `frontend/src/features/realtime/`, `frontend/src/realtime/`
- Local UI state: `frontend/src/stores/`
- Shared UI/components: `frontend/src/components/`
- i18n: `frontend/src/i18n/`
- Unit tests: colocated `*.test.ts` / `*.test.tsx`
- E2E tests: `frontend/e2e/`

## Infra Map

- Local services: `infra/docker-compose.yml`
- ClickHouse schemas: `infra/clickhouse/init/`
- Helm chart: `infra/helm/crypto-radar/`
- Terraform scaffold: `infra/terraform/`
- Observability: `infra/prometheus/`, `infra/loki/`, `infra/otel/`, `infra/grafana/`

## Stack

- Backend: FastAPI, Pydantic, SQLAlchemy, Alembic, Redis, ClickHouse, NATS-ready infra.
- Frontend: Next.js, React, TypeScript, pnpm, TanStack Query, Zustand, openapi-fetch.
- Data: PostgreSQL owns app state, Redis owns hot/realtime state, ClickHouse owns market/analytics time series.

## Development Rules

- Backend owns trading calculations: signals, entry zones, stops, targets, R:R, fees, slippage, position sizing, PnL, lifecycle, risk decisions, execution readiness.
- Frontend sends intents and displays backend state. Do not add trading math or hardcoded user/risk/execution parameters in the frontend.
- Database schema changes require SQLAlchemy model updates and Alembic migrations.
- API contract changes require Pydantic schema updates, backend tests, and regenerated frontend OpenAPI types.
- Keep live trading safety flags disabled by default. Never commit real exchange secrets.
- Prefer existing services/repositories over direct persistence in route handlers.
- Add or update tests near the changed behavior: `backend/tests/` for backend, colocated frontend tests for UI/client logic.
- Do not use archived docs as source of truth.
