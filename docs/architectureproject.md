# Architecture Contract Index

This compact index preserves pipeline contract names used by backend tests. Keep the detailed ownership notes in `docs/BACKEND.md`, `docs/DATABASE.md`, `docs/STRATEGIES.md`, `docs/WORKERS.md`, and `docs/FRONTEND.md`.

## Pipeline Stages

- Exchange WS
- Raw Market Event
- Normalizer
- Kafka Topic: market.trades
- Kafka Topic: market.orderbook
- Kafka Topic: market.candles
- Feature Builder
- Strategy Engine
- Signal Scoring
- Signal Store
- Frontend Radar

## Topic Contracts

- market.trades.raw
- market.orderbook.raw
- market.candles.raw
- market.liquidations.raw
- market.trades.normalized
- market.orderbook.normalized
- market.candles.normalized
- features.symbol.1m
- features.symbol.5m
- signals.created
- signals.updated
- signals.expired
- trades.virtual.opened
- trades.virtual.closed
- trades.real.synced
- ai.review.requested
- ai.review.completed

## Ownership

- Backend owns ingestion, normalization, feature building, strategy execution, signal scoring, persistence, execution gates, risk, lifecycle, and PnL.
- Frontend Radar displays backend-provided signal, action, execution gate, status, and realtime state; it does not compute trading eligibility or risk.
