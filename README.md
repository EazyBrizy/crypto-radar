# Crypto Radar

Crypto Radar is an MVP project for realtime crypto market scanning and manual signal review.

Current focus: **MVP 1 - Radar + Manual Signals**.

## What is implemented

- Bybit public WebSocket market data collector.
- Feature pipeline for price, volume spike, 1m price change, and volatility.
- Strategy engine with early signal generation logic.
- FastAPI backend entrypoint.
- MVP signal API routes:
  - `GET /api/v1/radar`
  - `GET /api/v1/signals`
  - `GET /api/v1/signals/{signal_id}`
  - `POST /api/v1/signals/{signal_id}/confirm`
  - `POST /api/v1/signals/{signal_id}/reject`
- In-memory `SignalService` for active/manual signals.
- Architecture blueprint in `docs/architectureproject.md`.

Note: scanner-generated signals are not yet automatically persisted into the API store. The API currently exposes the MVP contract and in-memory signal workflow.

## Project structure

```text
backend/
  app/
    api/v1/              FastAPI routes
    core/                config and future infrastructure helpers
    models/              Pydantic models
    services/            scanner, market data, feature, strategy, signal services
    main.py              FastAPI app entrypoint
docs/                    architecture and product docs
infra/                   local infrastructure configs
frontend/                reserved for Next.js frontend
```

## Local setup

From the project root:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

If `python` is not available in PATH, use your installed Python executable instead.

## Run the API

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

Interactive docs:

```text
http://127.0.0.1:8000/docs
```

## Check endpoints

Health check:

```powershell
curl http://127.0.0.1:8000/health
```

Radar feed:

```powershell
curl http://127.0.0.1:8000/api/v1/radar
```

All signals:

```powershell
curl http://127.0.0.1:8000/api/v1/signals
```

Signal detail:

```powershell
curl http://127.0.0.1:8000/api/v1/signals/sig_test
```

Confirm signal:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/signals/sig_test/confirm
```

Reject signal:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/signals/sig_test/reject
```

For now, unknown signal ids return `404 Signal not found`.

## Run the scanner manually

The old CLI scanner entrypoint is still available:

```powershell
.venv\Scripts\python.exe backend\app\main.py
```

It connects to Bybit WebSocket, processes ticks, and prints detected signals to the console.

## Environment

Create a local `.env` file from the safe example:

```powershell
copy .env.example .env
```

Do not commit real API keys. `.env` is ignored by git.
