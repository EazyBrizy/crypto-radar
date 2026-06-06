# Crypto Radar Execution Pipeline Hardening Design

## Goal

Separate market ideas, watchlist entries, and execution signals so the execution feed and notifications contain only signals that can actually be acted on. Open candles, weak edge, no-trade blocks, poor risk/reward, duplicate same-direction opportunities, and unfilled pending entries must become visible blockers or outcomes instead of looking like trade signals.

## Current State

The codebase already contains several pieces of the desired model:

- `backend/app/services/market_scanner.py` builds features from candles and calls the strategy engine. It currently reads candle series with `include_open=True`.
- `backend/app/strategies/engine.py` runs strategies, finalizes signals through `StrategySignalPipeline`, attaches edge through `edge_calibration_service.evaluate_signal_edge`, and recalculates `execution_gate`.
- `backend/app/strategies/pipeline.py` owns market quality, regime, setup, confirmation, risk/reward, no-trade, completeness, decision, and execution gate snapshots.
- `backend/app/services/signal_status_resolver.py` already downgrades many non-actionable states and partly handles open candles as `forming_candle`.
- `backend/app/services/signal_execution_gate.py` already classifies feed kind and execution permissions, but some thresholds and policies are hardcoded or incomplete.
- `backend/app/workers/signal_worker.py` persists scanner signals, publishes realtime signal events, and creates notifications.
- `backend/app/services/radar_service.py` filters visible radar feeds using `execution_gate.can_show_in_execution_feed` when present, then performs a read-side execution dedupe by score.
- `backend/app/services/pending_entry.py` creates pending entry intents. `backend/app/services/pending_entry_trigger.py` processes tick-driven virtual pending entries. `backend/app/services/signal_outcome_service.py` already records terminal pending entries as outcomes in some cases.
- Frontend components already render `execution_gate`, action state, pending-entry reason codes, and `candle_state`, but need clearer forming-candle, trigger, edge, eligibility, and dedup messages.

The remaining problem is consistency: several services already know pieces of the truth, but the execution contract is not enforced as a single source of truth before persistence, realtime publication, notification, and UI actions.

## Selected Approach

Use staged hardening rather than a large pipeline rewrite.

1. Make `SignalExecutionGateSnapshot` the backend source of truth for execution feed inclusion, notifications, and entry/pending action availability.
2. Add global signal deduplication before realtime publish and notification, while preserving suppressed market ideas/history for analytics.
3. Add a trigger snapshot so strategy setup is distinct from closed-candle trigger confirmation.
4. Tie edge, outcome, pending-entry no-entry rates, and optional walk-forward eligibility into execution gating.
5. Surface every blocker and terminal pending-entry reason through API and UI.

This preserves existing API compatibility, keeps live trading disabled by default, and lets strict behavior be controlled by settings where the spec asks for safe rollout defaults.

## Alternatives Considered

### Full Pipeline Rewrite

Rewrite `StrategySignalPipeline` around a new set of explicit layers in one pass. This would create a conceptually cleaner pipeline but has high regression risk because the current services already encode risk, no-trade, trade-plan completeness, edge, and UI contracts.

### Shadow Mode Only

Calculate all new gates and reasons but leave feed/notification behavior mostly unchanged until a later flag flip. This lowers rollout risk but does not solve the immediate user problem: non-executable ideas still look like trade signals.

### Staged Hardening

Build on the existing service boundaries, enforce the execution contract in the gate and worker, and add missing domain snapshots. This is the recommended path because it moves the product to the requested behavior while keeping each change testable.

## Architecture

### Settings

Add the requested runtime flags to `backend/app/core/config.py`.

Execution feed defaults:

- `scanner_open_candle_previews_enabled: bool = True`
- `execution_closed_candle_only: bool = True`
- `execution_min_score: int = 70`
- `execution_dedup_window_seconds: int = 300`
- `notification_dedup_window_seconds: int = 300`

Edge and eligibility defaults:

- `execution_edge_gate_enabled: bool = True`
- `execution_edge_min_sample_size: int = 50`
- `execution_edge_min_expectancy_after_costs_r: float = 0.05`
- `execution_edge_min_profit_factor: float = 1.15`
- `execution_edge_allow_insufficient_sample_in_learning_mode: bool = False`
- `execution_edge_learning_mode: bool = False`
- `execution_edge_min_entry_touch_rate: float = 0.25`
- `execution_edge_max_no_entry_rate: float = 0.60`
- `execution_require_walk_forward_edge: bool = False`
- `execution_min_validation_sample_size: int = 30`
- `execution_min_validation_expectancy_r: float = 0.05`
- `execution_min_validation_profit_factor: float = 1.15`
- `execution_max_validation_drawdown_r: float = 10.0`
- `execution_min_entry_touch_rate: float = 0.25`
- `execution_max_no_entry_rate: float = 0.60`

These flags are used by services, not frontend logic. The frontend continues to render backend decisions.

### Signal Lifecycle Contract

The scanner may create market ideas from open candles only when `scanner_open_candle_previews_enabled` is true. Those signals must carry `candle_state="open"` and an execution gate with:

- `feed_kind` equal to `watchlist` or `blocked`
- `can_notify=false`
- `can_enter_now=false`
- `can_arm_pending=false`
- `can_show_in_execution_feed=false`
- reason code `forming_candle`

If `scanner_open_candle_previews_enabled` is false, open candles must not generate `StrategySignal` objects at all.

Closed candles keep the existing lifecycle, but execution-ready status is valid only when the execution gate passes.

### Execution Gate

`backend/app/services/signal_execution_gate.py` becomes the canonical execution classifier.

Execution-ready requires all of:

- status is an execution candidate (`actionable`, `entry_touched`, or `confirmed`)
- score is at least `settings.execution_min_score`
- `candle_state == "closed"` when `settings.execution_closed_candle_only` is true
- trigger exists and `trigger.passed == true`
- no hard no-trade blocker
- risk/reward and trade-plan completeness permit execution
- decision snapshot permits virtual execution
- edge gate passes when enabled
- strategy eligibility passes when strict walk-forward edge is required

The service must produce stable reason codes for all blocks:

- `forming_candle`
- `trigger_not_confirmed`
- `score_below_execution_threshold`
- `no_trade_hard_block`
- `rr_failed`
- `trade_plan_incomplete`
- `edge_missing`
- `edge_unknown`
- `edge_insufficient_sample`
- `edge_negative`
- `edge_expectancy_below_threshold`
- `edge_profit_factor_below_threshold`
- `edge_entry_touch_rate_below_threshold`
- `edge_no_entry_rate_above_threshold`
- `strategy_eligibility_missing`
- `strategy_eligibility_failed`

Only `feed_kind="execution_signal"` with `can_show_in_execution_feed=true` can drive notification, execution feed inclusion, or enabled entry/pending buttons.

### Trigger Snapshot

Add `SignalTriggerSnapshot` to `backend/app/schemas/signal.py` and attach it to `StrategySignal` and `RadarSignal`.

Fields:

- `trigger_type`: one of `closed_candle`, `reclaim`, `breakdown`, `pullback_touch`, `liquidity_reclaim`, `breakout_retest`, `none`
- `passed: bool`
- `price: float | None`
- `candle_state: CandleState`
- `confirmed_at: datetime | None`
- `checks: list[SignalLayerCheck]`
- `metadata: dict`

`StrategySignalPipeline` builds this after confirmation and before status resolution.

Strategy behavior:

- `trend_pullback_continuation`: trigger requires closed-candle reclaim or hold of the pullback zone plus higher-timeframe alignment when required.
- `volatility_squeeze_breakout`: trigger requires closed candle outside breakout level or a retest close after an oversized impulse candle.
- `liquidity_sweep_reversal`: trigger requires closed-candle reclaim or rejection of the swept level, not merely a sweep.

If `trigger.passed` is false, status cannot be `actionable`. The resolver should return `watchlist`, `ready`, or `wait_for_pullback` depending on setup state and reason.

### Strategy Pipeline Shape

`backend/app/strategies/pipeline.py` should document and enforce these conceptual layers:

1. `MarketQualityFilter`
2. `MarketRegimeFilter`
3. `StrategySetupLayer`
4. `ConfirmationLayer`
5. `TriggerLayer`
6. `NoTradeFilter`
7. `RiskRewardAssessment`
8. `TradePlanCompleteness`
9. `EdgeGate`
10. `SignalExecutionGate`

The implementation does not need a full rewrite in one task. It does need clear comments/docstrings and checks/reasons showing where setup becomes confirmed trigger and where blockers are applied.

Market regime metadata must support:

- `trend_up`
- `trend_down`
- `range`
- `chop`
- `volatility_expansion`
- `volatility_compression`
- `unknown`

Strategy compatibility rules:

- Trend pullback is compatible with `trend_up` for long and `trend_down` for short. It is blocked or left as watchlist in chop/range unless explicitly allowed.
- Liquidity sweep reversal prefers range boundaries or liquidity pools. It is blocked against strong trend without reclaim and absorption evidence.
- Volatility squeeze breakout requires compression first. If expansion has already happened with a large candle, it waits for retest.

Score remains explanatory and useful for rank/dedup. Score never overrides trigger, edge, no-trade, risk, or trade-plan blockers.

### Global Deduplication

Add `backend/app/services/signal_deduplication.py`.

Public types:

- `DedupDecision`
- `SignalDeduplicationService`

`DedupDecision` fields:

- `action`: `keep`, `suppress`, or `replace`
- `reason: str`
- `suppressed_by_signal_id: str | None`
- `metadata: dict`

Dedup key:

- `exchange.lower()`
- normalized symbol
- `direction.lower()`

Ranking compares, in order:

1. `execution_gate.can_show_in_execution_feed == true`
2. `feed_kind`: `execution_signal` > `watchlist` > `market_idea` > `blocked`
3. status priority: `entry_touched` > `actionable` > `confirmed` > `wait_for_pullback` > `ready` > `watchlist` > `active` > `new` > terminal statuses
4. closed candle above open candle
5. higher score
6. positive edge above unknown/insufficient/negative
7. higher selected R:R
8. timeframe priority `15m > 5m > 1h > 4h > 1m > 1d` when scores are close

The worker applies dedup after `upsert_strategy_signal` and before realtime publish or notification.

Repository support:

- Add `SignalRepository.list_open_signals_for_market_direction(exchange, symbol, direction, since)`.
- Implement the Postgres query in `PostgresSignalRepository`.

Persistence:

- Store dedup metadata under `features_snapshot.dedup`.
- A suppressed new signal is marked blocked/suppressed in snapshot and must not notify.
- A replaced older signal transitions to `invalidated` or `rejected` with reason `dedup_replaced_by_better_signal`.

Read-side radar dedupe may remain as a defensive layer, but write-side dedupe is the source of truth for notifications and stored active signals.

### Notifications

Notifications are created only for true execution signals.

`signal_worker._should_notify_signal` must require:

- `signal.execution_gate is not None`
- `signal.execution_gate.can_notify == true`
- `signal.execution_gate.can_show_in_execution_feed == true`
- `signal.execution_gate.feed_kind == "execution_signal"`

Fallback for legacy signals without a gate remains strict and should require execution-candidate status, closed candle, and score at least `settings.execution_min_score`.

Notification type:

- Prefer `signal.execution_ready`.
- Legacy `signal.created` remains accepted for compatibility.

Notification content:

- title: `Execution signal`
- payload includes `signal_id`, `feed_kind`, `execution_gate.status`, `execution_gate.reasons`, `edge`, `selected_rr`, and `status_reason`.

Dedup:

- Suppress duplicate notifications for same user, exchange, normalized symbol, direction, and execution-signal kind within `settings.notification_dedup_window_seconds`.
- Postgres lookup over notification payload is sufficient. Redis can remain optional.

Realtime:

- `signal_created_event` may still publish market ideas so watchlist UI can update.
- `notification_created_event` is execution-only.

### Edge Gate And Walk-Forward Eligibility

`StrategyEngine.generate_signals` already calls `edge_calibration_service.evaluate_signal_edge(finalized)` after `pipeline.finalize()` and recalculates `execution_gate`. Keep this shape so the pipeline stays synchronous.

Enhance `SignalExecutionGateService` to use settings-driven thresholds:

- Negative edge blocks.
- Unknown or insufficient sample blocks when learning mode is false.
- Learning mode keeps unknown/insufficient ideas as watchlist/market ideas with no notification and no execution.
- Low expectancy after costs blocks.
- Low profit factor blocks or warns according to configured policy. Initial design treats it as blocker because the spec asks for execution feed quality.
- Low entry touch rate and high no-entry rate block when available.

Add `backend/app/services/execution_strategy_registry.py`.

`ExecutionStrategyEligibilityService.get_eligibility(strategy, timeframe, regime, score_bucket)` returns:

- `eligible: bool`
- `reason: str`
- `metrics: dict`
- `source`: `walk_forward`, `outcome`, or `none`

When `settings.execution_require_walk_forward_edge` is false, eligibility is informative and shown in UI. When true, failed eligibility blocks execution.

Add `scripts/calibrate_execution_gate.py` to connect existing backtest/strategy-testing infrastructure with eligibility metrics. The script accepts the spec's CLI parameters, separates train and validation windows, groups by strategy/timeframe/regime/score bucket/direction, computes requested metrics, and stores results in the existing performance store when possible.

### Pending Entry Diagnostics And Outcomes

`PendingEntryTriggerResult` must always include:

- `reason_code: str | None`
- `gate_snapshot: dict | None`
- `current_price: Decimal | None`
- `entry_zone_distance_bps: Decimal | None`

Known reason codes:

- `not_touched`
- `touched`
- `expired_before_touch`
- `signal_missing`
- `signal_terminal`
- `requires_reconfirmation`
- `material_trade_plan_change`
- `virtual_execution_rejected`
- `riskgate_temporary_failure`
- `riskgate_structural_failure`
- `filled`
- `real_execution_not_enabled`

`PendingEntryIntentRead.view.reason_code` must always be populated for known states. User-facing fallback text like "backend reason missing" must not appear for known terminal or pending statuses.

`pending_entry_service.transition_status` stores `failure_reason` and `reason_code` in `request_snapshot` first. A dedicated nullable column can be added later if the model migration is required by query needs; the initial compatible path is snapshot storage plus schema/view mapping.

Terminal pending entries update signal outcomes:

- expired or cancelled before touch becomes `no_entry`.
- virtual execution rejected becomes `execution_rejected` or `no_entry` with reason metadata.
- temporary risk-gate failure does not close the outcome unless the intent becomes terminal.

Performance metrics must count:

- pending armed count
- filled count
- entry touch rate
- fill rate
- no-entry rate
- execution rejected rate

Edge gate may block strategies with high no-entry rate or low entry touch rate.

### Frontend

Frontend remains display-only.

Signal details:

- If `signal.candle_state == "open"`, show badge `forming candle / preview`.
- Show text: `Свеча ещё формируется. Это наблюдение, не сигнал для исполнения.`
- Entry and pending buttons remain disabled through backend action state and execution gate.
- Show `Trigger` block: confirmed/waiting, trigger type, and reason.
- Show `Strategy eligibility`: source, sample size, validation expectancy, profit factor, and no-entry rate when present.
- Show dedup reason in details/history for suppressed duplicate signals.
- Show latest terminal pending-entry outcome in details.

Notification runtime/center:

- `signal.execution_ready` displays as `Сигнал готов к исполнению`.
- Legacy `signal.created` displays as `Новая идея` unless payload feed kind is `execution_signal`.
- Score below execution threshold must not appear as a trading notification.

Pending entries:

- Queue item shows status, reason code, user-facing reason, current price, entry zone, last checked time, and exact failure reason.
- Expired states distinguish expired before touch from expired after reconfirmation requirement.

### Documentation

Update current docs after implementation:

- `docs/BACKEND.md`: describe execution pipeline, gate, dedup, notifications, pending-entry outcomes.
- `docs/FRONTEND.md`: describe rendering-only responsibility for execution blockers and pending-entry reasons.
- Add `docs/STRATEGIES.md`: existing strategies, regimes, setup, trigger, execution rules, edge usage.
- Add `docs/WORKERS.md`: worker list, purpose, lifecycle, side effects, and safety notes.
- Update `docs/PROJECT_STRUCTURE.md` if new files are added.

### Tests

Backend tests:

- Extend forming-candle status/gate tests.
- `test_signal_worker_does_not_notify_open_candle`
- `test_signal_deduplication.py` for keep, suppress, replace, opposite direction, different symbol, and open-vs-closed ranking.
- Repository test for `list_open_signals_for_market_direction`.
- Worker test for no duplicate notifications.
- Trigger tests for liquidity sweep reclaim, breakout retest, trend pullback HTF alignment, and score without trigger.
- Edge gate tests for unknown, insufficient, negative, expectancy, profit factor, entry touch rate, and no-entry rate.
- Eligibility tests for no data, positive walk-forward, negative validation, and gate integration.
- Pending-entry reason/outcome tests for expired, cancelled, virtual rejection, temporary risk failure, and no-entry metrics.
- Notification tests for execution-gate passed only, low score, watchlist, forming candle, and dedup.
- Integration scenarios from the pasted spec.

Frontend tests:

- `SignalDetails.test.tsx` for forming candle blocker, trigger block, disabled buttons, eligibility block, pending terminal reason.
- `SignalCard.test.tsx` for feed kind and forming-candle/blocked badges.
- `RadarPage.test.tsx` for pending-entry queue reason display.
- `NotificationRuntime.test.tsx` and notification center tests for execution-ready vs legacy idea wording.
- `signal-status.test.ts` for gate-source-of-truth helpers.

Required verification commands after implementation:

- `python -m pytest backend/tests/test_signal_status_contract.py`
- `python -m pytest backend/tests/test_strategy_signal_pipeline.py`
- `python -m pytest backend/tests/test_radar_service.py`
- `python -m pytest backend/tests/test_pending_entry_trigger_service.py`
- `python -m pytest backend/tests/test_signal_outcome_service.py`
- `python -m pytest backend/tests/test_notification_service_contract.py`
- `python -m pytest backend/tests/test_trading_e2e_virtual_flow.py`
- `cd frontend && corepack pnpm typecheck`
- `cd frontend && corepack pnpm test -- SignalCard SignalDetails RadarPage NotificationRuntime signal-status`

If test names differ, use the closest existing test files and add new focused tests beside them.

## Rollout And Compatibility

- Real trading stays disabled by default.
- Existing API fields remain; new fields are optional for compatibility.
- Legacy notification type is still readable.
- Market ideas are preserved for analytics and learning, but they do not look like execution signals.
- Strict walk-forward eligibility is initially disabled by `execution_require_walk_forward_edge=false`; the evidence is still rendered and can be enabled later.

## Risks

- Existing tests may encode older semantics where `ready` or high score implied tradability. Those tests should be updated only when they conflict with the new explicit contract.
- Some backtest/strategy-testing services may not expose every requested walk-forward metric yet. The implementation should add missing fields in the nearest existing performance schema rather than introduce a disconnected store.
- Notification dedup through JSON payload queries can be slower than a dedicated index. It is acceptable for initial correctness; if volume grows, add an indexed dedup key.
- Trigger inference may initially rely on existing confirmation metadata. Keep the public snapshot explicit even if the first implementation maps from current checks.

## Completion Evidence

This design is complete only when implementation evidence proves:

- Open candles never notify or appear in execution-ready.
- Execution feed has no non-executable ideas.
- Same exchange, symbol, and direction cannot produce multiple active execution notifications within the dedup window.
- Actionable/execution requires a confirmed trigger.
- Edge and eligibility blockers are visible and enforced according to settings.
- Pending entries that never execute are recorded as outcomes and counted in performance.
- UI displays blocker and reason-code state without inventing trading calculations.
- Backend and frontend verification commands pass, or any skipped commands are explicitly explained with the closest tests that did run.
