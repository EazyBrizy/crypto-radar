# Virtual Trading Simulation Levels

## Current Rule

Global market data stays immutable. Virtual execution can create a private simulated path for one position, but it must not write synthetic candles, ticks, or orderbook data into the shared market storage.

The Settings `Simulation` block controls only virtual-trade simulation realism:
fill model, spread/slippage estimate, partial fill, max realistic size,
liquidity score, and private impact path. It must not decide whether a trade is
allowed to enter. Entry permission belongs to the backend risk gate and
`user_profiles.settings.risk_management`.

Virtual entry creation uses three separate decisions:

- `RiskGate` block means no virtual trade is created.
- Virtual execution `rejected_virtual_execution`, a zero fill, or a missing
  average fill price means no virtual trade is created.
- `quality_gate.status = "blocked"` is a simulation realism warning by
  default. It must be surfaced in notes/audit/response, but it is not an entry
  veto when RiskGate passes and a fill exists.

## Service Boundary

Primary module:

`app.services.virtual_trading`

This package is the boundary for virtual trading. New code should import the service from there, not from `app.services.trade_service`. The old `trade_service` module is kept only as a compatibility facade while the API and tests finish moving to the new package.

The module owns:

- virtual execution preview and confirmation;
- private impact-aware position path;
- PostgreSQL writes for virtual orders, fills, positions, balances, ledger, audit, and outbox;
- ClickHouse writes to `analytics.virtual_trade_events`;
- Redis fanout to `pubsub:portfolio:{user_id}`.

The module must not own:

- real exchange order placement;
- raw market data ingestion;
- shared candle, tick, or orderbook mutation;
- billing/provider delivery.

Future extraction point:

- input events: `signal.confirm_requested`, `virtual_trade.close_requested`, `market.price_tick`;
- output events: `virtual_trade.opened`, `virtual_trade.updated`, `virtual_trade.closed`;
- process dependencies: PostgreSQL repository, ClickHouse analytics writer, Redis portfolio publisher, signal hot-store side effects.

## Levels

### MVP

Status: active.

- orderbook depth simulation
- spread check
- slippage calculation
- partial fill
- max executable size
- liquidity score
- flag unrealistic execution with warnings and suggested max size

### Advanced

Status: stub for settings, partial active in execution.

Active now:

- impact decay for private position path

Planned:

- queue position for limit orders
- dynamic liquidity replenishment
- maker/taker fee logic
- funding
- cross-exchange liquidity comparison
- fake liquidity detection
- spoofing detection

### Pro

Status: stub.

- agent-based market simulator
- microstructure model
- probabilistic fill model
- Monte Carlo execution simulation
- historical replay with synthetic impact

## User Setting

The selected simulation level is stored in PostgreSQL:

`user_profiles.settings.virtual_trading`

Current shape:

```json
{
  "simulation_level": "mvp",
  "simulation_level_status": "active",
  "effective_simulation_level": "mvp"
}
```

When a user selects `advanced` or `pro`, the selected level is saved as a stub, but `effective_simulation_level` remains `mvp` until the missing execution models are implemented.

## Storage

Liquidity snapshots are market analytics, so they belong in ClickHouse, not PostgreSQL.

Current target table:

`market.liquidity_snapshots`

It stores spread, bid/ask depth bands, short-term volume, volatility, liquidity score, and impact risk by exchange, symbol, and `snapshot_ts`.

Virtual execution state stays in PostgreSQL because it is user/business state:

- `orders`
- `order_fills`
- `positions`
- `portfolio_balances`
- `portfolio_balance_ledger`
- `orders.metadata.virtual_execution`

This means a separate PostgreSQL `virtual_executions` table is not required for MVP. If we later need heavy filtering/reporting by execution quality, we can normalize the same report into a dedicated table without changing the public API.

## Reality Check

The product surface for execution simulation is `Reality Check`.

It should answer:

- how a virtual market/impact-aware fill would look;
- whether the requested virtual size is realistic for the current spread, depth, volume, and slippage;
- how much of the virtual size would fill and what would remain unfilled;
- what private simulated impact path applies to that virtual position;
- what smaller virtual size would look more realistic.

It must not be used as the final entry permission. A blocked `quality_gate`
status is a simulation warning, not a trade-entry veto. If the product later
wants this quality gate to block virtual entry, that must be introduced as an
explicit documented setting such as `virtual_execution_quality_policy =
warn_only | block`; there is no implicit block-by-quality behavior in the
current contract.
