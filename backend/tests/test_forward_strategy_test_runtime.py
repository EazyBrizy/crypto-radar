from __future__ import annotations

import asyncio
import contextlib
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Literal, Sequence
from unittest.mock import patch
from uuid import UUID, uuid4

from app.schemas.market import MarketData
from app.schemas.signal import RadarSignal, SignalExecutionGateSnapshot, StrategySignal
from app.schemas.trade import ManualConfirmRequest, VirtualTrade
from app.services.strategy_testing.forward_runtime import ForwardRuntimeResult, ForwardStrategyTestRuntime
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestPair,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestSignalEvent,
    StrategyTestTrade,
)
from app.workers.forward_strategy_test_worker import ForwardStrategyTestWorker


RUN_ID = UUID("11111111-2222-4333-8444-555555555555")
USER_ID = "forward_user"
NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)


class ForwardStrategyTestRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def test_start_run_initializes_isolated_forward_account_state(self) -> None:
        request = _run_request()
        run_store = _ForwardRunStore([_run()])
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            virtual_trading=_VirtualTrading(),
        )

        detail = runtime.start_run(RUN_ID, request)

        account = detail.run.runtime_state["forward_account"]
        self.assertEqual(account["initial_capital"], "1000")
        self.assertEqual(account["balance"], "1000")
        self.assertEqual(account["equity"], "1000")
        self.assertEqual(account["realized_pnl"], "0")
        self.assertEqual(account["unrealized_pnl"], "0")
        self.assertEqual(account["fees"], "0")
        self.assertEqual(account["slippage"], "0")
        self.assertEqual(account["open_positions"], 0)
        self.assertEqual(account["closed_positions"], 0)

    async def test_default_runtime_uses_isolated_forward_writers_only(self) -> None:
        run_store = _ForwardRunStore([_run()])
        trade_store = _RecordingTradeStore()
        radar_writer = _SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True)))

        with (
            patch("app.services.strategy_testing.forward_runtime.signal_service", radar_writer, create=True),
            patch(
                "app.services.strategy_testing.forward_runtime.virtual_trading_service",
                _ForbiddenVirtualTrading(),
                create=True,
            ),
        ):
            runtime = ForwardStrategyTestRuntime(run_store=run_store, trade_store=trade_store)

        result = await runtime.process_strategy_signal(_strategy_signal(execution_gate=_gate(can_enter_now=True)))

        self.assertEqual(result.errors, [])
        self.assertEqual(result.signals_processed, 1)
        self.assertEqual(result.opened_trades, 1)
        self.assertEqual(len(radar_writer.calls), 0)
        self.assertEqual(len(trade_store.signal_events), 1)
        self.assertEqual(trade_store.signal_events[0].test_type, "forward_virtual")
        self.assertEqual(trade_store.signal_events[0].filled, True)
        self.assertEqual(trade_store.signal_events[0].signal_id, trade_store.trades[0].trade_id.replace("forward_trade_", "forward_sig_"))
        runtime_state = run_store.get_run(RUN_ID).run.runtime_state  # type: ignore[union-attr]
        self.assertEqual(runtime_state["signal_events_written"], 1)
        self.assertEqual(runtime_state["forward_account"]["open_positions"], 1)
        self.assertEqual(runtime_state["forward_account"]["closed_positions"], 0)

    async def test_default_forward_entry_price_uses_long_entry_zone_midpoint(self) -> None:
        run_store = _ForwardRunStore([_run()])
        trade_store = _RecordingTradeStore()
        runtime = ForwardStrategyTestRuntime(run_store=run_store, trade_store=trade_store)

        result = await runtime.process_strategy_signal(
            _strategy_signal(
                direction="LONG",
                entry_min=100.0,
                entry_max=101.0,
                stop_loss=95.0,
                take_profit_1=110.0,
                take_profit_2=115.0,
                execution_gate=_gate(can_enter_now=True),
            )
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.opened_trades, 1)
        self.assertEqual(trade_store.trades[0].entry_price, Decimal("100.5"))
        self.assertNotEqual(trade_store.trades[0].entry_price, Decimal("100"))

    async def test_default_forward_entry_price_uses_short_entry_zone_midpoint(self) -> None:
        run_store = _ForwardRunStore([_run()])
        trade_store = _RecordingTradeStore()
        runtime = ForwardStrategyTestRuntime(run_store=run_store, trade_store=trade_store)

        result = await runtime.process_strategy_signal(
            _strategy_signal(
                direction="SHORT",
                entry_min=99.0,
                entry_max=100.0,
                stop_loss=105.0,
                take_profit_1=90.0,
                take_profit_2=85.0,
                execution_gate=_gate(can_enter_now=True),
            )
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.opened_trades, 1)
        self.assertEqual(trade_store.trades[0].entry_price, Decimal("99.5"))
        self.assertNotEqual(trade_store.trades[0].entry_price, Decimal("99"))

    async def test_default_forward_entry_price_uses_execution_policy_reference_price(self) -> None:
        run_store = _ForwardRunStore([_run(runtime_state={"last_price": 100.25})])
        trade_store = _RecordingTradeStore()
        runtime = ForwardStrategyTestRuntime(run_store=run_store, trade_store=trade_store)

        result = await runtime.process_strategy_signal(
            _strategy_signal(
                entry_min=100.0,
                entry_max=101.0,
                execution_gate=_gate(can_enter_now=True),
            )
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.opened_trades, 1)
        self.assertEqual(trade_store.trades[0].entry_price, Decimal("100.25"))

    async def test_default_forward_entry_price_keeps_legacy_no_zone_fallback(self) -> None:
        run_store = _ForwardRunStore([_run()])
        trade_store = _RecordingTradeStore()
        runtime = ForwardStrategyTestRuntime(run_store=run_store, trade_store=trade_store)

        result = await runtime.process_strategy_signal(
            _strategy_signal(
                entry_min=None,
                entry_max=None,
                stop_loss=95.0,
                take_profit_1=110.0,
                take_profit_2=None,
                execution_gate=_gate(can_enter_now=True),
            )
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.opened_trades, 1)
        self.assertEqual(trade_store.trades[0].entry_price, Decimal("110"))

    async def test_pending_forward_signal_records_isolated_event_without_normal_pending_service(self) -> None:
        run_store = _ForwardRunStore([_run()])
        trade_store = _RecordingTradeStore()
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=trade_store,
            signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_arm_pending=True))),
            virtual_trading=_VirtualTrading(),
        )

        result = await runtime.process_strategy_signal(_strategy_signal())

        self.assertEqual(result.errors, [])
        self.assertEqual(result.signals_processed, 1)
        self.assertEqual(result.pending_entries_armed, 1)
        self.assertEqual(len(trade_store.trades), 0)
        self.assertEqual(len(trade_store.signal_events), 1)
        self.assertEqual(trade_store.signal_events[0].funnel_stage, "pending")
        self.assertEqual(trade_store.signal_events[0].filled, False)
        self.assertEqual(trade_store.signal_events[0].execution_candidate, True)
        runtime_state = run_store.get_run(RUN_ID).run.runtime_state  # type: ignore[union-attr]
        self.assertEqual(runtime_state["signal_events_written"], 1)
        self.assertEqual(runtime_state["pending_entries_armed"], 1)

    async def test_wait_for_pullback_pending_entry_opens_on_future_entry_touch(self) -> None:
        run_store = _ForwardRunStore([_run()])
        trade_store = _RecordingTradeStore()
        virtual_trading = _VirtualTrading()
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=trade_store,
            signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_arm_pending=True))),
            virtual_trading=virtual_trading,
        )

        pending_result = await runtime.process_strategy_signal(_strategy_signal())
        runtime_state = run_store.get_run(RUN_ID).run.runtime_state  # type: ignore[union-attr]
        pending_entries = runtime_state["pending_entries"]

        self.assertEqual(pending_result.pending_entries_armed, 1)
        self.assertEqual(len(pending_entries), 1)
        self.assertEqual(pending_entries[0]["status"], "pending")
        self.assertEqual(pending_entries[0]["signal_id"], "sig_1")
        self.assertEqual(pending_entries[0]["exchange"], "bybit")
        self.assertEqual(pending_entries[0]["symbol"], "BTCUSDT")
        self.assertEqual(pending_entries[0]["side"], "long")
        self.assertEqual(pending_entries[0]["entry_min"], 100.0)
        self.assertEqual(pending_entries[0]["entry_max"], 101.0)
        self.assertEqual(pending_entries[0]["stop_loss"], 95.0)
        self.assertEqual(pending_entries[0]["targets"], [110.0, 115.0])
        self.assertIsNone(pending_entries[0]["expires_at"])
        self.assertTrue(pending_entries[0]["trade_plan_hash"].startswith("sha256:"))
        self.assertEqual(pending_entries[0]["created_at"], NOW.isoformat())

        fill_result = await runtime.process_market_tick(
            MarketData(exchange="bybit", symbol="BTCUSDT", price=100.5, volume=1.0, timestamp=1_780_000_060)
        )
        runtime_state = run_store.get_run(RUN_ID).run.runtime_state  # type: ignore[union-attr]

        self.assertEqual(fill_result.opened_trades, 1)
        self.assertEqual(len(virtual_trading.open_calls), 1)
        self.assertEqual(virtual_trading.open_calls[0][0].id, "sig_1")
        self.assertEqual(len(trade_store.trades), 1)
        self.assertEqual(trade_store.trades[0].trade_id, "trade_1")
        self.assertEqual(len(trade_store.signal_events), 2)
        self.assertEqual(trade_store.signal_events[1].funnel_stage, "filled")
        self.assertEqual(trade_store.signal_events[1].outcome, "filled")
        self.assertEqual(runtime_state["pending_entries"][0]["status"], "filled")
        self.assertEqual(runtime_state["pending_entries"][0]["trade_id"], "trade_1")
        self.assertEqual(runtime_state["opened_trades"], 1)

    async def test_default_forward_pending_touch_uses_bounded_touch_price(self) -> None:
        run_store = _ForwardRunStore([_run()])
        trade_store = _RecordingTradeStore()
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=trade_store,
            signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_arm_pending=True))),
        )

        pending_result = await runtime.process_strategy_signal(_strategy_signal())
        fill_result = await runtime.process_market_tick(
            MarketData(exchange="bybit", symbol="BTCUSDT", price=100.25, volume=1.0, timestamp=1_780_000_060)
        )

        self.assertEqual(pending_result.pending_entries_armed, 1)
        self.assertEqual(fill_result.errors, [])
        self.assertEqual(fill_result.opened_trades, 1)
        self.assertEqual(trade_store.trades[0].entry_price, Decimal("100.25"))
        runtime_state = run_store.get_run(RUN_ID).run.runtime_state  # type: ignore[union-attr]
        self.assertEqual(runtime_state["pending_entries"][0]["touch_price"], 100.25)

    async def test_execution_policy_pending_retest_records_forward_pending_event(self) -> None:
        run_store = _ForwardRunStore(
            [
                _run(
                    params={"execution_policy": {"allow_pending_retest": True}},
                    runtime_state={"last_price": 105},
                )
            ]
        )
        trade_store = _RecordingTradeStore()
        virtual_trading = _VirtualTrading()
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=trade_store,
            signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True))),
            virtual_trading=virtual_trading,
        )

        result = await runtime.process_strategy_signal(_strategy_signal())

        self.assertEqual(result.opened_trades, 0)
        self.assertEqual(result.pending_entries_armed, 1)
        self.assertEqual(virtual_trading.open_calls, [])
        self.assertEqual(len(trade_store.signal_events), 1)
        self.assertEqual(trade_store.signal_events[0].funnel_stage, "pending")
        self.assertEqual(trade_store.signal_events[0].trigger_reason_code, "entry_zone_missed_wait_for_retest")

    async def test_process_strategy_signal_opens_virtual_trade_and_records_runtime_state(self) -> None:
        run_store = _ForwardRunStore([_run()])
        trade_store = _RecordingTradeStore()
        signal_writer = _SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True)))
        virtual_trading = _VirtualTrading()
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=trade_store,
            signal_writer=signal_writer,
            virtual_trading=virtual_trading,
        )

        result = await runtime.process_strategy_signal(_strategy_signal())

        self.assertEqual(result.signals_processed, 1)
        self.assertEqual(result.opened_trades, 1)
        self.assertEqual(result.metrics_written, 1)
        self.assertEqual(len(virtual_trading.open_calls), 1)
        self.assertIsInstance(virtual_trading.open_calls[0][1], ManualConfirmRequest)
        self.assertEqual(virtual_trading.open_calls[0][1].mode, "virtual")
        self.assertEqual(virtual_trading.open_calls[0][1].user_id, USER_ID)
        self.assertEqual(len(trade_store.trades), 1)
        self.assertEqual(len(trade_store.metrics), 1)
        self.assertEqual(trade_store.trades[0].run_id, RUN_ID)
        self.assertEqual(trade_store.trades[0].trade_id, "trade_1")
        self.assertEqual(trade_store.metrics[0].metric_code, "forward_opened_trades")
        runtime_state = run_store.get_run(RUN_ID).run.runtime_state  # type: ignore[union-attr]
        self.assertEqual(runtime_state["processed_signals"], 1)
        self.assertEqual(runtime_state["opened_trades"], 1)
        self.assertEqual(runtime_state["metrics_written"], 1)
        self.assertEqual(runtime_state["last_signal_id"], "sig_1")
        self.assertIsNotNone(run_store.get_run(RUN_ID).run.last_heartbeat_at)  # type: ignore[union-attr]

    async def test_process_strategy_signal_blocks_when_forward_portfolio_limit_is_reached(self) -> None:
        run_store = _ForwardRunStore(
            [
                _run(
                    params={"max_concurrent_positions": 1},
                    runtime_state={
                        "forward_account": {
                            "initial_capital": "1000",
                            "balance": "1000",
                            "equity": "1000",
                            "realized_pnl": "0",
                            "unrealized_pnl": "0",
                            "fees": "0",
                            "slippage": "0",
                            "open_positions": 1,
                            "closed_positions": 0,
                        },
                        "forward_positions": [
                            {
                                "trade_id": "existing_trade",
                                "signal_id": "existing_sig",
                                "exchange": "bybit",
                                "symbol": "BTCUSDT",
                                "strategy": "trend_pullback_continuation",
                                "status": "open",
                                "risk_amount": "10",
                            }
                        ],
                    },
                )
            ]
        )
        trade_store = _RecordingTradeStore()
        virtual_trading = _VirtualTrading()
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=trade_store,
            signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True))),
            virtual_trading=virtual_trading,
        )

        result = await runtime.process_strategy_signal(_strategy_signal())

        self.assertEqual(result.signals_processed, 1)
        self.assertEqual(result.opened_trades, 0)
        self.assertEqual(virtual_trading.open_calls, [])
        self.assertEqual(len(trade_store.signal_events), 1)
        self.assertEqual(trade_store.signal_events[0].funnel_stage, "blocked")
        self.assertEqual(trade_store.signal_events[0].blocked_reason_code, "max_concurrent_positions_exceeded")
        runtime_state = run_store.get_run(RUN_ID).run.runtime_state  # type: ignore[union-attr]
        self.assertEqual(runtime_state["last_gate_status"], "blocked")

    async def test_process_strategy_signal_reduces_forward_size_to_open_risk_budget(self) -> None:
        run_store = _ForwardRunStore(
            [
                _run(
                    params={
                        "risk_settings": {
                            "max_open_risk_percent": 5,
                            "max_symbol_risk_percent": 100,
                            "max_strategy_exposure_percent": 100,
                        }
                    },
                    runtime_state={
                        "forward_account": {
                            "initial_capital": "1000",
                            "balance": "1000",
                            "equity": "1000",
                            "realized_pnl": "0",
                            "unrealized_pnl": "0",
                            "fees": "0",
                            "slippage": "0",
                            "open_positions": 1,
                            "closed_positions": 0,
                        },
                        "forward_positions": [
                            {
                                "trade_id": "existing_trade",
                                "signal_id": "existing_sig",
                                "exchange": "bybit",
                                "symbol": "BTCUSDT",
                                "strategy": "trend_pullback_continuation",
                                "status": "open",
                                "risk_amount": "49.5",
                            }
                        ],
                    },
                )
            ]
        )
        virtual_trading = _VirtualTrading()
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True))),
            virtual_trading=virtual_trading,
        )

        result = await runtime.process_strategy_signal(_strategy_signal())

        self.assertEqual(result.opened_trades, 1)
        self.assertEqual(len(virtual_trading.open_calls), 1)
        self.assertAlmostEqual(virtual_trading.open_calls[0][1].size_usd or 0, 50.0)
        self.assertEqual(
            virtual_trading.open_calls[0][1].metadata["portfolio_risk"]["reason_code"],
            "max_open_risk_exceeded",
        )

    async def test_process_strategy_signal_filters_by_requested_matrix(self) -> None:
        run_store = _ForwardRunStore([_run(pairs=[StrategyTestPair(exchange="bybit", symbol="ETHUSDT")])])
        virtual_trading = _VirtualTrading()
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True))),
            virtual_trading=virtual_trading,
        )

        result = await runtime.process_strategy_signal(_strategy_signal(symbol="BTCUSDT"))

        self.assertEqual(result.signals_processed, 0)
        self.assertEqual(result.signals_skipped, 1)
        self.assertEqual(virtual_trading.open_calls, [])

    async def test_process_market_tick_delegates_to_scanner_and_processes_returned_signals(self) -> None:
        scanner = _Scanner([_strategy_signal()])
        virtual_trading = _VirtualTrading()
        runtime = ForwardStrategyTestRuntime(
            run_store=_ForwardRunStore([_run()]),
            trade_store=_RecordingTradeStore(),
            signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True))),
            virtual_trading=virtual_trading,
            scanner=scanner,
        )
        tick = MarketData(exchange="bybit", symbol="BTCUSDT", price=100.0, volume=1.0, timestamp=1_780_000_000)

        result = await runtime.process_market_tick(tick)

        self.assertEqual(scanner.ticks, [tick])
        self.assertEqual(result.ticks_processed, 1)
        self.assertEqual(result.signals_processed, 1)
        self.assertEqual(result.opened_trades, 1)

    async def test_process_market_tick_closes_isolated_position_at_target(self) -> None:
        run = _run(runtime_state={
            "forward_account": {
                "initial_capital": "1000",
                "balance": "1000",
                "equity": "1000",
                "realized_pnl": "0",
                "unrealized_pnl": "0",
                "fees": "0",
                "slippage": "0",
                "open_positions": 1,
                "closed_positions": 0,
            },
            "forward_positions": [
                {
                    "trade_id": "trade_target",
                    "signal_id": "sig_target",
                    "exchange": "bybit",
                    "symbol": "BTCUSDT",
                    "strategy": "trend_pullback_continuation",
                    "timeframe": "15m",
                    "side": "long",
                    "entry_price": "100",
                    "current_price": "100",
                    "size_usd": "100",
                    "quantity": "1",
                    "stop_loss": "95",
                    "take_profit": ["110"],
                    "unrealized_pnl": "0",
                    "fees": "0",
                    "status": "open",
                    "opened_at": NOW.isoformat(),
                }
            ],
        })
        run_store = _ForwardRunStore([run])
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            virtual_trading=_VirtualTrading(),
        )
        tick = MarketData(exchange="bybit", symbol="BTCUSDT", price=112.0, volume=1.0, timestamp=1_780_000_060)

        result = await runtime.process_market_tick(tick)

        self.assertEqual(result.ticks_processed, 1)
        state = run_store.get_run(RUN_ID).run.runtime_state  # type: ignore[union-attr]
        self.assertEqual(state["forward_positions"][0]["status"], "closed")
        self.assertEqual(state["forward_positions"][0]["close_reason"], "take_profit")
        self.assertEqual(state["forward_positions"][0]["realized_pnl"], "12")
        self.assertEqual(state["forward_account"]["open_positions"], 0)
        self.assertEqual(state["forward_account"]["closed_positions"], 1)
        self.assertEqual(state["forward_account"]["realized_pnl"], "12")
        self.assertEqual(state["forward_account"]["unrealized_pnl"], "0")
        self.assertEqual(state["forward_account"]["equity"], "1012")

    async def test_process_market_tick_persists_forward_close_trade_event_and_metrics(self) -> None:
        scenarios = [
            ("take_profit", "forward_wins", 115.0),
            ("stop_loss", "forward_losses", 94.0),
        ]
        for close_reason, result_metric_code, close_price in scenarios:
            with self.subTest(close_reason=close_reason):
                run_store = _ForwardRunStore([_run()])
                trade_store = _RecordingTradeStore()
                runtime = ForwardStrategyTestRuntime(
                    run_store=run_store,
                    trade_store=trade_store,
                    signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True))),
                    virtual_trading=_VirtualTrading(),
                )

                open_result = await runtime.process_strategy_signal(_strategy_signal())
                tick_result = await runtime.process_market_tick(
                    MarketData(
                        exchange="bybit",
                        symbol="BTCUSDT",
                        price=close_price,
                        volume=1.0,
                        timestamp=1_780_000_060,
                    )
                )

                self.assertEqual(open_result.opened_trades, 1)
                self.assertEqual(tick_result.ticks_processed, 1)
                closed_trades = [trade for trade in trade_store.trades if trade.exit_time is not None]
                close_events = [event for event in trade_store.signal_events if event.closed]
                metric_codes = [row.metric_code for row in trade_store.metrics]
                self.assertEqual(len(closed_trades), 1)
                self.assertEqual(closed_trades[0].trade_id, "trade_1")
                self.assertEqual(closed_trades[0].close_reason, close_reason)
                self.assertEqual(len(close_events), 1)
                self.assertEqual(close_events[0].signal_id, "sig_1")
                self.assertEqual(close_events[0].outcome, close_reason)
                self.assertEqual(close_events[0].funnel_stage, "closed")
                self.assertIn("forward_closed_trades", metric_codes)
                self.assertIn(result_metric_code, metric_codes)
                self.assertIn("realized_pnl", metric_codes)
                self.assertIn("pnl_percent", metric_codes)

    async def test_process_market_tick_partially_closes_first_forward_target(self) -> None:
        run = _run(runtime_state={
            "forward_account": {
                "initial_capital": "1000",
                "balance": "1000",
                "equity": "1000",
                "realized_pnl": "0",
                "unrealized_pnl": "0",
                "fees": "0",
                "slippage": "0",
                "open_positions": 1,
                "closed_positions": 0,
            },
            "forward_positions": [
                {
                    "trade_id": "trade_partial",
                    "signal_id": "sig_partial",
                    "exchange": "bybit",
                    "symbol": "BTCUSDT",
                    "strategy": "trend_pullback_continuation",
                    "timeframe": "15m",
                    "side": "long",
                    "entry_price": "100",
                    "current_price": "100",
                    "size_usd": "100",
                    "quantity": "1",
                    "stop_loss": "95",
                    "take_profit": ["110", "120"],
                    "unrealized_pnl": "0",
                    "fees": "0",
                    "status": "open",
                    "opened_at": NOW.isoformat(),
                }
            ],
        })
        run_store = _ForwardRunStore([run])
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            virtual_trading=_VirtualTrading(),
        )
        tick = MarketData(exchange="bybit", symbol="BTCUSDT", price=110.0, volume=1.0, timestamp=1_780_000_060)

        result = await runtime.process_market_tick(tick)

        self.assertEqual(result.ticks_processed, 1)
        state = run_store.get_run(RUN_ID).run.runtime_state  # type: ignore[union-attr]
        position = state["forward_positions"][0]
        self.assertEqual(position["status"], "partially_closed")
        self.assertEqual(position["close_reason"], "partial_take_profit")
        self.assertEqual(position["realized_pnl"], "5")
        self.assertEqual(position["remaining_quantity"], "0.5")
        self.assertEqual(state["forward_account"]["open_positions"], 1)
        self.assertEqual(state["forward_account"]["closed_positions"], 0)
        self.assertEqual(state["forward_account"]["realized_pnl"], "5")
        self.assertEqual(state["forward_account"]["unrealized_pnl"], "5")

    async def test_stopping_run_is_cancelled_after_current_iteration_and_cancelled_runs_are_ignored(self) -> None:
        stopping = _run(status="stopping")
        cancelled = _run(run_id=uuid4(), status="cancelled")
        run_store = _ForwardRunStore([stopping, cancelled])
        virtual_trading = _VirtualTrading()
        runtime = ForwardStrategyTestRuntime(
            run_store=run_store,
            trade_store=_RecordingTradeStore(),
            signal_writer=_SignalWriter(_radar_signal(execution_gate=_gate(can_enter_now=True))),
            virtual_trading=virtual_trading,
        )

        result = await runtime.process_strategy_signal(_strategy_signal())

        self.assertEqual(result.cancelled_runs, 1)
        self.assertEqual(run_store.get_run(stopping.run_id).run.status, "cancelled")  # type: ignore[union-attr]
        self.assertEqual(run_store.get_run(cancelled.run_id).run.status, "cancelled")  # type: ignore[union-attr]
        self.assertEqual(virtual_trading.open_calls, [])


class ForwardStrategyTestWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_strategy_signal_delegates_to_runtime_and_updates_last_result(self) -> None:
        runtime = _WorkerSignalRuntime()
        worker = ForwardStrategyTestWorker(runtime=runtime)  # type: ignore[arg-type]
        signal = _strategy_signal()

        result = await worker.process_strategy_signal(signal)

        self.assertIs(result, worker.last_result)
        self.assertEqual(result.signals_processed, 1)
        self.assertEqual(runtime.signals, [signal])

    async def test_heartbeat_exception_sets_last_result_errors_and_keeps_loop_running(self) -> None:
        runtime = _FailingHeartbeatRuntime()
        worker = ForwardStrategyTestWorker(runtime=runtime)  # type: ignore[arg-type]
        worker._interval_seconds = 0.01
        task = asyncio.create_task(worker._run())

        try:
            await _wait_until(lambda: runtime.heartbeat_calls >= 2 or task.done())

            self.assertFalse(task.done())
            self.assertGreaterEqual(runtime.heartbeat_calls, 2)
            self.assertEqual(worker.last_result.errors, ["heartbeat failed"])
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                await task


def _run(
    *,
    run_id: UUID = RUN_ID,
    status: StrategyTestRunStatus = "running",
    pairs: list[StrategyTestPair] | None = None,
    params: dict[str, Any] | None = None,
    runtime_state: dict[str, Any] | None = None,
) -> StrategyTestRunResponse:
    request = _run_request(pairs=pairs, params=params)
    return StrategyTestRunResponse(
        run_id=run_id,
        status=status,
        test_type="forward_virtual",
        requested_matrix=_requested_matrix(request),
        runtime_state=runtime_state or {},
        created_at=NOW,
        started_at=NOW if status in {"running", "stopping"} else None,
        last_heartbeat_at=NOW if status in {"running", "stopping"} else None,
    )


def _run_request(
    *,
    pairs: list[StrategyTestPair] | None = None,
    params: dict[str, Any] | None = None,
) -> StrategyTestRunRequest:
    request = StrategyTestRunRequest(
        user_id=USER_ID,
        test_type="forward_virtual",
        strategies=["trend_pullback_continuation"],
        pairs=pairs or [StrategyTestPair(exchange="bybit", symbol="BTCUSDT")],
        timeframes=["15m"],
        start_at=NOW - timedelta(hours=1),
        end_at=NOW + timedelta(hours=1),
        mode="research_virtual",
        initial_capital=Decimal("1000"),
        params=params or {},
        tags=["forward"],
    )
    return request


def _strategy_signal(
    *,
    symbol: str = "BTCUSDT",
    direction: Literal["LONG", "SHORT"] = "LONG",
    entry_min: float | None = 100.0,
    entry_max: float | None = 101.0,
    stop_loss: float | None = 95.0,
    take_profit_1: float | None = 110.0,
    take_profit_2: float | None = 115.0,
    execution_gate: SignalExecutionGateSnapshot | None = None,
) -> StrategySignal:
    return StrategySignal(
        exchange="bybit",
        symbol=symbol,
        strategy="trend_pullback_continuation",
        direction=direction,
        confidence=0.82,
        timestamp=1_780_000_000,
        score=82,
        timeframe="15m",
        status="actionable",
        entry_min=entry_min,
        entry_max=entry_max,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        risk_reward=2.0,
        execution_gate=execution_gate,
    )


def _radar_signal(*, execution_gate: SignalExecutionGateSnapshot) -> RadarSignal:
    return RadarSignal(
        id="sig_1",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.82,
        risk_reward=2.0,
        status="actionable",
        score=82,
        timeframe="15m",
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=95.0,
        take_profit_1=110.0,
        take_profit_2=115.0,
        created_at=NOW,
        updated_at=NOW,
        execution_gate=execution_gate,
    )


def _gate(*, can_enter_now: bool = False, can_arm_pending: bool = False) -> SignalExecutionGateSnapshot:
    return SignalExecutionGateSnapshot(
        status="passed",
        feed_kind="execution_signal" if can_enter_now else "watchlist",
        can_notify=can_enter_now,
        can_enter_now=can_enter_now,
        can_arm_pending=can_arm_pending,
        can_show_in_execution_feed=can_enter_now,
    )


def _trade(signal_id: str = "sig_1") -> VirtualTrade:
    return VirtualTrade(
        id="trade_1",
        user_id=USER_ID,
        signal_id=signal_id,
        exchange="bybit",
        symbol="BTCUSDT",
        strategy="trend_pullback_continuation",
        timeframe="15m",
        side="long",
        entry_price=100.5,
        current_price=100.5,
        size_usd=100.0,
        quantity=1.0,
        leverage=1,
        risk_percent=1.0,
        stop_loss=95.0,
        take_profit=[110.0, 115.0],
        opened_at=NOW,
        updated_at=NOW,
    )


def _requested_matrix(request: StrategyTestRunRequest) -> dict[str, Any]:
    return {
        "user_id": request.user_id,
        "test_type": request.test_type,
        "mode": request.mode,
        "strategies": request.strategies,
        "pairs": [pair.model_dump(mode="json") for pair in request.pairs],
        "timeframes": request.timeframes,
        "start_at": request.start_at,
        "end_at": request.end_at,
        "initial_capital": request.initial_capital,
        "fee_rate": request.fee_rate,
        "slippage_bps": request.slippage_bps,
        "same_candle_policy": request.same_candle_policy,
        "params": request.params,
        "metric_set": request.metric_set,
        "tags": request.tags,
        "scenario_count": len(request.strategies) * len(request.pairs) * len(request.timeframes),
    }


class _ForwardRunStore:
    def __init__(self, runs: Sequence[StrategyTestRunResponse]) -> None:
        self._runs = {run.run_id: StrategyTestRunDetailResponse(run=run) for run in runs}

    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        runs = list(self._runs.values())
        if user_id is not None:
            runs = [detail for detail in runs if detail.run.requested_matrix["user_id"] == user_id]
        if status is not None:
            runs = [detail for detail in runs if detail.run.status == status]
        return runs[:limit]

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        return self._runs.get(run_id)

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        updated = detail.run.model_copy(update={"status": "running", "started_at": NOW, "last_heartbeat_at": NOW})
        self._runs[run_id] = StrategyTestRunDetailResponse(run=updated)
        return self._runs[run_id]

    def mark_cancelled(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        updated = detail.run.model_copy(update={"status": "cancelled", "last_heartbeat_at": NOW})
        self._runs[run_id] = StrategyTestRunDetailResponse(run=updated)
        return self._runs[run_id]

    def update_runtime_state(
        self,
        run_id: UUID,
        runtime_state: dict[str, Any],
        *,
        heartbeat: bool = True,
    ) -> StrategyTestRunDetailResponse:
        detail = self._runs[run_id]
        updated_state = {**detail.run.runtime_state, **runtime_state}
        update: dict[str, Any] = {"runtime_state": updated_state}
        if heartbeat:
            update["last_heartbeat_at"] = NOW
        self._runs[run_id] = StrategyTestRunDetailResponse(run=detail.run.model_copy(update=update))
        return self._runs[run_id]


class _RecordingTradeStore:
    def __init__(self) -> None:
        self.trades: list[StrategyTestTrade] = []
        self.metrics: list[StrategyTestMetricRow] = []
        self.signal_events: list[StrategyTestSignalEvent] = []

    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        self.trades.extend(trades)

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        self.metrics.extend(rows)

    def write_signal_events(self, signal_events: Sequence[StrategyTestSignalEvent]) -> None:
        self.signal_events.extend(signal_events)


class _SignalWriter:
    def __init__(self, signal: RadarSignal) -> None:
        self.signal = signal
        self.calls: list[StrategySignal] = []

    def upsert_strategy_signal(
        self,
        signal: StrategySignal,
        exchange: str | None = None,
        explanation: list[str] | None = None,
    ) -> tuple[RadarSignal, bool]:
        _ = exchange, explanation
        self.calls.append(signal)
        return self.signal, True


class _VirtualTrading:
    def __init__(self) -> None:
        self.open_calls: list[tuple[RadarSignal, ManualConfirmRequest]] = []

    def open_virtual_trade(self, signal: RadarSignal, request: ManualConfirmRequest) -> VirtualTrade:
        self.open_calls.append((signal, request))
        return _trade(signal.id)


class _ForbiddenVirtualTrading:
    def open_virtual_trade(self, signal: RadarSignal, request: ManualConfirmRequest) -> VirtualTrade:
        _ = signal, request
        raise AssertionError("forward runtime must use an isolated virtual account by default")


class _Scanner:
    def __init__(self, signals: list[StrategySignal]) -> None:
        self._signals = signals
        self.ticks: list[MarketData] = []

    async def process_tick(self, tick: MarketData) -> list[StrategySignal]:
        self.ticks.append(tick)
        return list(self._signals)


class _WorkerSignalRuntime:
    def __init__(self) -> None:
        self.signals: list[StrategySignal] = []

    async def process_strategy_signal(self, signal: StrategySignal) -> ForwardRuntimeResult:
        self.signals.append(signal)
        return ForwardRuntimeResult(signals_processed=1)


class _FailingHeartbeatRuntime:
    def __init__(self) -> None:
        self.heartbeat_calls = 0

    def heartbeat_active_runs(self) -> ForwardRuntimeResult:
        self.heartbeat_calls += 1
        raise RuntimeError("heartbeat failed")


async def _wait_until(predicate: Callable[[], bool], *, attempts: int = 30) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.01)


if __name__ == "__main__":
    unittest.main()
