# System Flow

MarketData -> Features -> StrategySignal -> TradePlan -> Pipeline checks -> RiskGate -> Virtual/Real Execution -> Outcome Labeling -> Strategy Performance -> EV Gate

## Operating Flow v3.4

The canonical trading flow is:

```text
MarketData
-> Features
-> StrategySignal
-> TradePlan
-> Pipeline checks
-> RiskGate
-> Virtual/Real Execution
-> Outcome Labeling
-> Strategy Performance
-> EV Gate
```

## Contract Layer Separation v1

AUD-01 fixes the contract boundary between setup discovery, research
measurement, and execution permission. A strategy setup can be real market
information even when it is not executable.

Canonical layers:

1. Signal Discovery Layer

   - Strategies may find and return a setup from market structure, momentum,
     volatility, liquidity, derivatives context, or other strategy evidence.
   - A setup must not disappear only because its RR is weak, unknown, or below
     the current execution threshold.
   - In discovery, RR is a measurement/annotation. It may lower confidence,
     add warnings, or mark the candidate as non-executable for a scope, but it
     must not hide the research/watchlist candidate by itself.

2. TradePlan Completeness Layer

   - This layer checks whether the setup has a structural stop, invalidation
     thesis, and structural target thesis.
   - A structural plan is market-based and strategy-explained.
   - A fallback plan is synthetic, such as an ATR stop or R-multiple targets,
     and must be explicit through metadata flags instead of silently replacing
     missing structure.

3. Risk/RR Eligibility Layer

   - This layer evaluates RR, account risk, user settings, edge, no-trade
     filters, and market quality for a specific decision scope.
   - Failed RR may make a signal non-executable for virtual execution and/or
     real execution when the active guard mode is hard.
   - Failed RR does not have to delete, reject, or hide the discovery signal.
     The signal should remain visible as a research, watchlist, or blocked
     candidate with reason metadata.

4. Execution Eligibility Layer

   - This layer decides whether a virtual or real execution path is allowed.
   - `execution_allowed_virtual` and `execution_allowed_real` are separate
     decisions and may differ for the same signal.
   - Real execution eligibility is always stricter than discovery, research,
     backtest, and virtual simulation eligibility.

Contract terms:

- `research_mode`: discovery, backtest, Strategy Test Lab `discovery`, and
  Strategy Test Lab `research_virtual` scopes. These scopes measure evidence
  and outcomes; they do not grant production exchange permission.
- `production_mode`: live or production-like decision scopes where a signal may
  become executable only after the configured completeness, risk, RR, market,
  edge, and execution checks pass.
- `signal_actionable`: the signal is eligible for user/execution action in the
  current scope. It is not synonymous with "strategy found a setup".
- `execution_allowed_virtual`: the decision snapshot permits virtual execution
  or lifecycle simulation for the current signal and scope.
- `execution_allowed_real`: the decision snapshot permits real execution after
  real-entry gates pass. This must remain false until all real execution
  readiness conditions are satisfied.
- `decision snapshot`: an immutable decision record attached to the signal,
  trade plan, journal row, or execution result. It records setup validity,
  trade-plan completeness, market context score, actionability, virtual/real
  execution eligibility, blockers, warnings, and source metadata used by the
  decision.

Future decision snapshot schema changes must be additive and backward
compatible. `StrategySignal.decision` and `RadarSignal.decision` are optional;
legacy signals may omit the field or return `null`. Persisted signals store the
unified snapshot in `features_snapshot.decision_snapshot`; the older
`features_snapshot.decision` key remains reserved for legacy manual decision
metadata.

```python
DecisionReasonSource = (
    "setup" | "market_quality" | "rr" | "no_trade" | "risk" | "execution" | "data"
)
DecisionReasonSeverity = "info" | "warning" | "blocker"
DecisionReasonScope = "discovery" | "virtual" | "real" | "backtest"

DecisionReason = {
    "code": str,
    "message": str,
    "source": DecisionReasonSource,
    "severity": DecisionReasonSeverity,
    "scope": DecisionReasonScope,
    "metadata": dict,
}

SignalDecisionSnapshot = {
    "setup_valid": bool,
    "trade_plan_valid": bool,
    "market_context_score": float,
    "signal_actionable": bool,
    "execution_allowed_virtual": bool | None,
    "execution_allowed_real": bool | None,
    "blockers": list[DecisionReason],
    "warnings": list[DecisionReason],
}
```

Boundary rules:

- `MarketData` is raw exchange/watchlist data and must not contain strategy or
  risk decisions.
- `Features` are deterministic derived values calculated from market data only.
  `Features.candle_state` is `"closed"` for closed OHLCV evaluation and
  `"open"` for live/open candle or tick-derived previews.
- `StrategySignal` is pure strategy output: setup, direction, score,
  explanation, entry/stop/target candidates, confirmations, and no-trade
  context. `StrategySignal.candle_state` mirrors the evaluated
  `Features.candle_state`. A strategy may return a setup that is not
  production-actionable. Strategies must not read/write DB, call APIs, or
  execute trades. Strategy params must not include account balance, margin,
  position sizing, fixed/percent risk amounts, user leverage, or Radar display
  mode; those fields belong to the execution profile and risk layer.
- `TradePlan` normalizes executable entry, stop, target, invalidation, and risk
  metadata from a strategy signal while keeping legacy signal fields available.
  It also records whether structural levels or fallback levels were used.
- Pipeline checks calculate shared quality signals such as RR quality, regime,
  confirmation, freshness, no-trade filters, market quality, and actionability.
  These checks annotate the signal and feed eligibility decisions; they must not
  hide a discovery signal only because RR failed. Pipeline/persistence keeps
  market opportunities available with explicit decision metadata; the Radar
  API/service layer resolves `radar_display_mode` and decides which persisted
  opportunities are displayed to the user. RR is soft by default for discovery,
  research, virtual confirmation, and backtests; it affects execution
  eligibility only when the active RR guard mode is `hard`. Legacy
  strategy-risk flags such as `hide_failed_rr_signals`,
  `hide_low_rr_signals`, `show_only_active_setups`, and `only_active_setups`
  are backward-compatible display preferences only; the strategy pipeline must
  record that they were ignored and still persist the market opportunity.
- `RiskGate` is the single business boundary for virtual and real entry
  eligibility decisions. It consumes `RiskContext`, `TradePlan`, market quality,
  edge, and configured user risk settings. It does not decide whether a market
  setup exists.
- Virtual execution may be used for research and simulation after the risk gate
  decision. Real execution requires all real-entry gates to pass before any
  adapter can submit an order.
- `Outcome Labeling` observes persisted signals on closed candles and records
  entry touch, TP/SL/invalidation/expiry, R outcome, MFE, and MAE.
- `Strategy Performance` aggregates closed outcomes into daily strategy,
  regime, score-bucket, and direction analytics.
- `EV Gate` calibrates future signals from historical/forward outcomes. It does
  not rewrite the heuristic score; it produces the `edge` snapshot consumed by
  real-entry risk checks.

Real execution eligibility is stricter than discovery, research, virtual
confirmation, and backtests. A real entry must have: `risk passed`, no hard
no-trade result, positive edge, sufficient edge sample size, fresh market data,
valid orderbook, a valid liquidation price/buffer for futures, available
protective orders, valid exchange rules, and, when `real_rr_guard_mode = "hard"`
(the default), `RR passed`.

Virtual execution may continue to surface research warnings for weak RR,
unknown or weak edge, or incomplete context, but warnings must not be confused
with production permission to send exchange orders.

## Strategy Execution Profile v1

`StrategyExecutionSettings` is the typed contract stored over the existing
`user_strategy_configs.risk_settings` JSONB container. The saved user/strategy
execution profile is the source of truth before RiskGate. Request-level risk
changes are allowed only through the explicit `risk_override` object on
preview/confirm requests. The JSONB storage remains backward-compatible:
legacy keys are accepted, but execution settings are resolved through this
typed profile before RiskGate.

```python
RiskAmountMode = "percent" | "fixed"
RadarDisplayMode = "all_market_opportunities" | "execution_ready"
ExecutionMode = "virtual" | "real"
InstrumentType = "spot" | "futures"
RRGuardMode = "off" | "soft" | "hard"
RRTarget = "nearest" | "final"

StrategyExecutionSettings = {
    "risk_mode": RiskAmountMode,
    "risk_percent": Decimal | None,
    "fixed_risk_amount": Decimal | None,
    "fixed_risk_currency": str,
    "leverage": Decimal | None,
    "instrument_type": InstrumentType | None,
    "rr_guard_mode": RRGuardMode | None,
    "min_rr_ratio": Decimal | None,
    "rr_target": RRTarget | None,
    "radar_display_mode": RadarDisplayMode | None,
}

RiskOverride = {
    "risk_mode": RiskAmountMode,
    "risk_percent": Decimal | None,
    "fixed_risk_amount": Decimal | None,
    "leverage": Decimal | None,
}

RiskPreviewRequest = {
    "mode": ExecutionMode,
    "instrument_type": InstrumentType | None,
    "risk_percent": float | None,       # deprecated legacy field
    "risk_override": RiskOverride | None,
}

ManualConfirmRequest = {
    "mode": ExecutionMode,
    "risk_percent": float | None,       # deprecated legacy field
    "risk_override": RiskOverride | None,
}
```

Field meanings:

- `mode`: selected execution mode, `virtual` for simulation/paper execution or
  `real` for production-like exchange execution. It is not an instrument type.
- `risk_mode`: chooses whether the trade risk budget is a percent of current
  equity or a fixed currency amount.
- `risk_percent`: percent risk per trade when `risk_mode = "percent"`.
- `fixed_risk_amount`: fixed risk budget when `risk_mode = "fixed"`. Fixed
  mode without this amount is invalid.
- `fixed_risk_currency`: currency for the fixed budget, default `USDT`.
- `leverage`: requested/default execution leverage. It is not strategy input.
- `instrument_type`: selected execution instrument, `spot` or `futures`.
  `virtual` is deprecated as an `instrument_type` value and may be accepted
  only as a backward-compatible input adapter: it resolves `mode = "virtual"`
  and derives the actual instrument from explicit request/profile settings,
  exchange instrument rules, leverage, or default `spot`.
- `rr_guard_mode`: execution RR policy mode. `hard` can block execution;
  `soft` warns; `off` records RR only.
- `min_rr_ratio`: minimum RR used for reporting/execution policy. It is not a
  setup-discovery filter.
- `rr_target`: target used for RR policy, `nearest` or `final`.
- `radar_display_mode`: `all_market_opportunities` shows all strategy market
  setups; `execution_ready` shows only opportunities that currently pass the
  resolved execution profile and RiskGate preview.

Resolution precedence:

```text
request risk_override
> strategy execution settings in risk_settings JSONB
> user risk_management settings
> schema/config defaults
```

Radar display mode uses the same field-level precedence on the Radar surface:

```text
Radar query/request radar_display_mode
> matching strategy execution setting radar_display_mode
> user risk_management.radar_display_mode
> default "all_market_opportunities"
```

The Radar API may accept `radar_display_mode` as an explicit request override.
This override is a display contract only; it must not be passed into strategy
setup logic.

Radar `execution_ready` filtering uses a read-only RiskGate preview. `GET /radar`
must not persist `risk_decisions`, change signal status, or create
virtual trades while resolving display visibility. Manual/API risk preview
flows remain auditable.

## Signal Status Lifecycle v1

`SignalStatus` is the market setup lifecycle, not exchange-entry permission.
The canonical status meanings are:

- `new`: newly discovered setup that has not completed the shared pipeline.
- `active`: a market opportunity exists. It does not mean the user or system
  may enter now.
- `watchlist`: the setup is being observed and is not execution-ready.
- `ready`: the trade plan is structurally present, but entry may not be reached
  or confirmed yet.
- `wait_for_pullback`: the setup exists, but the strategy is waiting for
  pullback/retest/entry-zone conditions.
- `entry_touched`: price reached the entry zone; execution still needs the
  decision snapshot and RiskGate.
- `actionable`: the setup is an execution candidate for the current scope.
- `confirmed`: the user confirmed execution or intent.
- `invalidated`: the setup is no longer valid.
- `expired`: the setup exceeded its lifecycle TTL.
- `closed`: legacy signal-lifecycle close state. Filled/open/closed position
  states belong to trade lifecycle, not setup discovery.

Canonical helper groups:

```python
OPEN_SIGNAL_STATUSES = {
    "new",
    "active",
    "watchlist",
    "ready",
    "wait_for_pullback",
    "entry_touched",
    "actionable",
}

MARKET_OPPORTUNITY_STATUSES = OPEN_SIGNAL_STATUSES
WAITING_ENTRY_STATUSES = {"new", "active", "watchlist", "ready", "wait_for_pullback"}
EXECUTION_CANDIDATE_STATUSES = {"entry_touched", "actionable", "confirmed"}
TERMINAL_SIGNAL_STATUSES = {"invalidated", "expired", "closed", "rejected"}
```

`active` is an open market opportunity only. It must not be treated as
`can_enter`, execution-ready, auto-entry-ready, or real-order-ready.

Execution permission is:

```text
is_execution_candidate_status(signal.status)
AND decision snapshot allows the requested scope when present
AND RiskGate preview/confirm returns can_enter=true
AND real execution readiness passes for real orders
```

Radar `execution_ready` first applies `is_execution_candidate_status`, then
uses a read-only RiskGate preview. Manual virtual/real confirmation must run
RiskGate again on the current request. Real execution must run
`RealExecutionReadinessService` after RiskGate and before any adapter order.

Radar list contract:

```python
RadarFilters = {
    "exchange": str | None,
    "symbol": str | None,
    "timeframe": str | None,
}

GET /api/v1/radar(
    user_id: str,
    radar_display_mode: RadarDisplayMode | None,
    exchange: str | None,
    symbol: str | None,
    timeframe: str | None,
) -> RadarResponse

RadarResponse = {
    "signals": list[RadarSignal],
}
```

`RadarService.list_signals(user_id, mode, filters)` owns Radar display
filtering. API handlers must only parse request parameters and return the
service response. `SignalService` and the strategy pipeline must not filter
market opportunities by `radar_display_mode`.

Radar annotations on each returned `RadarSignal` are additive and may be
`null` for legacy rows or when a calculation was not needed:

```python
RadarSignal = {
    # existing fields remain unchanged
    "rr_status": "passed" | "warning" | "failed" | "skipped" | "unknown" | None,
    "risk_gate_status": "passed" | "warning" | "failed" | None,
    "can_enter": bool | None,
    "display_reason": str | None,
}
```

`rr_status` is copied from the centralized RR metadata when present, otherwise
derived as `unknown`. `risk_gate_status` and `can_enter` are set only when
Radar runs the read-only RiskGate preview. `display_reason` records why the
returned signal is visible for the resolved mode, for example all-market
visibility, non-actionable status, RiskGate allowed, or profile-resolution
warnings.

`all_market_opportunities` returns every open market setup matching filters,
including `new`, `active`, `watchlist`, `ready`, `wait_for_pullback`,
`entry_touched`, RR-blocked, warning, and actionable opportunities.
`execution_ready` first applies the centralized execution-candidate status
helper and then includes only signals whose read-only RiskGate preview returns
`can_enter = true`.

Legacy keys such as `risk_per_trade_percent`,
`futures_risk_per_trade_percent`, `spot_risk_per_trade_percent`, and
`virtual_risk_per_trade_percent` remain accepted and map to percent mode when
the new typed field is absent. The request fields
`RiskPreviewRequest.risk_percent` and `ManualConfirmRequest.risk_percent` are
deprecated and retained only for backward-compatible parsing/audit snapshots.
They are never considered explicit risk overrides by themselves, including the
legacy default `risk_percent = 10.0`, because older API clients used that value
as a request default. `risk_override.risk_mode = "percent"` requires
`risk_override.risk_percent`; `risk_override.risk_mode = "fixed"` requires
`risk_override.fixed_risk_amount`.

RiskGate contexts and decisions expose `mode` and `instrument_type`
separately. New code must never write `instrument_type = "virtual"` into
`RiskContext`, `RiskDecision`, market-data lookup, fee lookup, or risk-state
lookup. Futures-only checks, including liquidation checks, are selected by
`instrument_type == "futures"` or effective `leverage > 1`, never by
`mode == "virtual"`.

RiskGate decisions and risk audit snapshots expose the resolved
`risk_profile_source` (`request_override`, `strategy`, `user_profile`, or
`default`) plus field-level `execution_profile_sources` for debugging.

RiskGate risk-budget and sizing snapshots are additive and backward compatible.
Legacy fields stay present, while the resolved amount source is explicit:

```python
RiskAdjustmentPlan = {
    "risk_mode": RiskAmountMode,
    "fixed_risk_amount": float | None,
    "requested_risk_amount": float,
    "effective_risk_amount": float,
    "risk_amount_capped": bool,
    "risk_cap_amount": float | None,
    "risk_cap_percent": float | None,
    "base_risk_percent": float,      # retained legacy/public field
    "base_risk_amount": float,       # retained legacy/public field
    "adjusted_risk_percent": float,  # retained legacy/public field
    "adjusted_risk_amount": float,   # retained legacy/public field
}

PositionSizingResult = {
    "risk_mode": RiskAmountMode,
    "fixed_risk_amount": float | None,
    "requested_risk_amount": float | None,
    "effective_risk_amount": float | None,
    "risk_amount_capped": bool,
    "risk_cap_amount": float | None,
    "risk_per_trade_percent": float, # retained legacy/public field
    "risk_amount": float,            # retained legacy/public field
}
```

`requested_risk_amount` is the amount requested by the resolved execution
profile before risk caps and multipliers. `effective_risk_amount` on
`RiskAdjustmentPlan` is the final risk budget consumed by position sizing.
`PositionSizingResult.risk_amount` remains backward-compatible and equals the
amount used for quantity calculation. When a fixed risk amount is reduced by a
configured risk cap, RiskGate must surface an explicit warning and set
`risk_amount_capped = true`.

## Pipeline Layer Services v1

`StrategySignalPipeline.finalize(signal, context)` remains the public strategy
facade. Strategies continue to call it with a `StrategySignal` and
`StrategyEvaluationContext`; the facade orchestrates shared layers and attaches
snapshots to the signal without changing the strategy call contract.

`StrategyEvaluationContext` separates market setup parameters from execution
policy:

```python
StrategyEvaluationContext = {
    "signal_features": Features,
    "alpha_context": AlphaMarketContext | None,
    "context_features": Features | None,
    "context_features_by_timeframe": dict[str, Features],
    "support_resistance_by_timeframe": dict[str, SupportResistanceSnapshot],
    "strategy_params": dict,      # market setup / strategy logic only
    "execution_settings": StrategyExecutionSettings,
    "pipeline_settings": dict,    # transitional pipeline adapter
    "market_quality": MarketQualityInput | None,
    "pair_scope_configured": bool,
    "rr_guard_context": str,
}
```

`strategy_params` must not contain account balance, margin, position sizing,
fixed/percent risk amounts, user leverage, or Radar display mode. The strategy
engine passes only `strategy_params` plus market context to
`strategy.evaluate(...)`. Pipeline layers that need RR guard mode, `min_rr`,
`rr_target`, no-trade filters, display filtering, or execution eligibility
settings must read them from `execution_settings` or `pipeline_settings`.
`pipeline_settings` may merge strategy market params with typed execution
settings for backward-compatible pipeline checks, but it must not be passed to
strategy code.

Pipeline layer ownership:

- `SetupDetector` / setup layer: strategy-specific setup discovery and stage
  snapshots. This layer describes whether a setup is forming, ready, or
  confirmed; it must not calculate stops, targets, or execution permission.
- `TradePlanBuilder` / `TradePlanEnrichment`: ensures a `TradePlan` exists,
  enriches exits and invalidation, and attaches fallback/completeness metadata.
  It must not decide final status or auto-entry.
- `ContextScorer`: higher-timeframe regime, support/resistance, macro context,
  and score adjustment snapshots. It annotates context quality without hiding a
  valid setup except for explicit severe strategy filters.
- `SignalQualityService`: shared market quality and confirmation checks such as
  history, liquidity, spread, overextension, volume confirmation, and RR
  measurement. RR assessment records metrics and reasons separately from final
  status resolution.
- `SignalStatusResolver`: resolves setup validity, trade-plan completeness,
  closed/open candle gates, RR execution eligibility, no-trade blockers,
  invalidation, final `signal.status`, and `status_reason` from already
  calculated snapshots. It must not calculate targets or stops.
- `ExecutionEligibilityService`: resolves execution/auto-entry eligibility from
  completed snapshots. Disabled auto-entry must include an explicit reason and
  must not silently fallback to an executable path.

## Candle State Separation v1

Open candle evaluation is a live preview path. It may surface forming setups
for watchlist/research UI, but it must not silently create an actionable
signal.

Contracts:

- `CandleState = "open" | "closed"`.
- `Features.candle_state: CandleState = "closed"`.
- `StrategySignal.candle_state: CandleState = "closed"`.
- `RadarSignal.candle_state: CandleState = "closed"`.

`FeatureEngine.process_candles(candles)` sets `Features.candle_state` from the
latest candle: `"closed"` when `latest.is_closed` is true and `"open"` when it
is false. Tick/realtime fallback features are always `"open"` because they are
derived from live tick state rather than a closed OHLCV candle.

`StrategySignalPipeline.finalize()` applies the shared actionability gate:

- if `signal/features.candle_state == "open"` and
  `allow_open_candle_actionable != true`, the signal must be preview-only:
  status is kept non-actionable (`watchlist`), `auto_entry` is disabled, the
  confirmation layer records reason code `forming_candle`, and the explanation
  includes `forming candle preview`;
- if `allow_open_candle_actionable == true`, existing actionability behavior is
  allowed, but `trade_plan.metadata` and the `candle_state_gate` check must
  explicitly show `actionable_from_open_candle=true`;
- lower-timeframe trigger actionability is blocked unless
  `allow_lower_timeframe_trigger_actionable == true`. This flag defaults to
  false and must be visible in metadata when used.

`RadarSignal` responses expose the direct `candle_state` field. Persistence
keeps it in `features_snapshot.candle_state`; older rows without the field are
restored as `"closed"` for backward compatibility. The trade-plan metadata and
confirmation checks mirror candle-state/source flags for UI/debug.

Market scanner preview rules:

- signal timeframe evaluation may include the current open candle and therefore
  produces `"open"` preview features/signals;
- higher-timeframe context and support/resistance calculations must use closed
  context candles only, so an open HTF candle is never treated as confirmed
  context;
- closed-candle lifecycle/outcome/invalidation paths continue to use
  `include_open=False`.

## Backtest Runner v1

`ProductionBacktestRunner` is connected and is the production backtest service
runner for the legacy `/api/v1/backtests` surface. Production backtests replay
closed historical candles through the same service pipeline used by live signal
generation:

Historical candles -> FeatureEngine -> StrategyEngine/StrategySignalPipeline ->
RiskGate -> virtual execution/lifecycle simulation -> metrics.

Backtests must use closed candles only. They must not consume open candle
preview data, live scanner preview state, or any future candle information.
Generated backtest features, strategy signals, simulated trades, and journal
tags must carry `candle_state=closed`. If a provider returns open preview
candles, the runner must exclude them rather than marking them actionable.

`HistoricalCandleProvider` is the service boundary for loading candles:

```python
class HistoricalCandleProvider(Protocol):
    async def load_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[OHLCVCandle]:
        ...
```

Providers must return only closed candles ordered by `open_time` and must not
include candles outside `[start_at, end_at]`.

`BacktestRunRequest.params` may carry optional backtest configuration such as
`warmup_candles`, `rolling_window_candles`, `leverage`, `risk_settings`, signal
selection settings, position limits, and strategy params. Existing top-level
`fee_rate` and `slippage_bps` remain the execution cost inputs.

Signal selection settings:

- `signal_selection_policy`: `first_actionable`, `highest_score`,
  `all_non_overlapping`, or `all_signals`;
- `max_concurrent_positions`: maximum simultaneous simulated positions;
- `max_positions_per_symbol`: maximum simultaneous simulated positions for one
  `exchange + symbol`;
- `cooldown_bars_after_close`: number of bars that block re-entry after a
  same `exchange + symbol + timeframe + direction` position closes;
- `allow_opposite_signal_flip`: when false, an opposite direction signal for
  the same `exchange + symbol + timeframe` cannot open while a position is
  open.

Legacy `/api/v1/backtests` defaults remain `signal_selection_policy =
"first_actionable"` and `max_concurrent_positions = 1`. Strategy Test Lab
`discovery` and `research_virtual` scenarios default to
`all_non_overlapping` with conservative multi-position capacity unless request
params override them. Strategy Test Lab `production_like` defaults remain
`first_actionable` and one concurrent position unless overridden.

`BacktestResultResponse` keeps the existing top-level fields and adds v1
analytics in `metrics`:

- `selected_rr`, `rr_bucket`, `rr_pass_rate`
- `trades_count`, `wins`, `losses`, `winrate`
- `avg_win_r`, `avg_loss_r`, `expectancy_r`, `profit_factor`
- `realized_pnl`
- `max_drawdown_pct`
- `fees_total`, `slippage_total`, `funding_total`
- `avg_bars_in_trade`, `mfe_r_avg`, `mae_r_avg`
- `tp1_rate`, `tp2_rate`, `stop_rate`, `invalidation_rate`, `expiry_rate`
- `by_strategy`, `by_regime`

No-data failures must surface explicit `no_historical_data` or
`not_enough_data` errors instead of `not_implemented` when a runner is
configured. Research/report layers that cannot produce a valid metric sample
must return explicit `no_data` or `insufficient_data` status metadata rather
than fabricated baseline/backtest values.

`ProductionBacktestRunner.run(request)` remains backward-compatible and returns
only `BacktestRunResult`. `ProductionBacktestRunner.run_detailed(...)` is the
service-only Strategy Test Lab extension:

```python
BacktestDetailedRunResult = {
    "run_result": BacktestRunResult,
    "trades": list[BacktestSimulatedTrade],
    "signals_seen": int,
    "risk_rejections": int,
    "execution_rejections": int,
    "assumptions": dict,
}
```

`BacktestSimulatedTrade` rows are research observations only. They may be
converted to `StrategyTestTrade`, but must never be inserted into orders,
positions, portfolio balances, or live/virtual risk state.

## Strategy Testing v1

Strategy Test Lab is a separate research and simulation surface from the
legacy single-scenario backtest runner. It supports matrix-style runs across
pairs, strategies, timeframes, parameters, assumptions, and modes.

LAB-01 adds a synchronous Strategy Lab orchestration surface for batch/matrix
research runs on top of `ProductionBacktestRunner.run_detailed`:

```text
POST /api/v1/strategy-lab/run
POST /api/v1/strategy-lab/matrix
```

The API layer validates the request and calls `StrategyTestLabService`. It must
not contain strategy, backtest, comparison, or persistence logic.

LAB-01 request modes are comparison modes, not real execution permissions:

```python
StrategyLabMode = "baseline" | "experiment"
```

`baseline` records a reference research run. `experiment` records a candidate
research run that can be compared against a baseline. Both are executed with
safe research/backtest assumptions and must not call `RealExecutionService`,
exchange adapters, scanner mutation paths, order writers, position writers,
portfolio balance writers, or live/virtual `risk_state` writers.

`StrategyLabRunRequest` is the single-scenario request. It uses the same fields
as `StrategyLabMatrixRequest`, but `strategies`, `symbols`, and `timeframes`
must each contain exactly one item.

```python
StrategyLabMatrixRequest = {
    "user_id": str,
    "exchange": str,
    "strategies": list[str],
    "symbols": list[str],
    "timeframes": list[str],
    "start_time": datetime,
    "end_time": datetime,
    "initial_equity": Decimal,
    "fees_bps": Decimal,
    "slippage_bps": Decimal,
    "max_bars_in_trade": int | None,
    "warmup_bars": int,
    "mode": StrategyLabMode,
    "label": str | None,
    "tags": dict[str, str],
    "params": dict,
    "strategy_version": str | None,
}
```

The service expands every `strategy x symbol x timeframe` scenario into a
backward-compatible `BacktestRunRequest`. Fee bps are converted to
`BacktestRunRequest.fee_rate`; `warmup_bars` is forwarded as
`params.warmup_candles`; `max_bars_in_trade` is forwarded as scenario metadata.

Every scenario must carry these structured tags:

```python
StrategyLabTags = {
    "source": "strategy_lab",
    "mode": "baseline" | "experiment",
    "lab_run_id": str,
    "strategy": str,
    "symbol": str,
    "timeframe": str,
    "candle_state": "closed",
}
```

`StrategyLabRunSummary` is the comparison metric contract:

```python
StrategyLabRunSummary = {
    "status": "completed" | "no_data" | "insufficient_data" | "failed",
    "total_trades": int | None,
    "win_rate": float | None,
    "profit_factor": float | None,
    "expectancy_r": float | None,
    "avg_r": float | None,
    "max_drawdown": float | None,
    "avg_bars_in_trade": float | None,
    "stop_rate": float | None,
    "tp1_rate": float | None,
    "final_target_rate": float | None,
    "fees_paid": Decimal | None,
    "slippage_paid": Decimal | None,
    "risk_rejections": int | None,
    "execution_rejections": int | None,
    "fallback_used_count": int | None,
    "incomplete_trade_plan_count": int | None,
    "signals_seen": int | None,
}
```

`StrategyLabComparisonResult` returns `overall_summary`,
`metrics_by_strategy`, `metrics_by_symbol`, `metrics_by_timeframe`, and the
expanded `runs`. Historical-data failures must be explicit: runner
`no_historical_data` errors become `no_data`, runner `not_enough_data` errors
become `insufficient_data`, and metrics must remain empty for those scenarios.

## LAB-02 Baseline Harness

`scripts/run_strategy_baseline.py` is the reproducible local baseline harness
for current strategies before AUD-02..AUD-10 behavior changes. It is not an API
surface and it does not persist orders, positions, portfolio balances, scanner
state, or live/virtual `risk_state`.

The baseline matrix must use real strategy codes from `backend/app/strategies`:

- `liquidity_sweep_reversal`
- `volatility_squeeze_breakout`
- `trend_pullback_continuation`

The script accepts a JSON config or CLI flags for:

- `symbols`, `timeframes`, `start_time`, `end_time`
- `initial_equity`, `fees_bps`, `slippage_bps`
- `warmup_bars`, `max_bars_in_trade`
- per-strategy `strategy_params` overrides
- `output_path`

Baseline output is machine-readable JSON:

```python
StrategyBaselineOutput = {
    "baseline_id": str,
    "baseline_version": str,
    "run_id": str,
    "lab_run_ids": list[str],
    "created_at": str,
    "code_revision": str | None,
    "code_revision_available": bool,
    "status": "completed" | "no_data" | "insufficient_data" | "failed",
    "tags": dict[str, str],
    "config": dict,
    "summary": dict,
    "results": list[StrategyBaselineScenario],
}

StrategyBaselineScenario = {
    "run_id": str,
    "baseline_id": str,
    "scenario_id": str,
    "status": "completed" | "no_data" | "insufficient_data" | "failed",
    "strategy": str,
    "exchange": str,
    "symbol": str,
    "timeframe": str,
    "tags": dict[str, str],
    "metrics": dict[str, int | float | str | None],
    "assumptions": dict,
    "error": str | None,
    "created_at": str,
}
```

Every scenario tag must include `source=baseline`, `baseline_version`,
`strategy`, `symbol`, `timeframe`, `candle_state=closed`, `created_at`, and
`code_revision` when it can be read safely from git. Scenarios without
historical candles must be reported as `no_data`; scenarios with too few
closed candles must be reported as `insufficient_data`. Missing baseline metrics
must be `null`, not fabricated zero values.

Canonical discovery test flow:

```text
Historical candles
-> FeatureEngine
-> StrategyEngine
-> StrategySignal
-> Entry/Stop/Targets
-> outcome simulation
-> metrics
```

Canonical research virtual test flow:

```text
Historical candles
-> FeatureEngine
-> StrategyEngine
-> StrategySignal
-> virtual execution simulation
-> lifecycle simulation
-> metrics
```

Canonical production-like test flow:

```text
Historical candles
-> FeatureEngine
-> StrategyEngine
-> StrategySignal
-> RiskGate
-> execution simulation
-> metrics
```

Boundary rules:

- `discovery` and `research_virtual` are research/alpha modes.
- `production_like` is the execution/risk-gate realism mode.
- Research results must not be interpreted as real execution permission.
- backtest trades must not pollute live/virtual portfolio risk state.
- Backtest trades are surfaced in the journal with `source/tag = backtest`.
- Backtest trades must not insert rows into `orders`.
- Backtest trades must not insert rows into `positions`.
- Backtest trades must not update portfolio balances or `risk_state`.
- Journal visibility for backtest trades must come from
  `StrategyTestJournalAdapter`.

`StrategyTestMode` is the execution realism level for a lab run:

```python
StrategyTestMode = "discovery" | "research_virtual" | "production_like"
```

`StrategyTestAssumptions` records deterministic execution assumptions for one
lab run or scenario:

```python
StrategyTestAssumptions = {
    "mode": StrategyTestMode,
    "fee_rate": Decimal,
    "slippage_bps": Decimal,
    "same_candle_policy": "stop_first" | "target_first" | "ignore_ambiguous",
    "initial_capital": Decimal,
    "rr_hard_gate_enabled": bool,
    "risk_gate_enabled": bool,
    "virtual_execution_enabled": bool,
    "lifecycle_enabled": bool,
    "notes": list[str],
}
```

Mode assumptions:

- `discovery`: risk-gate and RR hard execution blocking are disabled for
  research; any evaluated hard blockers are surfaced as warnings.
- `research_virtual`: virtual execution/lifecycle simulation is enabled, but
  risk-gate and RR hard blockers are surfaced as warnings or blocked
  eligibility reasons instead of deleting discovery observations.
- `production_like`: risk gate is enabled; RR hard gate is enabled unless the
  request params explicitly disable it.

`StrategyTestPair` identifies one market/timeframe input in a matrix:

```python
StrategyTestPair = {
    "exchange": str,
    "symbol": str,
    "timeframe": str,
}
```

`StrategyTestRun` records one requested or completed lab run:

```python
StrategyTestRun = {
    "run_id": str,
    "mode": StrategyTestMode,
    "status": "queued" | "running" | "completed" | "failed" | "cancelled",
    "pairs": list[StrategyTestPair],
    "strategy_codes": list[str],
    "started_at": datetime | None,
    "completed_at": datetime | None,
    "params": dict,
    "assumptions": dict,
    "metadata": dict,
}
```

`StrategyTestMatrix` is the expanded deterministic set of scenarios produced
from a lab request:

```python
StrategyTestMatrix = {
    "run_id": str,
    "mode": StrategyTestMode,
    "pairs": list[StrategyTestPair],
    "strategy_codes": list[str],
    "parameter_sets": list[dict],
    "assumption_sets": list[dict],
    "scenario_count": int,
}
```

`StrategyTestMatrixResult` is the synchronous service result produced by the
matrix runner before run status finalization:

```python
StrategyTestMatrixResult = {
    "run_id": UUID,
    "scenario_count": int,
    "completed_scenarios": int,
    "failed_scenarios": int,
    "scenario_summaries": list[dict],
    "errors": list[dict],
    "trades": list[StrategyTestTrade],
}
```

`StrategyTestTrade` is a simulated trade-level analytics observation stored in
ClickHouse. It is not an order, position, balance event, or risk-state
mutation:

```python
StrategyTestTrade = {
    "run_id": UUID,
    "trade_id": str,
    "user_id": UUID,
    "mode": StrategyTestMode,
    "strategy_code": str,
    "strategy_version": str,
    "exchange": str,
    "symbol": str,
    "timeframe": str,
    "direction": str,
    "signal_score": float | None,
    "market_regime": str,
    "score_bucket": str,
    "entry_time": datetime,
    "exit_time": datetime | None,
    "entry_price": Decimal,
    "exit_price": Decimal | None,
    "stop_loss": Decimal | None,
    "targets": list[dict],
    "selected_rr": float | None,
    "realized_r": float | None,
    "pnl": Decimal,
    "pnl_pct": float,
    "fees": Decimal,
    "slippage": Decimal,
    "mfe_r": float | None,
    "mae_r": float | None,
    "bars_to_entry": int | None,
    "bars_in_trade": int | None,
    "close_reason": str,
    "outcome": str,
    "risk_rejected": bool,
    "execution_rejected": bool,
    "warnings": list[str],
    "features_snapshot": dict,
    "trade_plan": dict,
    "tags": list[str],
    "created_at": datetime,
}
```

`TradeJournalEntry` is the unified journal projection returned by
`GET /api/v1/trades`. It keeps execution `mode` backward-compatible as
`"virtual" | "real"` and uses separate source metadata to expose research
trades without inserting them into execution-state tables:

```python
TradeJournalEntry = {
    # existing virtual/real journal fields remain unchanged
    "mode": "virtual" | "real",
    "source": "virtual" | "real" | "backtest",
    "tags": list[str],
    "run_id": UUID | None,
}
```

Virtual journal entries default to `source="virtual"`, `tags=[]`, and
`run_id=None`. Real journal entries use `source="real"`. Strategy Test Lab
journal projections use `mode="virtual"`, `source="backtest"`, include the
`backtest` tag, and carry the Strategy Test Lab `run_id`.

`StrategyTestMetric` is a named deterministic metric emitted by the metrics
registry:

```python
MetricDefinition = {
    "code": str,
    "label": str,
    "description": str,
    "groupings": list[str],
    "compute": Callable[[Sequence[StrategyTestTrade]], float | int | None],
    "min_sample_size": int,
}

MetricResult = {
    "code": str,
    "label": str,
    "value": float | int | None,
    "sample_size": int,
    "group": dict[str, str],
    "warnings": list[str],
}

MetricRegistry = {
    "register(definition)": None,
    "get(code)": MetricDefinition,
    "list_definitions()": list[MetricDefinition],
    "compute(trades, metric_set=None, group_by=None)": list[MetricResult],
}

StrategyTestMetric = {
    "run_id": str,
    "scenario_id": str | None,
    "name": str,
    "value": int | float | str | bool | None,
    "unit": str | None,
    "group": dict,
    "confidence": "high" | "medium" | "low" | "insufficient_sample",
    "metadata": dict,
}
```

Grouped Strategy Test Lab metric rows may also be stored in ClickHouse:

```python
StrategyTestMetricRow = {
    "run_id": UUID,
    "user_id": UUID,
    "mode": StrategyTestMode,
    "strategy_code": str,
    "exchange": str,
    "symbol": str,
    "timeframe": str,
    "market_regime": str,
    "score_bucket": str,
    "direction": str,
    "metric_code": str,
    "metric_value": float | None,
    "sample_size": int,
    "metadata": dict,
    "created_at": datetime,
}
```

`StrategyTestReport` is the read model returned by report endpoints:

```python
StrategyTestReport = {
    "run": StrategyTestRun,
    "matrix": StrategyTestMatrix,
    "summary_metrics": list[StrategyTestMetric],
    "grouped_metrics": list[StrategyTestMetric],
    "trades_count": int,
    "warnings": list[str],
    "rejections": list[str],
    "assumptions": dict,
    "created_at": datetime,
}
```

`TradePlan` is a backward-compatible v1 signal contract generated from the
legacy signal entry/stop/target fields. Existing signal fields remain available:
`entry_min`, `entry_max`, `stop_loss`, `take_profit_1`, `take_profit_2`,
`risk_reward`, `first_target_rr`, `final_target_rr`, `selected_rr`,
`selected_rr_target`, and `min_rr_ratio`.

`TradePlan` is persisted in `features_snapshot.trade_plan` and restored to
`StrategySignal.trade_plan` / `RadarSignal.trade_plan` when present.

RR target basis is resolved from `TradePlan` before RR calculation.
`nearest` means the first executable target in plan order; `final` means the
last planned priced/executable target after TradePlan normalization. Legacy
`take_profit_1` / `take_profit_2` fields are adapted into TradePlan targets
before RR is calculated. When an enriched TradePlan contains a later structural
target such as a measured move, `final_target_rr` represents that final
TradePlan target rather than being capped to legacy `take_profit_2`.

Trade plan completeness is explicit:

- A complete structural trade plan has a market-based entry model, structural
  stop, invalidation thesis, and structural target thesis.
- A fallback trade plan may use a fallback ATR stop, fallback R-multiple
  targets, or both. Fallback is allowed for `research_mode`, but it must set
  `metadata.fallback_used = true` and the more specific flags
  `metadata.fallback_stop_used` and/or `metadata.fallback_targets_used`.
- A production actionable signal requires a complete structural trade plan.
  Fallback plans may remain visible for research/backtest/watchlist purposes,
  but they must not be silently treated as complete production plans.

`TradePlanCompletenessResult` is the service-level result attached to
`TradePlan.metadata.trade_plan_completeness` and mirrored into
`TradePlan.risk_rules.metadata` as summary flags:

```python
TradePlanCompletenessResult = {
    "complete": bool,
    "fallback_used": bool,
    "fallback_stop_used": bool,
    "fallback_targets_used": bool,
    "has_entry": bool,
    "has_structural_stop": bool,
    "has_invalidation_thesis": bool,
    "has_structural_target": bool,
    "has_score": bool,
    "has_context": bool,
    "missing": list[str],          # legacy structural names
    "missing_fields": list[str],   # normalized names: entry/stop/target/score/context
    "warnings": list[str],
    "blockers": list[str],
    "execution_allowed_virtual": bool,
    "execution_allowed_real": bool,
    "metadata": dict,
}
```

Summary metadata keys are additive and backward-compatible:
`trade_plan_complete`, `fallback_used`, `fallback_stop_used`,
`fallback_targets_used`, `has_entry`, `has_structural_stop`,
`has_invalidation_thesis`, `has_structural_target`, `has_score`,
`has_context`, `missing`, `missing_fields`, `warnings`, `blockers`,
`research_mode`, `production_mode`, `signal_actionable`,
`execution_allowed_virtual`, and `execution_allowed_real`.

`TradePlanCompletenessService.assess(signal, trade_plan)` is the normalized
service boundary for this result. Pipeline, Radar display filtering, and
RiskGate must consume the same normalized assessment instead of re-implementing
entry/stop/target/score/context rules locally. The older
`TradePlanCompletenessCheck.evaluate(trade_plan)` name remains a
backward-compatible facade over the service.

Completeness field policy:

- Missing `entry`, structural `stop`, or structural `target` is a blocker for
  virtual and real execution, but it must not delete the market opportunity.
- Missing score or context is evaluated by config:
  `trade_plan_missing_score_policy` and `trade_plan_missing_context_policy`
  support `warning`, `block`, and `off`. Defaults are `warning`.
- `complete` means blocker-level structural completeness for the active policy.
  `missing_fields` may still include warning-level `score` or `context` gaps.
- `execution_allowed_virtual` and `execution_allowed_real` on the assessment
  are completeness-layer permissions. They are not a substitute for the final
  RiskGate or real-readiness decision.

In `research_mode`, incomplete or fallback plans remain visible with a
`trade_plan_completeness` warning/block check according to the normalized
assessment. In `production_mode`, a blocker-level incomplete or fallback plan
makes the signal non-actionable, disables auto-entry metadata, and sets
virtual/real execution eligibility false for the completeness layer. Real
risk-gate evaluation blocks an explicit incomplete `TradePlan`; research and
backtest contexts may keep the market opportunity visible with reasons.

Strategy trade plans are level-aware when strategy context exposes structure:

- `trend_pullback_continuation` uses a structural pullback-zone entry model:
  VWAP/deviation, liquidity/session/PDH/PDL levels, HTF support/resistance,
  imbalance/orderbook walls, and EMA20/EMA50 fallback may all be recorded as
  the selected pullback zone. Structure-aware TP1/TP2 and `time_stop_bars`
  remain backward compatible in `TradePlan.risk_rules.metadata`.
- `volatility_squeeze_breakout` records `aggressive_breakout` or
  `conservative_retest` entry metadata and stores the measured move as an
  executable `TradePlanTarget` when enabled.
- `liquidity_sweep_reversal` uses range midpoint and opposite boundary targets
  where available.

## Market-Based Exits / TargetThesis AUD-10

`TradePlanTarget` remains backward compatible and adds optional
`thesis: TargetThesis | None`. Legacy clients may ignore it and continue to
read `price`, `r_multiple`, `source`, and `metadata`.

```python
TargetSource = (
    "nearest_liquidity_pool"
    | "previous_day_high"
    | "previous_day_low"
    | "session_high"
    | "session_low"
    | "range_midpoint"
    | "range_opposite_boundary"
    | "vwap"
    | "vwap_deviation_band"
    | "htf_support"
    | "htf_resistance"
    | "measured_move"
    | "risk_multiple_fallback"
)

TargetThesis = {
    "source": TargetSource,
    "price": float | None,
    "direction": "LONG" | "SHORT",
    "confidence": float,
    "priority": int,
    "close_percent": float | None,
    "requires_acceptance": bool,
    "invalidation_hint": str | None,
    "metadata": dict,
}
```

`TargetResolverService` is the service boundary for resolving ordered target
theses from already available `Features`, optional `AlphaMarketContext`,
higher-timeframe support/resistance snapshots, and strategy metadata. It must
not call exchange, DB, Redis, or API sources. It filters target prices by
direction: LONG targets are above entry, SHORT targets are below entry.

R-multiple targets are represented by `source="risk_multiple_fallback"` and
must set fallback metadata. They are allowed only when explicitly requested for
research/backtest fallback, and fallback-only target plans are incomplete for
production actionability. Trade-plan completeness treats a target as structural
when `TargetThesis.source != "risk_multiple_fallback"` or the legacy target
source is structural.

Backtest and Strategy Lab params may include:

- `exit_policy`: `legacy_r_multiple`, `market_targets`, `liquidity_first`,
  `structure_runner`, or `measured_move_after_acceptance`;
- `target_sources_enabled`: list of enabled `TargetSource` values;
- `partial_exit_policy`: source-specific partial/main/final mapping;
- `allow_r_multiple_fallback`: explicit research fallback flag.

Backtest metrics include grouped exit views:

- `by_exit_policy`
- `by_first_target_source`
- `by_final_target_source`
- `by_runner_used`
- `by_fallback_target_used`

Strategy runtime params include:

- `trend_pullback_continuation.entry_model`
- `trend_pullback_continuation.max_overextension_atr`
- `trend_pullback_continuation.require_htf_alignment`
- `trend_pullback_continuation.time_stop_bars`
- `volatility_squeeze_breakout.allow_aggressive_entry`
- `volatility_squeeze_breakout.require_retest_after_large_candle`
- `volatility_squeeze_breakout.large_candle_body_atr`
- `volatility_squeeze_breakout.measured_move_target_enabled`
- `volatility_squeeze_breakout.oi_expansion_threshold`
- `volatility_squeeze_breakout.oi_expansion_bonus`
- `volatility_squeeze_breakout.oi_no_expansion_penalty`
- `volatility_squeeze_breakout.require_delta_expansion`
- `volatility_squeeze_breakout.require_oi_expansion`
- `volatility_squeeze_breakout.min_delta_expansion_score`
- `volatility_squeeze_breakout.min_oi_expansion_score`
- `volatility_squeeze_breakout.accepted_breakout_min_score`
- `volatility_squeeze_breakout.fakeout_risk_max_score`
- `liquidity_sweep_reversal.require_reclaim`
- `liquidity_sweep_reversal.require_absorption`
- `liquidity_sweep_reversal.min_absorption_score`
- `liquidity_sweep_reversal.min_cvd_divergence_score`
- `liquidity_sweep_reversal.min_oi_flush_score`
- `liquidity_sweep_reversal.min_obvious_liquidity_score`
- `liquidity_sweep_reversal.min_target_distance_r`
- `liquidity_sweep_reversal.alpha_context_required`
- `liquidity_sweep_reversal.require_oi_flush`
- `liquidity_sweep_reversal.max_obstacle_distance_r`
- `liquidity_sweep_reversal.oi_flush_threshold`
- `liquidity_sweep_reversal.oi_flush_bonus`
- `liquidity_sweep_reversal.liquidation_flush_bonus`
- `trend_pullback_continuation.funding_warning_threshold`
- `trend_pullback_continuation.funding_block_threshold`
- `trend_pullback_continuation.crowded_oi_change_threshold`
- `trend_pullback_continuation.crowded_oi_penalty`
- `trend_pullback_continuation.require_structural_zone`
- `trend_pullback_continuation.require_delta_confirmation`
- `trend_pullback_continuation.require_absorption_or_reclaim`
- `trend_pullback_continuation.min_zone_quality_score`
- `trend_pullback_continuation.min_continuation_score`
- `trend_pullback_continuation.max_exhaustion_score`
- `trend_pullback_continuation.min_htf_target_distance_r`

`Features` may expose intraday range context for level-aware strategies:
`session_high`, `session_low`, `previous_day_high`, and `previous_day_low`.

`Features` may expose derivative context when a hot derivative snapshot is
available:

- `funding_rate`: current exchange funding rate;
- `oi_change`: fractional open-interest change versus the previous derivative
  snapshot, or `None` when current or previous open interest is unavailable.

`DerivativeMarketSnapshot` keeps backward-compatible market context fields and
may include:

- `open_interest`
- `open_interest_value`
- `oi_change`

`oi_change` is calculated only from real exchange-provided open interest:
`(current_open_interest - previous_open_interest) / previous_open_interest`.
It remains `None` when the exchange omits open interest or no previous open
interest exists.

## Alpha Market Context v1

AUD-06 adds an optional alpha/context layer between `Features` and strategy
evaluation. The layer turns available orderflow, derivative, orderbook, and
level-reaction data into a strategy-readable `AlphaMarketContext` without
letting strategies call APIs, DB, Redis, or exchanges directly.

`MarketData` remains backward compatible and may include optional normalized
trade identity:

- `trade_id: str | None`
- `side: "buy" | "sell" | None`
- `is_buyer_maker: bool | None`

When trade side is unavailable, buy/sell volume, aggressive delta, and CVD must
remain `None`; the alpha context must record `recent_trade_side` in
`data_quality.missing_sources` instead of inferring side from price movement.

`AlphaMarketContext` is optional for strategy evaluation and backtests. Live
scanner orchestration may pass it through `StrategyEvaluationContext` and
runtime params after it has been built by services. Strategies may read it, but
must remain pure trading logic.

```python
RecentTrade = {
    "exchange": str,
    "symbol": str,
    "price": float,
    "quantity": float,
    "timestamp": int,
    "side": "buy" | "sell" | None,
    "trade_id": str | None,
    "is_buyer_maker": bool | None,
}

RecentTradesAggregate = {
    "trades_count": int,
    "buy_volume": float | None,
    "sell_volume": float | None,
    "total_volume": float,
    "aggressive_delta": float | None,
    "cvd": float | None,
    "side_available": bool,
}

AlphaMarketContext = {
    "symbol": str,
    "timeframe": str,
    "timestamp": int,
    "buy_volume": float | None,
    "sell_volume": float | None,
    "aggressive_delta": float | None,
    "cvd": float | None,
    "cvd_change": float | None,
    "delta_divergence": str | None,
    "oi_delta_5m": float | None,
    "oi_delta_15m": float | None,
    "funding_rate": float | None,
    "funding_pressure": float | None,
    "liquidation_proximity": float | None,
    "liquidation_clusters": list[dict] | None,
    "orderbook_imbalance": float | None,
    "bid_depth_usd": float | None,
    "ask_depth_usd": float | None,
    "depth_wall_side": "bid" | "ask" | "none" | None,
    "depth_wall_price": float | None,
    "absorption_score": float | None,
    "sweep_through_book": bool | None,
    "session_liquidity_pools": list[dict],
    "pdh_pdl_reaction": str | None,
    "vwap_deviation": float | None,
    "vwap_acceptance": str | None,
    "data_quality": dict,
}
```

Market-quality/risk orderbook usage remains separate from alpha/context
orderflow usage:

- `RiskMarketDataService` reads L2 to decide spread, depth, freshness, and real
  or virtual entry eligibility.
- `AlphaMarketContextService` reads the same normalized hot L2 snapshot only as
  alpha evidence: imbalance, depth-wall side/price, and optional absorption or
  sweep-through-book annotations.

Backtests must not use future or live alpha data. When historical trades, L2,
or derivative history are unavailable, backtest assumptions and trade metadata
must expose `alpha_context_available=false` and
`alpha_context_missing_sources` rather than filling synthetic orderflow values.

## Trend Pullback AUD-09 Additive Metadata

`trend_pullback_continuation` keeps the existing `StrategySignal` and
`TradePlan` schemas. AUD-09 adds only internal strategy structures plus
additive trade-plan and decision metadata.

The selected structural pullback zone may be written to
`TradePlan.metadata.structural_pullback_zone`,
`TradePlan.entry.metadata.structural_pullback_zone`,
`TradePlan.risk_rules.metadata.structural_pullback_zone`, and
`TradePlan.invalidation.metadata.structural_pullback_zone`:

```python
StructuralPullbackZone = {
    "source": (
        "vwap" | "vwap_deviation" | "liquidity_pool" | "imbalance" |
        "ema20" | "ema50" | "range_boundary" | "htf_support_resistance"
    ),
    "price": float,
    "distance_atr": float,
    "quality_score": float,
    "metadata": dict,
}
```

The strategy may also write:

```python
TrendPullbackMetadata = {
    "structural_zone_source": str | None,
    "structural_zone_price": float | None,
    "structural_zone_quality_score": float | None,
    "require_structural_zone": bool,
    "structural_zone_ok": bool,
    "continuation_score": float,
    "min_continuation_score": float,
    "delta_confirmed": bool,
    "absorption_confirmed": bool,
    "reclaimed_pullback_zone": bool,
    "exhaustion_score": float,
    "exhaustion_reasons": list[str],
    "max_exhaustion_score": float,
    "crowded_trade_score": float,
    "crowded_trade_reasons": list[str],
    "funding_pressure": float | None,
    "funding_rate": float | None,
    "oi_delta": float | None,
    "nearest_htf_target": float | None,
    "nearest_htf_target_source": str | None,
    "nearest_htf_target_distance_r": float | None,
    "min_htf_target_distance_r": float,
    "alpha_context_used": bool,
    "missing_alpha_sources": list[str],
}
```

Trend pullback confirmation checks may add `DecisionReason` entries with
codes `trend_structural_zone`, `trend_continuation_confirmation`,
`trend_exhaustion`, `trend_crowded_trade`, and `trend_htf_target_room`.
`trend_exhaustion` is setup-sourced by default. `trend_crowded_trade` is
risk-sourced and is a warning by default; it becomes a blocker only when an
explicit hard crowded-trade setting is enabled. Missing `AlphaMarketContext`
must be recorded in `missing_alpha_sources` and must not be silently converted
into zero delta, CVD, OI, or funding evidence.

## Liquidity Sweep Reversal AUD-07 Additive Metadata

`liquidity_sweep_reversal` keeps the existing `StrategySignal` and `TradePlan`
schemas. AUD-07 adds only strategy/trade-plan metadata and runtime params.

The strategy may write `TradePlan.metadata.liquidity_sweep_score_breakdown`:

```python
LiquiditySweepScoreBreakdown = {
    "obvious_liquidity_score": float,      # 0..1
    "reclaim_score": float,                # 0..1
    "absorption_score": float,             # 0..1
    "cvd_divergence_score": float,         # 0..1
    "oi_flush_score": float,               # 0..1
    "liquidation_flush_score": float,      # 0..1
    "failed_continuation_score": float,    # 0..1
    "htf_target_distance_r": float | None,
    "market_target_source": str | None,
    "alpha_context_used": bool,
    "missing_alpha_sources": list[str],
}
```

Targets remain `TradePlanTarget` objects. When a market target is available,
target `source` and `metadata.market_target_source` identify the market level,
such as `range_midpoint`, `swing_high`, `session_high`,
`previous_day_low`, `liquidity_pool_*`, or `htf_1h_resistance`. If no market
target exists, fallback R-multiple targets remain explicitly marked through the
existing fallback metadata.

Missing alpha context is never silently filled. If no `AlphaMarketContext` is
provided, `alpha_context_used=false` and `missing_alpha_sources` includes
`alpha_context`; candle/volume proxy evidence may still be scored as research
context. Backtests without historical alpha data continue to expose
`alpha_context_available=false` and do not synthesize CVD, L2, derivative, or
liquidation values.

## Volatility Squeeze Breakout AUD-08 Additive Metadata

`volatility_squeeze_breakout` keeps the existing `StrategySignal` and
`TradePlan` schemas. AUD-08 adds strategy/trade-plan metadata for classifying
accepted breakouts versus liquidity raids/fakeouts.

The strategy may write these additive metadata keys to `TradePlan.metadata`,
`TradePlan.entry.metadata`, `TradePlan.risk_rules.metadata`, and
`TradePlan.invalidation.metadata`:

```python
BreakoutAcceptanceMetadata = {
    "accepted_breakout_score": float,      # 0..1
    "fakeout_risk_score": float,           # 0..1
    "post_breakout_hold_score": float,     # 0..1
    "retest_quality_score": float,         # 0..1
    "delta_expansion_score": float,        # 0..1
    "oi_expansion_score": float,           # 0..1
    "volume_acceptance_score": float,      # 0..1
    "failed_breakout_invalidation": bool,
    "retest_required": bool,
    "alpha_context_used": bool,
    "missing_alpha_sources": list[str],
}
```

`entry_model` remains backward-compatible and records
`aggressive_breakout` or `conservative_retest`. `TradePlan.entry.source` may
identify the executable source more specifically as `aggressive_breakout`,
`breakout_retest`, or `conservative_breakout`.

Accepted breakout scoring uses candle close outside the compression range,
directional close location, body quality, volume/VWAP acceptance, ATR
expansion, optional delta expansion, optional OI expansion, and hold/retest
quality around the broken level. Missing alpha context is never silently filled:
`alpha_context_used=false` and `missing_alpha_sources` includes
`alpha_context` when no `AlphaMarketContext` is supplied.

Fakeout risk scoring uses wick-through-and-close-back-inside behavior, failed
hold on the next evaluation, missing or weak delta/OI confirmation when
available or required, low volume/VWAP acceptance, large candle without hold,
crowded funding/OI pressure, and sweep-through-book without acceptance when
available.

Optional confirmation params are disabled by default and must not become
hardcoded mandatory gates:

- `require_delta_expansion: bool = false`
- `require_oi_expansion: bool = false`
- `min_delta_expansion_score`
- `min_oi_expansion_score`
- `accepted_breakout_min_score`
- `fakeout_risk_max_score`
- `require_retest_after_large_candle`

When a large or fakeout-prone breakout requires a conservative retest, the
pipeline emits a setup warning with
`code="retest_required_after_large_breakout"`, `source="setup"`, and
`scope="discovery"` unless a stricter scope is explicitly configured.

Breakout invalidation remains backward compatible with the legacy hard stop,
but the structural invalidation thesis must include close back inside the
range, loss of the breakout level, failed retest back inside the old range, and
delta/OI reversal against continuation when that data is available.

Risk gate consumes `RiskContext.trade_plan` when it is present. Take-profit
precedence is:

1. `manual_take_profit_price` explicit override;
2. `trade_plan.targets` from the signal;
3. risk-settings generated `calculate_take_profit_plan` fallback only when the
   signal has no `trade_plan`.

Malformed `TradePlan` take-profit data must fail the risk decision instead of
silently falling back to risk-settings targets. Validation rules:

- long targets must be above entry;
- short targets must be below entry;
- stop loss must be on the risk side of entry;
- target `r_multiple` is recalculated from actual entry/stop/target prices;
- each executable target must have `close_percent > 0`;
- total executable `close_percent` must not exceed 100.

`TakeProfitPlan.source` records `manual_override`, `trade_plan`,
`trade_plan_invalid`, or `risk_settings`. `TakeProfitPlan.selected_rr` /
`selected_rr_target` record the RR actually used by risk checks; for
`trade_plan`, `selected_rr_target` is read from
`TradePlan.risk_rules.selected_rr_target` when provided.

## Virtual Trade Lifecycle v1

`VirtualTrade` keeps the legacy execution fields (`size_usd`, `quantity`,
`stop_loss`, `take_profit`, `fees`, `pnl`, `close_reason`) for backward
compatibility. `take_profit` remains `list[float]` and continues to represent
the legacy target price list.

Lifecycle-aware virtual trades also expose:

- `initial_quantity`, `remaining_quantity`, `closed_quantity`
- `initial_size_usd`, `remaining_size_usd`
- `current_stop_loss`, `stop_moved_to_breakeven`, `trailing_active`
- `realized_pnl`, `unrealized_pnl`, `exit_fees`
- `target_states: list[VirtualTradeTargetState]`
- `lifecycle_events: list[VirtualTradeLifecycleEvent]`

`target_states` records executable take-profit targets from
`VirtualExecutionReport.take_profit_plan` when available. Legacy virtual trades
without `target_states` must still work by using the final legacy
`take_profit` price as a full-close target.

Lifecycle close reasons extend the legacy set with
`partial_take_profit`, `breakeven_stop`, `trailing_stop`, and `time_stop`.
Partial take-profit events keep the trade open, update remaining/closed
quantities, account proportional entry fees plus exit fees in `realized_pnl`,
and append a lifecycle event. Final closes set legacy `pnl` / `pnl_percent`
from accumulated lifecycle PnL.

Lifecycle state is persisted through the virtual trade metadata snapshot stored
on the entry order. No database migration is required for v1.

## Signal Outcome Labeling v1

`SignalOutcome` records the observed result of every relevant strategy signal,
independent from whether a user confirmed a real or virtual trade. Outcomes are
stored in `signal_outcomes` and are keyed one-to-one by `signal_id` to avoid
duplicate tracking for refreshed signals.

Tracking is created only after a strategy signal is persisted and all of these
conditions hold:

- `score >= settings.signal_outcome_tracking_min_score`;
- entry zone, stop loss, and at least one directional target are valid;
- no outcome exists for the same persisted signal.

`SignalOutcome.status` values:

- `tracking`
- `entry_touched`
- `tp1`
- `tp2`
- `tp3`
- `stop_loss`
- `expired`
- `invalidated`
- `time_stop`

`SignalOutcome.outcome` values:

- `win`
- `loss`
- `breakeven`
- `expired`
- `invalidated`
- `open`

Closed candles update open outcomes by `exchange`, `symbol`, and `timeframe`.
Entry touch is detected when candle high/low intersects the signal entry zone
for both long and short signals. After entry is touched, MFE and MAE are stored
in R units using the persisted entry price and stop distance. `bars_to_entry`
and `bars_to_outcome` count processed closed candles since tracking started.

Target/stop collisions inside the same candle use
`settings.signal_outcome_same_candle_resolution`. The v1 default is
`stop_first`; supported values are `stop_first`, `target_first`, and
`ignore_ambiguous`.

Expiry before entry closes the outcome as `expired` with `realized_r = 0`.
Time stop metadata may be supplied by `trade_plan.metadata`,
`trade_plan.risk_rules.metadata`, or `trade_plan.invalidation.metadata` via
`time_stop`, `time_stop_at`, `expires_at`, `at`, or `max_holding_seconds`.

## Strategy Performance Aggregator v1

`StrategyPerformanceService.aggregate_daily` builds strategy analytics from
closed `SignalOutcome` records and writes daily rows to
`analytics.strategy_performance_daily`.

Daily rows are grouped by:

- `date`
- `exchange`
- `symbol`
- `timeframe`
- `strategy`
- `strategy_version`
- `market_regime`
- `score_bucket`
- `direction`

`score_bucket` values are:

- `0-49`
- `50-59`
- `60-69`
- `70-79`
- `80-89`
- `90-100`

Daily metrics are:

- `sample_size`
- `trades_count`
- `signals_count`
- `wins_count`
- `losses_count`
- `entry_touch_rate`
- `winrate`
- `tp1_rate`
- `tp2_rate`
- `stop_rate`
- `invalidation_rate`
- `avg_win_r`
- `avg_loss_r`
- `expectancy_r`
- `profit_factor`
- `max_drawdown_r`
- `median_bars_to_entry`
- `median_bars_to_outcome`
- `avg_mfe_r`
- `avg_mae_r`
- `fees_bps`
- `slippage_bps`

`StrategyPerformanceService.get_edge_profile` returns a
`StrategyEdgeProfile` for a requested strategy/exchange/symbol/timeframe with
optional market regime and score. Lookup order is:

1. exact `strategy + exchange + symbol + timeframe + market_regime + score_bucket`;
2. fallback `strategy + timeframe + market_regime`;
3. fallback `strategy` global.

The minimum sample threshold is configured by
`settings.strategy_performance_min_sample_size`. Results with data below that
threshold return `confidence = "low"`. No matching data returns
`confidence = "insufficient_sample"`.

## Edge Calibration / EV Gate v1

`StrategySignal` and `RadarSignal` expose optional `edge:
SignalEdgeSnapshot | None` for historical/forward-performance calibration.
The heuristic `score` remains backward-compatible and is not recalculated by
the EV gate.

`SignalEdgeSnapshot` fields:

- `status`: `unknown`, `positive`, `negative`, or `insufficient_sample`
- `sample_size`
- `min_sample_size`
- `winrate`
- `avg_win_r`
- `avg_loss_r`
- `expectancy_r`
- `expectancy_after_costs_r`
- `profit_factor`
- `confidence_score`
- `source`: `outcome`, `backtest`, `mixed`, or `none`
- `score_bucket`
- `metadata`

`EdgeCalibrationService.evaluate_signal_edge(signal)` reads
`StrategyPerformanceService.get_edge_profile()` and calculates:

```python
expectancy_r = winrate * avg_win_r - (1 - winrate) * abs(avg_loss_r)
expectancy_after_costs_r = expectancy_r - estimated_costs_r
```

`estimated_costs_r` is derived from the profile cost bps and the signal
entry/stop distance when available; otherwise it is recorded as `0` with
metadata indicating that R-based cost conversion was unavailable.

`RiskManagementSettings` adds:

- `real_requires_positive_edge: bool = True`
- `edge_min_sample_size: int = 50`
- `min_expectancy_after_costs_r: float = 0.05`

Real execution must be blocked when `real_requires_positive_edge` is enabled
and any of these conditions is true:

- signal edge is missing;
- edge status is not `positive`;
- edge `sample_size` is below `edge_min_sample_size`;
- `expectancy_after_costs_r` is missing or not greater than
  `min_expectancy_after_costs_r`.

Virtual execution does not hard-block on explicit unknown, insufficient, or
weak edge snapshots, but the risk decision warns:
`Edge is insufficient/unknown; virtual-only recommended.`

## Real Execution Adapter v1

Real execution keeps the existing backend risk-gate boundary and safe adapter
layer before any production exchange integration:

```text
RealExecutionService -> RealExecutionReadinessService -> ExchangeExecutionAdapter -> DryRunExecutionAdapter
```

`RealExecutionReadinessService` is the service-layer guard after RiskGate and
execution-plan validation, and before any adapter call. It does not submit
orders and does not replace RiskGate. It blocks live adapter placement unless
all live-readiness requirements pass:

- signal status is `entry_touched`, `actionable`, or `confirmed`, and not
  terminal;
- `SignalDecisionSnapshot.signal_actionable == true` and
  `execution_allowed_real == true`;
- `TradePlanCompletenessService` confirms structural stop, invalidation thesis,
  and structural target, or an explicitly validated runner exit policy;
- fallback stop or fallback-only targets are not used;
- entry, protective stop, and take-profit order specs are built before adapter
  placement;
- every order has stable `client_order_id` and role-scoped
  `idempotency_key`;
- fresh exchange rules, `qty_step`, `tick_size`, and `min_notional` are
  available;
- fresh real account equity and available-balance snapshots are available;
- fresh exchange fee rates are available within `real_fee_rate_ttl_seconds`;
- futures requests have a passed liquidation projection;
- position reconciliation is enabled;
- the live adapter declares protective-order placement guarantees.

`RiskManagementSettings` adds:

- `real_execution_enabled: bool = False`
- `real_fee_rate_ttl_seconds: int = 86400`

`real_execution_enabled=false` blocks non-dry-run live placement. It does not
disable virtual execution and does not prevent `DryRunExecutionAdapter` from
returning an auditable dry-run plan. A non-dry-run adapter must never submit a
naked entry, and duplicate calls with the same order intent must reuse existing
orders by `client_order_id`/`idempotency_key` rather than submitting duplicates.

`ExchangeExecutionAdapter` is an async protocol with these methods:

- `place_order(order)`
- `place_protective_stop(order)`
- `place_take_profit(order)`
- `cancel_order(exchange, symbol, client_order_id)`
- `replace_order(current_client_order_id, replacement)`
- `get_order(exchange, symbol, client_order_id)`
- `get_open_orders(exchange, symbol)`
- `get_position(exchange, symbol)`

The default adapter is `DryRunExecutionAdapter`. It never sends exchange orders.
It returns the planned entry, protective stop, and take-profit orders with
stable `client_order_id` values and idempotency keys.

`RealExecutionResult.status` keeps the existing `not_implemented` and
`risk_failed` values and adds:

- `dry_run`: the risk gate passed, a complete order plan was built, and the
  dry-run adapter returned planned orders;
- `submitted`: reserved for a future real adapter after explicit implementation.

`RealExecutionResult` remains backward compatible and may include:

- `execution_plan`: full real execution plan;
- `planned_orders`: flattened list of planned adapter orders;
- `idempotency_key`: stable key for the same signal/order intent;
- `adapter`: adapter name such as `dry_run`;
- `validation_errors`: execution-plan validation failures when present.

`ExecutionPlannedOrder` records:

- `role`: `entry`, `protective_stop`, or `take_profit`;
- `side`: exchange order side, `buy` or `sell`;
- `order_type`: `market`, `limit`, `stop`, or `take_profit`;
- `quantity`, optional `price`, optional `stop_price`;
- `reduce_only` for protective stop and take-profit orders;
- optional `close_percent`;
- optional exchange state: `exchange_order_id`, `filled_qty`,
  `avg_fill_price`, `remaining_qty`, and `fees`;
- `client_order_id`, `idempotency_key`, `status`, and `metadata`.

Order status values are additive and include `planned`, `new`, `dry_run`,
`submitted`, `partially_filled`, `filled`, `canceled`, `cancelled`,
`rejected`, `expired`, and `unknown`.

Real execution must not place an order when no adapter is configured. In that
case it returns `not_implemented` after the risk decision and execution plan are
available. If exchange rule step sizes are available, quantity must align with
`qty_step` and entry/stop/take-profit prices must align with `tick_size` before
adapter methods are called.

Partial fills must remain explicit. `RealExecutionService` must not assume a
full fill when an adapter returns `partially_filled` or nonzero
`remaining_qty`; the returned `RealExecutionPlan.metadata` records
`reconciliation_required=true` and a reconciliation state snapshot. Cancel and
replace operations are explicit guarded adapter methods, not silent mutation
paths.

## Real Position Reconciliation v1

After a real execution adapter submits orders, exchange order/position state is
the source of truth for local live `Order` and `Position` records.

`RealPositionSyncWorker` periodically uses a configured real sync client to:

- fetch exchange open orders;
- fetch exchange positions;
- look up terminal state for local open live orders by `client_order_id`;
- pass normalized snapshots to `RealTradeImportService.reconcile_connection`.

The sync client must not submit or cancel orders. It only reads exchange state.

`ExchangeOrderSnapshot` is the normalized order contract consumed by
reconciliation:

- `exchange`, `symbol`
- `exchange_order_id | None`
- `client_order_id | None`
- `side`: `buy` or `sell`
- `order_type | None`: `market`, `limit`, `stop`, or `take_profit`
- `status`: normalized exchange status such as `submitted`,
  `partially_filled`, `filled`, `cancelled`, or `rejected`
- `quantity | None`
- `filled_quantity | None`
- `price | None`, `stop_price | None`, `avg_price | None`
- `reduce_only`
- optional `role`: `entry`, `protective_stop`, or `take_profit`
- optional `signal_id`, `position_id`
- optional `updated_at`
- `raw`

`ExchangePositionSnapshot` is the normalized position contract:

- `exchange`, `symbol`
- `side`: `long` or `short`
- `quantity`
- `entry_avg_price`
- optional `signal_id`, `position_id`, `exchange_position_id`
- optional `mark_price`, `unrealized_pnl`, `updated_at`
- `raw`

Idempotency is based on available identity fields in this order:

- `client_order_id`
- `exchange_order_id`
- `signal_id`
- `position_id`

Reconciliation behavior:

- partial entry fills update local order status and local live position
  quantity/entry price to the exchange-reported actual position;
- cancelled or rejected entry orders close any unmatched local live position so
  it no longer contributes to real open risk;
- filled reduce-only stop/TP orders close the matched local live position when
  the exchange no longer reports an open position;
- exchange position size mismatches update local live position quantity;
- local live positions missing from exchange positions are closed and audited;
- unmatched exchange positions are audited as manual/external positions and are
  not silently inserted as local strategy positions.

`external_exchange_orders` remains idempotent by
`connection_id + exchange_order_id`; client order ids, reduce-only flags,
filled quantities, and local identity fields are stored in order metadata for
backward compatibility.

Real risk state continues to read open live risk from local `positions`, but
after reconciliation those positions reflect actual exchange positions rather
than only local execution intent.

## L2 Orderbook Market Quality v1

`OrderbookSnapshotWorker` refreshes configured/watchlist Bybit symbols and
writes normalized hot L2 snapshots to Redis key
`orderbook:{exchange}:{symbol}`.

`OrderBookSnapshot` fields:

- `exchange`, `symbol`, `category`
- `bids`, `asks`: normalized levels with `price` and `quantity`
- `timestamp`: source/fetch timestamp in milliseconds
- `ts`: ISO-8601 UTC timestamp for compatibility with existing hot payloads
- `source`: `bybit_v5_orderbook` for real L2 snapshots
- `spread_bps`
- `bid_depth_usd_0_1_pct`, `ask_depth_usd_0_1_pct`
- `bid_depth_usd_0_5_pct`, `ask_depth_usd_0_5_pct`
- `bid_depth_usd_1_pct`, `ask_depth_usd_1_pct`

Depth bands are measured from the best bid/ask. Bids include levels at or
above `best_bid * (1 - band)`; asks include levels at or below
`best_ask * (1 + band)`.

`RiskMarketDataService` reads the Redis L2 snapshot for Bybit market context.
It exposes `spread_bps`, entry-side `orderbook_depth_usd` from the 0.5% band,
and `market_data_status`:

- `fresh`: a non-placeholder L2 snapshot is present and within the configured
  orderbook snapshot max age
- `stale`: a real L2 snapshot exists but is older than the configured max age
- `missing`: no usable L2 snapshot exists, including legacy
  `orderbook_l2_not_available` placeholder payloads

`RiskManagementSettings` adds:

- `real_requires_fresh_market_data: bool = True`

When `real_requires_fresh_market_data` is enabled, real entries are blocked for
`missing` or `stale` market data. Virtual entries warn instead. If disabled,
real entries also warn, while other risk checks still apply.

## No-Trade Filters v1

`StrategySignal` and `RadarSignal` expose optional
`no_trade_filter: NoTradeFilterResult | None`. The no-trade layer is evaluated
after strategy setup, market quality, regime, confirmation, and RR checks. It
does not change strategy formulas; it converts hard entry blockers into an
explicit signal layer.

`NoTradeFilterResult` fields:

- `enabled`
- `blocked`
- `hard_block`
- `blockers`
- `warnings`
- `checks: list[SignalLayerCheck]`
- `metadata`

The no-trade check names are:

- `near_htf_obstacle`
- `low_liquidity`
- `high_spread`
- `high_slippage`
- `overextended_entry`
- `extreme_funding`
- `strategy_cooldown`
- `daily_loss_streak`
- `negative_edge`
- `missing_market_data`

Hard no-trade results must be visible in `signal.risks`, persisted in
`features_snapshot.no_trade_filter`, and surfaced as a `no_trade_filter`
confirmation check. A hard no-trade result makes the signal non-actionable,
sets disabled `auto_entry` metadata, and prevents lifecycle promotion to
`actionable`.

`RiskContext` carries `no_trade_filter`. RiskGate blocks real and virtual
trade confirmation when `no_trade_filter.blocked` is true. Research-only
warning behavior is not introduced in v1.

No-trade settings are configurable through strategy runtime/risk settings:

- `no_trade_filters_enabled`
- `max_spread_bps_for_entry`
- `max_slippage_bps_for_entry`
- `min_depth_usd_for_entry`
- `max_obstacle_distance_r`
- `cooldown_after_stop_minutes`
- `max_strategy_losses_per_day`

Existing related settings remain honored where applicable:
`real_requires_fresh_market_data`, `real_requires_positive_edge`,
`edge_min_sample_size`, `min_expectancy_after_costs_r`, and strategy funding
thresholds such as `funding_block_threshold`.

---

# Rules

## run_strategies
- pure function
- no DB
- no external APIs

## calculate_features
- must use only market data
- no external calls

## execution
- must use config
- no hardcoded values

## RiskManagementSettings
- `strategy_risk_multipliers` must include current strategy keys:
  `trend_pullback_continuation`, `volatility_squeeze_breakout`,
  `liquidity_sweep_reversal`.
- Legacy strategy aliases remain supported:
  `trend_following`, `breakout`, `smart_money_setup`.
- Strategy multiplier lookup uses exact normalized strategy key first,
  then legacy alias fallback, then `1.0`.

## Strategy RR eligibility
- RR is calculated for discovery, research, virtual confirmation, backtests,
  and real execution. By default, low RR is an execution quality/risk warning
  and metadata signal, not proof that the market setup is invalid.
- Signal discovery, `signal_actionable`, and execution eligibility are
  separate. A failed RR check may leave `signal_valid = true` and the setup
  visible as a research/watchlist/blocked candidate. In `soft` or `off` mode,
  `signal_actionable` may remain true for the current non-real scope when other
  checks allow it. `execution_allowed_virtual` and `execution_allowed_real` may
  be false only in the eligibility/execution layer when the active guard mode
  or other hard gate blocks that scope.
- `min_rr_ratio` remains part of API/settings/storage for backward
  compatibility. Its contract meaning is "minimum R:R for execution/reporting",
  not a universal signal discovery filter.

RR guard modes:

- `off`: calculate and persist RR only; do not warn or block.
- `soft`: warning plus metadata; default for discovery, virtual confirmation,
  backtests, and research.
- `hard`: block execution eligibility according to mode.

RR guard mode precedence:

1. Per-strategy `risk_settings.rr_guard_mode`.
2. User risk setting `strategy_rr_guard_modes[strategy_code]`.
3. Context-specific setting:
   `discovery_rr_guard_mode`, `virtual_rr_guard_mode`,
   `backtest_rr_guard_mode`, or `real_rr_guard_mode`.
4. Generic `rr_guard_mode`.
5. Safe default: `soft` for discovery/virtual/backtest/research, `hard` for
   real execution.

Context-specific defaults:

- `discovery_rr_guard_mode = "soft"`
- `virtual_rr_guard_mode = "soft"`
- `backtest_rr_guard_mode = "soft"`
- `real_rr_guard_mode = "hard"` by default, configurable to `"soft"` or
  `"off"`.

`risk_reward_guard` pipeline/layer check semantics:

- `hard` mode plus failed RR => failed check, `risk_reward_blocked = true`,
  `risk_reward_block_reason`, and decision blocker code `blocked_by_rr`.
  This blocks execution and auto-entry eligibility, not discovery visibility.
- `soft` mode plus failed RR => warning check, `risk_reward_warning = true`,
  and `risk_reward_warning_reason`; signal discovery/research/virtual/backtest
  status is not blocked by RR alone.
- `off` mode plus failed RR => skipped/info check; RR values and metadata are
  still calculated and persisted.

RR metadata snapshots expose:

- `selected_rr`
- `rr_value`
- `rr_status`
- `min_rr_ratio`
- `risk_reward_guard_mode`
- `signal_actionable`
- `auto_entry_allowed`
- `execution_allowed_virtual`
- `execution_allowed_real`
- `blockers`
- `warnings`
- `risk_reward_warning`
- `risk_reward_warning_reason`
- `risk_reward_blocked`
- `risk_reward_block_reason`

Failed RR signals disable `auto_entry` metadata only when the active guard mode
is `hard` and the execution layer/risk gate blocks eligibility. No-trade hard
blockers remain hard blockers independent of RR mode.
