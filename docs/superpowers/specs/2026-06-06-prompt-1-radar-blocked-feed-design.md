# Prompt 0 And Prompt 1 Design

## Goal

Implement the first roadmap slice for `crypto-radar`: complete the required pre-change audit and fix the radar feed/UI so low-score blocked diagnostic ideas do not look like executable trading signals in the normal working feed.

## Prompt 0 Audit

1. `StrategySignal` is created by strategy modules through `backend/app/strategies/common.py::build_strategy_signal`; the shared schema lives in `backend/app/schemas/signal.py::StrategySignal`. The pipeline finalizes candidates in `backend/app/strategies/pipeline.py::StrategySignalPipeline`.
2. Signal status is resolved in `backend/app/services/signal_status_resolver.py` and applied inside `StrategySignalPipeline.finalize()` before the signal is converted to `RadarSignal`.
3. `execution_gate` is calculated in `backend/app/services/signal_execution_gate.py::SignalExecutionGateService.evaluate()` and attached by `StrategySignalPipeline._attach_execution_gate()`.
4. Signals enter the radar feed through `backend/app/services/signal_service.py` persistence/read APIs and are assembled for users by `backend/app/services/radar_service.py::RadarService.list_signals()`.
5. Enter/pending availability is backend-owned by `backend/app/services/signal_actions.py` and `backend/app/services/signal_risk_reward.py`, then displayed by `frontend/src/components/SignalDetails.tsx` and the backend-generated views from `backend/app/services/signal_views.py`.
6. Strategy test runs are created by `backend/app/api/v1/strategy_tests.py` through `backend/app/services/strategy_testing/service.py`, with durable run state in `backend/app/services/strategy_testing/stores.py::PostgresStrategyTestRunStore`.
7. Backtests open simulated virtual trades in `backend/app/services/backtest_runner.py::_try_open_position()`, update/close them through `apply_virtual_trade_candle()` and `close_virtual_trade_lifecycle()`, and convert closed positions into `BacktestSimulatedTrade` rows.
8. Current storage involved: Postgres `trading_signals`, `trading_signal_events`, `signal_outcomes`, `pending_entry_intents`, `strategy_test_runs`, virtual trading tables, outbox/audit tables; ClickHouse market candle/tick tables plus `analytics.signal_events`, `analytics.virtual_trade_events`, `analytics.strategy_test_trades`, `analytics.strategy_test_metrics`, and `analytics.backtest_results`.

## Prompt 1 Design

### Backend

`RadarService.list_signals()` will keep blocked ideas in the backend result source, but hide them from `all_market_opportunities` by default. The all feed will only display observation-worthy feed kinds: `market_idea`, `watchlist`, and `execution_signal`. It will also hide signals below `settings.radar_all_feed_min_visible_score` and count hidden blocked/low-score ideas for diagnostics.

`mode="blocked"` remains a diagnostic mode. It will show `feed_kind="blocked"` signals when `settings.radar_debug_blocked_feed_enabled` is true, and it will keep the existing behavior that can include execution candidates denied by the read-only risk preview.

`RadarSummary` will gain optional/default counters:

- `visible_market_ideas`
- `hidden_blocked_ideas`
- `hidden_low_score_ideas`
- `diagnostic_blocked_ideas`

These counters will be produced from the unfiltered source set plus visible set so the UI can explain why the working feed is cleaner without deleting diagnostic ideas.

### Frontend

`RadarPage` will rename the default feed filter from "All ideas" to "Working feed" and make the blocked tab visibly diagnostic. When the blocked tab is selected, it will render a warning: "These are diagnostic ideas, they are not entry signals."

`SignalCard` will render `feed_kind="blocked"` cards as diagnostic cards:

- Heading/status text: "Blocked idea" for low-score blocked ideas.
- Primary blocker is shown first.
- Trading-style entry/TP grid is suppressed for blocked cards.
- The card displays "Not for execution".
- Low scores use "Idea score" and "low score" instead of confidence-led trading language.

`SignalDetails` will surface a reason beside disabled pending-entry actions by using backend action state or the first `execution_gate` blocker. It will not show a disabled pending-entry button without an explanatory caption.

### Tests

Backend tests will be added to `backend/tests/test_radar_service.py`:

- `test_radar_service_all_feed_hides_blocked_low_score`
- `test_radar_service_blocked_mode_shows_blocked_diagnostics`
- `test_radar_summary_counts_hidden_blocked`

Frontend tests will be added to existing test files:

- `frontend/src/components/SignalCard.test.tsx`: blocked low-score cards render "Not for execution".
- `frontend/src/features/app-shell/RadarPage.test.tsx`: blocked filter shows the diagnostic warning.
- `frontend/src/domain/signal-status.test.ts`: feed kind helpers remain backend-gate driven.

### Acceptance

The normal radar working feed no longer shows low-score blocked NEAR/CLOUD/WIF-style cards as executable signals. Those cards remain available in the diagnostic blocked filter, while `execution_ready` stays zero when the backend gate has no execution-approved signals.
