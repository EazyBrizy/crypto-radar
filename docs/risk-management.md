# Risk Management / Risk-Reward

## Current Scope

This module starts with user-level configuration and a shared backend risk gate.
Virtual entry preview/open flows now pass through the same `RiskGateService`
decision layer that real execution will use before any exchange order can be
sent. Preview, blocked-attempt, successful virtual, and real-attempt decisions
are now auditable through `risk_decisions`. `risk_protection_state`,
`asset_risk_groups`, and cached exchange instrument rules are wired into the
backend risk context, with some production automation still outstanding below.

## Virtual Vs Real Gates

Virtual and real entries share the same `RiskGateService`, but they do not have
the same operating meaning.

Virtual trading:

- is allowed as a research/simulation path after the risk decision is recorded;
- may surface warnings for weak, unknown, or insufficient edge;
- may be used to study lifecycle behavior, fill assumptions, and strategy
  outcomes;
- must still respect hard blockers such as invalid trade plans, failed RR guard,
  blocked no-trade filters, impossible stops/targets, and account protection
  states that block virtual entries.
- consumes `TradePlanCompletenessService` results instead of recalculating
  entry/stop/target/score/context completeness locally.

Real trading:

- requires the risk decision to pass;
- requires the strategy RR guard to pass;
- requires no hard no-trade filter;
- requires a fresh exchange-derived account snapshot before pre-execution
  RiskGate sizing for non-dry-run live adapters;
- requires `edge.status == positive`;
- requires edge `sample_size >= edge_min_sample_size`;
- requires `expectancy_after_costs_r` to be greater than the configured minimum;
- requires fresh market data when `real_requires_fresh_market_data` is enabled;
- requires a valid orderbook/depth snapshot for liquidity and spread checks;
- requires fresh exchange rules and valid order-size/price constraints;
- requires protective stop/take-profit orders to be available in the execution
  plan;
- for futures, requires a valid liquidation price or liquidation-buffer check
  before entry can be treated as production-safe;
- for spot, enforces the configured `spot_max_position_size_percent` cap.
- blocks when the normalized trade-plan completeness assessment reports
  missing entry, structural stop, structural target, or another completeness
  blocker.

Real execution must never downgrade these failures into research warnings. If a
real gate fails, the adapter must not submit an exchange order. Virtual can help
generate evidence for strategy calibration, but positive EV with enough sample
size is required before a signal is eligible for real entry.

Real confirm API boundaries return the service decision as structured
`RealExecutionResult` data. `risk_failed`, `readiness_failed`,
`not_implemented`, `dry_run`, `submitted`, `partially_filled`, and `failed` are
response statuses, not reasons for an API handler to throw HTTP 501 after
calling the execution service. A live adapter that is absent or explicitly not
implemented must produce `not_implemented` before any adapter placement method
is called.

Completeness assessment is separate from display visibility. Radar
`all_market_opportunities` keeps incomplete market setups visible with reasons.
Radar `execution_ready` returns only opportunities whose fresh read-only
RiskGate preview currently allows execution for the display scope. This Radar
GET path must not write risk audit rows, change signal status, or create
virtual trades.

Signal status alone never grants entry permission. `active` means an open
market opportunity and must remain visible in all-market Radar mode, but it is
not an execution candidate. RiskGate preview/confirm is evaluated only after
the centralized execution-candidate status helper accepts the signal status:
`entry_touched`, `actionable`, or `confirmed`.

## Storage

PostgreSQL remains the source of truth:

- `app_users.risk_profile` stores the selected profile name.
- `user_profiles.settings.risk_management` stores the active numeric limits.

Current JSON shape:

```json
{
  "risk_profile": "balanced",
  "risk_mode": "percent",
  "risk_per_trade_percent": 1.0,
  "fixed_risk_amount": null,
  "fixed_risk_currency": "USDT",
  "radar_display_mode": "all_market_opportunities",
  "min_rr_ratio": 2.0,
  "max_daily_loss_percent": 3.0,
  "max_weekly_loss_percent": 7.0,
  "max_account_drawdown_percent": 10.0,
  "max_open_risk_percent": 5.0,
  "max_correlated_risk_percent": 3.0,
  "max_spread_bps": 50.0,
  "max_slippage_bps": 150.0,
  "max_price_deviation_bps": 100.0,
  "max_orderbook_liquidity_ratio": 1.0,
  "include_fees_in_risk": true,
  "include_slippage_in_risk": true,
  "stop_loss_required": true,
  "take_profit_required": true,
  "stop_loss_mode": "fixed_percent",
  "default_stop_loss_percent": 1.5,
  "atr_period": 14,
  "atr_multiplier": 2.0,
  "take_profit_mode": "risk_multiple",
  "tp1_r_multiple": 1.0,
  "tp2_r_multiple": 2.0,
  "tp3_r_multiple": 3.0,
  "partial_take_profit_enabled": true,
  "tp1_close_percent": 30.0,
  "tp2_close_percent": 40.0,
  "tp3_close_percent": 30.0,
  "move_sl_to_breakeven_after_r": 1.0,
  "breakeven_offset_percent": 0.05,
  "trailing_stop_enabled": true,
  "trailing_mode": "atr",
  "trailing_atr_multiplier": 1.5,
  "trailing_stop_percent": 0.5,
  "max_leverage": 3,
  "min_liquidation_buffer_percent": 2.0,
  "liquidation_buffer_required": true,
  "spot_risk_per_trade_percent": 1.0,
  "spot_max_position_size_percent": 20.0,
  "spot_stop_required": true,
  "futures_risk_per_trade_percent": 0.5,
  "futures_max_leverage": 3,
  "futures_max_open_risk_percent": 3.0,
  "futures_liquidation_buffer_required": true,
  "virtual_risk_mode": "same_as_real",
  "virtual_risk_per_trade_percent": 1.0,
  "virtual_starting_balance": 10000.0,
  "virtual_slippage_model": "spread_based",
  "virtual_fee_model": "exchange_based",
  "virtual_trading_uses_realistic_execution": true,
  "strategy_risk_multipliers": {
    "trend_pullback_continuation": 1.0,
    "volatility_squeeze_breakout": 0.75,
    "liquidity_sweep_reversal": 1.0,
    "trend_following": 1.0,
    "breakout": 0.75,
    "smart_money_setup": 1.0,
    "scalping": 0.5,
    "mean_reversion": 0.75,
    "news_event_trade": 0.25
  },
  "auto_reduce_risk_after_losses": true,
  "allow_risk_increase_after_profit": false,
  "increase_risk_after_profit_streak": false,
  "max_risk_boost": 1.25
}
```

The preset values are product defaults, not immutable trading rules. They can be
rebalanced as the risk engine becomes more sophisticated.
For the MVP, fee and slippage inclusion is mandatory and exposed as read-only
settings rather than user toggles.

## Execution Profile Resolution

Risk settings are resolved as a typed execution profile before RiskGate. The
resolver is deterministic and does not read the database itself; callers pass
the already-loaded user risk settings, strategy `risk_settings` JSON, optional
explicit `risk_override`, execution mode, and instrument type. The saved
user/strategy execution profile is the source of truth; request risk changes
must use `risk_override`.

Execution mode and instrument type are separate contract fields:

- `mode`: `virtual` or `real`; this selects simulated/paper execution versus
  production-like exchange execution.
- `instrument_type`: `spot` or `futures`; this selects market-data category,
  fee category, exchange-rule lookup, leverage policy, and futures/liquidation
  checks.

Legacy requests that send `instrument_type = "virtual"` are accepted only by a
backward-compatible adapter. The adapter resolves `mode = "virtual"`, derives
the actual instrument type from explicit request/profile settings, exchange
instrument rules, leverage, or default `spot`, and records an explicit
deprecation warning/source. RiskGate internals and new code must not persist or
propagate `instrument_type = "virtual"`.

Precedence:

```text
request risk_override
> strategy risk_settings
> user risk_management settings
> schema/config defaults
```

Request override contract:

```python
RiskOverride = {
    "risk_mode": "percent" | "fixed",
    "risk_percent": Decimal | None,
    "fixed_risk_amount": Decimal | None,
    "leverage": Decimal | None,
}
```

`risk_mode = "percent"` requires `risk_percent`. `risk_mode = "fixed"`
requires `fixed_risk_amount`. An override source is surfaced in RiskGate
decisions/audit as `risk_profile_source = "request_override"`.

For Radar display, the explicit request field is
`radar_display_mode`. Filtering `all_market_opportunities` vs
`execution_ready` belongs to the Radar service layer, not strategy setup or
persistence. `execution_ready` uses a read-only RiskGate preview so refreshes
do not create audit spam.

Legacy percent keys remain readable for backward compatibility:
`risk_per_trade_percent`, `spot_risk_per_trade_percent`,
`futures_risk_per_trade_percent`, and `virtual_risk_per_trade_percent`.
The legacy request value `risk_percent = 10.0` is not treated as an explicit
override and does not replace a saved profile, because that value was
historically an API default. `RiskPreviewRequest.risk_percent` and
`ManualConfirmRequest.risk_percent` are deprecated/backward-compatible fields
kept for parsing and audit snapshots only. Use `risk_override` for per-ticket
percent, fixed-risk, or leverage changes.

Futures-only branches are enabled by `instrument_type == "futures"` or effective
`leverage > 1`. They must not be enabled only because `mode == "virtual"`.

Invalid profile combinations must fail with an auditable validation reason.
Examples: `risk_mode = "fixed"` without `fixed_risk_amount`, non-positive
fixed risk amount, unsupported RR target, or an invalid Radar display mode.

Strategy evaluation must not consume the resolved execution profile directly.
`StrategyEngine` resolves `user_strategy_configs.risk_settings` into typed
`StrategyExecutionSettings` and exposes it to the shared pipeline context for
RR/no-trade/execution policy checks, while `strategy.evaluate(...)` receives
only market setup params and market context.

## Profiles

- `conservative`: lower risk budget for beginners or larger deposits.
- `balanced`: default MVP profile.
- `aggressive`: larger risk budget for experienced users.
- `custom`: manual limits, intended for Pro-level control.

## User Education In Settings

Implemented in the frontend:

- the Risk management settings block now has a `Guide` tab;
- the guide explains why risk-gate can block every entry, especially through
  `max_open_risk_percent`, `max_correlated_risk_percent`, `min_rr_ratio`,
  spread/slippage/price-drift blockers, and futures liquidation checks;
- each settings group has user-facing explanations for profile limits, trade
  rules, stop-loss, take-profit, breakeven, trailing stop, futures protection,
  virtual trading, fees, slippage, strategy multipliers, and adaptive risk;
- the user-facing guide intentionally avoids formulas and numeric calculations,
  keeping formulas in internal docs and backend tests instead;
- the guide shows the current profile, risk per trade, open risk, correlated
  risk, and protection state next to the educational text so users can connect
  explanations with the live backend state;
- the guide recommends safe debugging steps for paper trading: close stale
  virtual positions, switch virtual trading to separate settings, adjust one
  field at a time, and prefer loosening virtual limits before real limits.

Zero-value behavior:

- for optional limit fields, `0` means "disabled" rather than "block at zero";
- this applies to minimum R:R, daily/weekly loss limits, max drawdown, open risk
  caps, correlated risk, spread/slippage/price-drift caps, orderbook-use cap,
  spot max position size, futures open-risk cap, and minimum liquidation buffer;
- core calculation inputs still remain positive: risk per trade, entry/stop
  prices, stop distance, leverage, and virtual starting balance.

Still missing:

- contextual per-field tooltips beside every input;
- direct links from a failed Radar risk-card reason to the exact setting that
  can change that blocker;
- preset recommendations such as "learning virtual", "strict real", or
  "scalping test" that update multiple custom fields together after user
  confirmation.

## Not Implemented Yet

This section is the single backlog for missing risk-management functionality
while the module is being built step by step.

### Risk Enforcement

- mark virtual trades opened after daily stop as discipline violations instead
  of blocking the simulation when protection is not account-blocked;

### Fees, Funding, And Liquidation

- Add fee-rate TTL/staleness policy and background refresh observability. The
  risk paths now consume cached/synced Bybit fee-rate data, but there is no
  separate production scheduler for refreshing stale private fee rates yet.
- Apply quantity and price rounding from cached `qty_step` and `tick_size`.
  Automatic Bybit rule refresh exists and the risk context reads cached min/max
  order size, min notional, max leverage, and rule freshness, but execution
  paths do not yet round outgoing quantities/prices by these filters.
- Add fee-rate retrieval for exchanges beyond Bybit.
- Add full funding checks for futures. A production derivative snapshot runner
  now refreshes Bybit ticker `fundingRate` into PostgreSQL and Redis hot cache
  for strategy/lifecycle funding filters, and the risk gate still includes a
  one-interval funding buffer when ticker context is available. It does not yet
  model holding horizon, funding schedule accrual, or realized funding
  debits/credits.
- Calculate projected liquidation prices for new futures orders. The gate can
  now consume live Bybit `liqPrice` for an already-open matching real futures
  position, and it still accepts a caller-provided liquidation price, but it does
  not yet calculate the exact post-order liquidation price by margin mode,
  maintenance tier, wallet balance, and existing exposure.
- Move orderbook from REST snapshot to stream/cache for production latency.
  The risk gate now consumes REST Bybit ticker/orderbook snapshots before the
  decision, but there is no local hot cache or WebSocket orderbook stream wired
  into this gate yet.
- Add level-by-level orderbook VWAP/impact-price validation. The gate now blocks
  insufficient visible depth and excessive configured slippage, but it does not
  yet compute exact fill VWAP against every orderbook level or compare it with a
  user limit price.
- Add an admin/user-facing fee cache status view.

### Stop-Loss And Take-Profit

- Pass user-scoped ATR values from market features into manual confirm and
  virtual execution previews. ATR stop calculation exists, but virtual execution
  currently falls back when ATR is unavailable.
- Implement real structure-stop detection instead of using only the signal stop:
  swing low/high, liquidity zone, order block, support/resistance, VWAP
  deviation, and local extrema.
- Wire the same protective-order lifecycle into a future real exchange adapter.
  Virtual lifecycle already records partial take-profit, breakeven, trailing,
  and time-stop events; real trading still needs exchange-native protective
  order placement and reconciliation before production submission.

### Real Trading

- Connect production real exchange order placement after the real risk gate and
  readiness checks pass. The current default real path uses
  `DryRunExecutionAdapter` and returns a structured `dry_run` result; absent or
  explicitly unimplemented live adapters return structured `not_implemented`
  before placement.
- Wire close-only behavior into the future real order adapter. The backend risk
  state and risk decisions now expose close-only/reduce-only/protective-order
  flags, but there is still no production adapter endpoint that places
  reduce-only or protective exchange orders.
- Fetch or calculate exchange-specific liquidation prices for real futures
  orders. The liquidation guard can validate a provided liquidation price, but
  the app does not yet calculate the exact exchange liquidation price by margin
  mode, maintenance margin tier, wallet balance, and position mode.

### Correlation, Strategy, And Adaptive Risk

- Make signal score risk tiers configurable. The current score multipliers are
  implemented as fixed product defaults.
- Update protection state from real trade closes. Virtual closes update loss
  streak, daily/weekly loss, peak/current equity, adaptive multiplier, and mode.
- Implement cautious risk increase after profit streaks. The settings are stored
  but disabled by default and not yet applied.

### User-Facing Entry Card

- Finish the real-order confirm modal around `/api/v1/trades/real/confirm`.
  Signal details now use backend preview data for the risk card and only hard
  block on `risk_check.status === "failed"`, but the real confirm flow is still
  not connected to a production order adapter.

### Production Readiness

- Replace the current dev secret provider with real secret storage
  (Vault/KMS or equivalent) before production trading. The current provider keeps
  raw exchange credentials only in process memory; raw API keys/secrets are not
  persisted in PostgreSQL and are not returned by API responses.

## Position Sizing

The shared sizing helper is implemented in `app.services.risk_management` and is
now attached to virtual execution previews and opened virtual trades.

`RiskGateService` now compares manually requested notional against the adjusted
risk budget. If `size_usd` would risk more than the backend-calculated limit,
the decision is `failed` with `Risk per trade exceeds the adjusted risk limit.`

RR target basis is centralized in `RiskRewardPlanService`. Pipeline RR
assessment and RiskGate RR checks both select the policy target from TradePlan
with the same `nearest` / `final` rules and then calculate RR from actual
entry, stop, selected target, and side. Legacy `take_profit_1` /
`take_profit_2` values are supported only through the TradePlan adapter before
RR calculation.

Base formula:

```text
risk_amount = account_equity * risk_per_trade_percent / 100
position_size_base = risk_amount / effective_risk_per_unit
notional = position_size_base * entry_price
required_margin = notional / leverage
```

Fixed-risk mode uses the same sizing path after resolving the budget:

```text
requested_risk_amount = fixed_risk_amount
risk_cap_amount = account_equity * max_per_trade_risk_cap_percent / 100
base_risk_amount = min(requested_risk_amount, risk_cap_amount)
effective_risk_amount =
base_risk_amount
* strategy_risk_multiplier
* signal_score_multiplier
* volatility_multiplier
* user_mode_multiplier
risk_per_trade_percent = effective_risk_amount / account_equity * 100
position_size_base = effective_risk_amount / effective_risk_per_unit
notional = position_size_base * entry_price
required_margin = notional / leverage
```

The max per-trade cap for fixed mode comes from the same resolved per-trade
percent context that percent sizing uses (`risk_per_trade_percent`,
`spot_risk_per_trade_percent`, `futures_risk_per_trade_percent`, or
`virtual_risk_per_trade_percent` when virtual custom risk is active). A fixed
amount must be positive. Missing, zero, or negative fixed amounts are invalid.

When `fixed_risk_amount` is above the cap, the backend must reduce the amount
before sizing, set `risk_amount_capped = true`, expose
`requested_risk_amount`, `effective_risk_amount`, `risk_cap_amount`, and add a
RiskGate warning. This is not a silent fallback. The capped
`effective_risk_amount` is the source of truth for quantity calculation.

Fixed-risk mode still respects open-risk, correlated-risk, leverage,
liquidation, exchange-rule, market-quality, no-trade, RR, and real-readiness
gates. The fixed amount is a maximum loss budget, not a requested notional.
Futures margin and available-balance checks run after fixed-risk sizing because
required margin depends on the final quantity, price, and leverage.

`effective_risk_per_unit` currently includes:

- absolute distance from entry to stop;
- estimated entry fee per unit from backend-resolved fee-rate;
- estimated stop/exit fee per unit from backend-resolved fee-rate;
- slippage buffer per unit;
- funding buffer per unit when exchange funding context is available.

Fee-rate source is resolved before sizing:

- Bybit cached/synced maker/taker fees are read by user, exchange connection,
  account type/category, and symbol/category;
- risk sizing uses the taker fee, or the larger maker/taker value if needed;
- `virtual_fee_model=exchange_based` uses this backend fee resolver in preview
  and confirm paths;
- if fee-rate is unavailable, the gate uses a conservative fallback fee rate and
  adds an explicit decision warning.

## Trade-Type Risk And Final Risk Formula

The risk settings now store separate defaults for spot, futures, and virtual
execution:

- spot risk percent, max spot position size percent, and required stop flag;
- futures risk percent, futures max leverage, futures max open risk, and
  required liquidation buffer flag;
- virtual execution risk mode (`same_as_real` or `custom`), virtual starting
  balance, slippage model, and fee model. These settings modify simulated
  execution behavior and risk-budget selection; they do not make `virtual` an
  instrument type.

The backend now calculates `RiskAdjustmentPlan`:

```text
requested_risk_amount = percent_or_fixed_profile_budget
base_risk_amount = requested_risk_amount capped by the per-trade risk cap
effective_risk_amount =
base_risk_amount
* strategy_risk_multiplier
* signal_score_multiplier
* volatility_multiplier
* user_mode_multiplier
```

The legacy `adjusted_risk_amount` field remains present and equals
`effective_risk_amount`. Position sizing consumes `effective_risk_amount`
directly instead of recalculating the budget from `risk_percent`.

Signal score multipliers are currently:

- 90-100: `1.0x`
- 75-89: `0.75x`
- 60-74: `0.5x`
- below 60: blocked / virtual-only

Virtual position sizing now uses this adjusted risk percent instead of the raw
profile risk percent. The execution report also includes `RiskCheckResult`,
which evaluates R:R, margin, daily risk, open risk, futures guard status, and
exchange order-size constraints when those inputs are available.

## Backend Risk Gate

The first shared risk-gate layer is implemented:

```text
RiskContextService -> RiskGateService -> RiskDecision
```

Current behavior:

- virtual execution previews build a `RiskContext` and expose `RiskDecision` in
  `VirtualExecutionReport`;
- `POST /api/v1/risk/preview` builds the same context, writes a preview audit,
  and returns `RiskPreviewResponse`;
- Radar `execution_ready` builds a read-only preview for display filtering and
  does not persist a `risk_decisions` audit row;
- `GET /api/v1/risk/state` exposes daily/weekly/open/correlated risk and
  protection mode, close-only flags, reset windows, and exchange-rule
  freshness;
- virtual trade opening runs the gate before execution simulation and again
  after the simulated fill price/partial fill;
- cached exchange instrument rules are checked for `fresh` / `missing` /
  `stale`; missing or stale rules warn virtual previews and hard-block real
  entries;
- Bybit ticker/orderbook/live position context feeds entry price, spread
  slippage, funding buffer, visible liquidity, and live matching-position
  liquidation price into the same decision path;
- real execution builds an `AccountRiskSnapshot` before the pre-execution
  RiskGate context. Live adapters require `source=exchange` and
  `status=fresh`; `ManualConfirmRequest.account_balance` is accepted only for
  dry-run/manual simulation snapshots and is surfaced with explicit
  source/warning metadata;
- cached/synced Bybit fee-rate context feeds position sizing in preview, real
  confirm, and virtual confirm/open paths;
- spread-too-high, expected-slippage-too-high, price-moved-too-far, and
  insufficient visible orderbook liquidity are hard blockers in the backend
  gate;
- Settings `Simulation` / `virtual_simulation_level` does not change these
  hard blockers; it only controls virtual execution realism and Reality Check
  diagnostics;
- `risk_protection_state` uses user-timezone daily/weekly windows, resets the
  daily and weekly loss counters at new windows, applies weekly loss limits, and
  keeps peak equity separate from those resets;
- protection states now expose close-only semantics: new real entries and
  position increases are blocked in `virtual_only`/`blocked`, while reduce-only
  and protective-order actions are marked as allowed for the future adapter;
- failed decisions block virtual trade creation;
- blocked virtual attempts and real attempts are recorded in `risk_decisions`;
- real confirm paths call the same gate and return a structured
  `RealExecutionResult`, such as `risk_failed`, `readiness_failed`,
  `not_implemented`, `dry_run`, or future live adapter statuses;
- frontend receives backend `risk_decision` / `risk_check` and displays the
  backend status instead of calculating entry permission locally.

Still missing:

- projected liquidation price for brand-new futures orders;
- actual reduce-only/protective-order placement in the future real exchange
  adapter.

## Risk Persistence

Risk-management persistence is now reserved in PostgreSQL by Alembic migration
`202605280012_create_risk_management_tables`.

Tables:

- `risk_decisions`: durable risk-gate audit records with mode, instrument type,
  stage, status, blockers, warnings, input snapshot, and result snapshot.
- `position_risk_snapshots`: frozen risk numbers at position open time:
  adjusted risk, R:R, leverage, margin mode, liquidation fields, fee/slippage
  estimate, funding buffer, and multipliers.
- `exchange_instrument_rules`: exchange constraints cache for min/max size, min
  notional, quantity step, tick size, max leverage, funding interval, and raw
  exchange payload.
- `asset_risk_groups`: asset-to-risk-cluster classification. For MVP, the model
  allows one primary group per asset.
- `risk_protection_state`: current user protection state for adaptive risk:
  normal/reduced/virtual-only/blocked, loss streak, daily/weekly loss, peak
  equity, current equity, adaptive multiplier, daily/weekly reset window starts,
  and the timezone used for those windows.

Current write coverage:

- successful virtual opens persist `risk_decisions` and
  `position_risk_snapshots` from the backend `RiskDecision`;
- manual/API preview checks persist `risk_decisions` with `stage=preview`;
- Radar read-only execution-ready previews do not persist `risk_decisions`;
- blocked virtual attempts persist failed `risk_decisions` without order/position
  ids;
- real confirm attempts persist `risk_decisions` before any future exchange
  adapter is called;
- manual Bybit instrument-rule sync upserts `exchange_instrument_rules`;
- automatic Bybit instrument-rule sync starts with FastAPI, refreshes configured
  categories periodically, and stores `fetched_at` / `updated_at` for TTL checks;
- bootstrap seeds the primary `asset_risk_groups` taxonomy for majors, L1, L2,
  meme, DeFi, AI, exchange-token, and BTC-beta-high clusters;
- virtual trade closes update `risk_protection_state`.

Still missing:

- production scheduling/observability for exchange-rule refresh beyond the
  in-process FastAPI runner;
- quantity/price rounding enforcement from `qty_step` and `tick_size`;
- admin/editor workflow for maintaining asset-group taxonomy;
- real trade close updates for `risk_protection_state`;
- multi-group per-asset enforcement beyond the current primary-group MVP.

## Close-Only And Protection Reset

Implemented for the current backend:

- `risk_protection_state` stores `daily_window_start`,
  `weekly_window_start`, and `window_timezone`;
- the service derives daily and weekly windows from the user's timezone and
  resets only `daily_loss_amount` / `weekly_loss_amount` when a new window
  starts;
- `peak_equity` is not reset by daily/weekly windows;
- weekly loss now participates in protection-state calculation;
- `RiskStateResponse` and `RiskCheckResult` expose `close_only`,
  `real_entries_allowed`, `virtual_entries_allowed`, `reduce_only_allowed`, and
  `protective_orders_allowed`;
- `virtual_only` blocks new real entries/increases and leaves virtual entries
  available; `blocked` blocks new real and virtual entries, while close/reduce
  semantics stay allowed for existing exposure.

Still missing for this point:

- actual real reduce-only, stop-loss, and take-profit order placement, because
  the production real order adapter is intentionally left as a later task.

## Asset Risk Group Taxonomy

Implemented for the current backend:

- bootstrap seeds primary groups for `majors`, `l1`, `l2`, `meme`, `defi`,
  `ai`, `exchange_tokens`, and `btc_beta_high`;
- the resolver can classify a symbol by seeded `MarketPair` or by parsing the
  base asset from symbols such as `AVAXUSDT` when a pair record is not present;
- correlated risk enforcement continues to sum open risk by
  `correlation_group + side`.

Still missing for this point:

- multiple simultaneous groups per asset in enforcement;
- admin taxonomy editor and periodic taxonomy review workflow.

## Automatic Bybit Instrument Rule Sync

Implemented for the current backend:

- `ExchangeInstrumentRuleSyncRunner` starts during FastAPI lifespan when
  `exchange_instrument_sync_enabled=true`;
- the runner calls Bybit `/v5/market/instruments-info` through
  `ExchangeInstrumentRuleService.sync_bybit_rules`;
- default category is `linear`; categories can be configured with
  `bybit_instrument_rule_categories`, for example `linear,spot`;
- refresh interval is configured by
  `exchange_instrument_sync_interval_seconds` and defaults to 6 hours;
- rule freshness is evaluated using `exchange_instrument_rules.fetched_at` and
  `exchange_instrument_rules_ttl_seconds`, defaulting to 24 hours;
- `GET /api/v1/exchanges/instrument-rules` returns rule age, TTL, and
  `is_stale`;
- `RiskStateService` passes rule freshness into `RiskGateService`;
- missing or stale exchange rules are a warning for virtual mode and a hard
  blocker for real mode.

Still missing for this point:

- move the refresh loop to a dedicated scheduler/worker for production
  deployment;
- add metrics/alerts for stale or failed sync cycles;
- run configured spot + derivatives categories based on real product coverage,
  not only the current default;
- enforce `qty_step` and `tick_size` rounding before real order submission.

## Bybit Market Context In Risk Gate

Implemented for the current backend:

- `RiskMarketDataService` collects Bybit V5 ticker, REST orderbook, and private
  position-list data before `RiskGateService.evaluate`;
- long entry uses best ask and short entry uses best bid when the user did not
  manually override entry price;
- ticker spread is added to request slippage bps, so it increases
  `slippage_buffer_per_unit` and `effective_risk_per_unit`;
- ticker `markPrice`, `fundingRate`, bid/ask, spread, visible orderbook depth,
  and market-data status are returned inside `RiskCheckResult`;
- one-interval funding buffer is included in position sizing through
  `funding_buffer_per_unit`;
- visible orderbook depth is compared with calculated/checked notional, and the
  gate blocks when visible entry-side depth is insufficient;
- configured `max_spread_bps`, `max_slippage_bps`,
  `max_price_deviation_bps`, and `max_orderbook_liquidity_ratio` are hard
  blockers, so a stale signal whose real bid/ask entry breaks the risk plan
  returns `failed` from the backend gate;
- for real Bybit futures, private `/v5/position/list` is queried through the
  existing dev secret-provider boundary, and a matching open position's live
  `liqPrice` is passed into the futures guard;
- frontend risk cards render market-data status, bid/ask, mark price, spread,
  depth, and funding buffer from backend response only.
- Radar read-only `execution_ready` previews resolve `instrument_type` and
  leverage through the execution profile resolver instead of hardcoding an MVP
  futures context.
- Virtual spot previews use `mode=virtual`, `instrument_type=spot`; they must
  not query linear futures context or create liquidation blockers unless the
  effective profile resolves futures or leverage above 1.

Still missing for this point:

- WebSocket/orderbook-stream cache for lower-latency liquidity checks;
- projected liquidation-price calculation for the new order before it reaches an
  exchange adapter;
- per-symbol overrides for spread/liquidity/price-drift thresholds;
- exact level-by-level orderbook VWAP/impact-price validation against a user
  limit price;
- user-selectable instrument type/leverage in the pre-entry ticket instead of
  the current MVP frontend default of futures `3x`;
- wiring preview-only cards to a simulated path, or hiding post-impact/decay
  fields until a virtual execution exists;
- production Vault/KMS secret provider for private position-list access.

## Cached Fee-Rate In Risk Calculations

Implemented for the current backend:

- `ExchangeConnectionService` stores Bybit maker/taker fee cache in the active
  user exchange connection metadata by category and symbol. The connection
  itself scopes the cache by user, exchange, and account type;
- `RiskFeeRateService` resolves fee-rate before every risk decision for
  `/api/v1/risk/preview`, virtual confirm/open, and real confirm;
- exchange-based virtual trading ignores the request/default fee and uses the
  backend resolver;
- sizing uses the taker fee, or the larger maker/taker value, as the
  conservative execution fee;
- if cached/synced fee-rate is unavailable, the decision uses
  `conservative_fallback` and includes a warning in `RiskDecision.warnings`;
- frontend risk card now shows fee source and taker fee from backend response.

Still missing for this point:

- production refresh policy/TTL for private fee-rate cache;
- metrics/alerts for stale fee cache or repeated private API failures;
- non-Bybit exchange fee adapters;
- explicit fee cache status in settings/account UI.

## Stop-Loss And Take-Profit

User settings now include the first configurable stop-loss modes:

- `fixed_percent`: computes stop distance from `default_stop_loss_percent`.
- `atr`: computes stop distance from `atr_value * atr_multiplier` when ATR is
  supplied by the caller.
- `structure`: uses the signal/strategy stop as the structure invalidation
  level.

The shared helpers in `app.services.risk_management` return `StopLossPlan` and
`TakeProfitPlan`. Virtual execution previews and opened virtual trades now attach
these plans to the execution report. Opened virtual trades store three
risk-multiple targets by default: TP1, TP2, and TP3.

Current behavior:

- fixed-percent stop is fully usable in virtual execution;
- structure stop uses the signal stop-loss as the structure source when one is
  available;
- ATR stop calculation is available to callers that pass `atr_value`;
- open virtual trades store TP1/TP2/TP3 risk-multiple target prices;
- lifecycle-aware virtual trades store target states and record partial
  take-profit, breakeven-stop, trailing-stop, and time-stop events when the
  candle path reaches those rules.

## Breakeven, Trailing Stop, And Futures Guard

The risk helper layer now also calculates:

- `BreakevenPlan`: trigger price after `move_sl_to_breakeven_after_r` and a
  breakeven stop adjusted by `breakeven_offset_percent`;
- `TrailingStopPlan`: trailing mode and initial trailing stop candidate for
  `atr`, `percent`, or `structure` modes;
- `FuturesRiskPlan`: max leverage check and liquidation safety check when a
  liquidation price is provided.

Current behavior:

- virtual execution previews and opened virtual trades include these plans in
  the execution report;
- virtual lifecycle can move `current_stop_loss`, mark breakeven/trailing state,
  and persist lifecycle events on the entry-order metadata snapshot;
- `max_leverage` is enforced for virtual entries;
- if `liquidation_price` is provided, the guard blocks trades where liquidation
  can happen before stop-loss or where the stop-to-liquidation buffer is below
  `min_liquidation_buffer_percent`;
- if `liquidation_price` is unavailable, the futures guard status is `unknown`
  and the exact liquidation check is not treated as passed.

Bybit fee-rate retrieval has an initial implementation through the private V5
`GET /v5/account/fee-rate` endpoint. It returns maker/taker rates per category
and optional symbol, writes the latest result to the exchange connection
metadata cache, and exposes it via:

```text
GET /api/v1/exchanges/connections/{connection_id}/fees?category=linear&symbol=BTCUSDT
```

Current behavior:

- only Bybit fee-rate retrieval is implemented;
- fee rates are cached in exchange connection metadata;
- credentials are available only through the current dev secret-provider process.
