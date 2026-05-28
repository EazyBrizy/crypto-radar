# Architecture

## Data Flow

```text
Exchange WS
   ↓
Raw Market Event
   ↓
Normalizer
   ↓
Kafka Topic: market.trades
Kafka Topic: market.orderbook
Kafka Topic: market.candles
   ↓
Feature Builder
   ↓
Strategy Engine
   ↓
Signal Scoring
   ↓
Signal Store
   ↓
Frontend Radar
```

## Kafka Topics

```text
market.trades.raw
market.orderbook.raw
market.candles.raw
market.liquidations.raw

market.trades.normalized
market.orderbook.normalized
market.candles.normalized

features.symbol.1m
features.symbol.5m

signals.created
signals.updated
signals.expired

trades.virtual.opened
trades.virtual.closed
trades.real.synced

ai.review.requested
ai.review.completed
```

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
