# Architecture

## Data Flow

WebSocket (exchanges)
→ Data Collector
→ Feature Engine
→ Strategy Engine
→ Signal Scoring
→ API (FastAPI)
→ Frontend (Next.js)

## Core Services

- market_data_service
- feature_engine
- strategy_engine
- scoring_engine
- execution_engine
- journal_service

## Rules

- async everywhere
- modular services
- no business logic in controllers