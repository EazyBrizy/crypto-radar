from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID, uuid4

from app.schemas.candle import OHLCVCandle
from app.schemas.decision import SignalDecisionSnapshot
from app.schemas.signal import (
    NoTradeFilterResult,
    SignalExecutionGateSnapshot,
    SignalTriggerSnapshot,
    StrategySignal,
)
from app.schemas.trade_plan import build_trade_plan_from_legacy_fields
from app.services.strategy_testing.forward_runner import (
    ForwardTestSignalBatch,
    StrategyForwardTestRunner,
)
from app.services.strategy_testing.schemas import StrategyTestPair, StrategyTestRunRequest


class StrategyForwardTestRunnerTest(unittest.TestCase):
    def test_forward_strategy_test_records_signal_rows(self) -> None:
        run_id = uuid4()
        runner = StrategyForwardTestRunner(signal_provider=_SignalProvider([
            _batch([_signal(signal_id="signal-1")])
        ]))

        result = runner.run_once(run_id=run_id, user_uuid=_user_uuid(), request=_request())

        self.assertEqual(len(result.signals), 1)
        self.assertEqual(result.signals[0].run_id, run_id)
        self.assertEqual(result.signals[0].signal_id, "signal-1")
        self.assertEqual(result.summary["signals_seen"], 1)
        self.assertEqual(result.summary["execution_candidates"], 1)

    def test_forward_strategy_test_does_not_write_radar_signals(self) -> None:
        writer = _ExplodingRadarWriter()
        runner = StrategyForwardTestRunner(
            radar_signal_writer=writer,
            signal_provider=_SignalProvider([_batch([_signal(signal_id="signal-1")])]),
        )

        runner.run_once(run_id=uuid4(), user_uuid=_user_uuid(), request=_request())

        self.assertEqual(writer.calls, 0)

    def test_forward_strategy_test_auto_enters_virtual_on_gate_passed(self) -> None:
        runner = StrategyForwardTestRunner(signal_provider=_SignalProvider([
            _batch([_signal(signal_id="signal-1")], close=Decimal("100.5"))
        ]))

        result = runner.run_once(run_id=uuid4(), user_uuid=_user_uuid(), request=_request())

        self.assertEqual(result.summary["filled_trades"], 1)
        self.assertEqual(result.summary["open_positions"], 1)
        self.assertTrue(result.signals[0].filled)
        self.assertFalse(result.signals[0].no_entry)

    def test_forward_strategy_test_pending_no_entry_expiry(self) -> None:
        runner = StrategyForwardTestRunner(signal_provider=_SignalProvider([
            _batch([_signal(signal_id="signal-1")], close=Decimal("120"))
        ]))

        result = runner.run_once(
            run_id=uuid4(),
            user_uuid=_user_uuid(),
            request=_request(params={"max_pending_minutes": 0}),
        )

        self.assertEqual(result.summary["pending_entries"], 0)
        self.assertEqual(result.summary["no_entry"], 1)
        self.assertTrue(result.signals[0].no_entry)
        self.assertEqual(result.signals[0].outcome_reason, "expired_before_touch")

    def test_forward_strategy_test_closes_virtual_position_on_sl(self) -> None:
        runner = StrategyForwardTestRunner(signal_provider=_SignalProvider([
            _batch([_signal(signal_id="signal-1")], close=Decimal("100.5"), open_time=1),
            _batch([], close=Decimal("97.5"), low=Decimal("97.0"), open_time=2),
        ]))

        result = runner.run_once(run_id=uuid4(), user_uuid=_user_uuid(), request=_request())

        self.assertEqual(result.summary["closed_trades"], 1)
        self.assertEqual(result.summary["open_positions"], 0)
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].close_reason, "stop_loss")
        self.assertLess(result.trades[0].pnl, Decimal("0"))

    def test_forward_strategy_test_summary_counters_include_blocked_and_rejections(self) -> None:
        runner = StrategyForwardTestRunner(signal_provider=_SignalProvider([
            _batch([
                _signal(signal_id="candidate-1"),
                _signal(
                    signal_id="blocked-1",
                    execution_gate=_gate(feed_kind="blocked", can_enter_now=False, can_arm_pending=False),
                    status="rejected",
                ),
            ])
        ]))

        result = runner.run_once(run_id=uuid4(), user_uuid=_user_uuid(), request=_request())

        self.assertEqual(result.summary["signals_seen"], 2)
        self.assertEqual(result.summary["execution_candidates"], 1)
        self.assertEqual(result.summary["blocked_signals"], 1)
        self.assertEqual(result.summary["risk_rejections"], 0)
        self.assertEqual(result.summary["execution_rejections"], 0)


class _SignalProvider:
    def __init__(self, batches: Sequence[ForwardTestSignalBatch]) -> None:
        self._batches = list(batches)

    def load_batches(
        self,
        *,
        request: StrategyTestRunRequest,
        runtime_state: dict[str, Any],
    ) -> list[ForwardTestSignalBatch]:
        _ = request, runtime_state
        return list(self._batches)


class _ExplodingRadarWriter:
    def __init__(self) -> None:
        self.calls = 0

    def upsert_strategy_signal(self, signal: StrategySignal) -> None:
        self.calls += 1
        raise AssertionError(f"Forward test wrote radar signal {signal.symbol}")


def _request(params: dict[str, Any] | None = None) -> StrategyTestRunRequest:
    now = datetime(2026, 6, 6, tzinfo=timezone.utc)
    return StrategyTestRunRequest(
        test_type="forward_virtual",
        strategies=["trend_pullback_continuation"],
        pairs=[StrategyTestPair(exchange="bybit", symbol="BTCUSDT")],
        timeframes=["1m"],
        start_at=now,
        end_at=now + timedelta(hours=1),
        mode="research_virtual",
        initial_capital=Decimal("1000"),
        params=params or {},
        tags=[],
    )


def _batch(
    signals: list[StrategySignal],
    *,
    close: Decimal = Decimal("100.5"),
    low: Decimal = Decimal("99.5"),
    open_time: int = 1,
) -> ForwardTestSignalBatch:
    close_time = open_time + 59
    return ForwardTestSignalBatch(
        candle=OHLCVCandle(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=open_time,
            close_time=close_time,
            open=float(close),
            high=float(max(close, Decimal("101"))),
            low=float(low),
            close=float(close),
            volume=1000,
            trades=100,
            is_closed=True,
        ),
        signals=signals,
    )


def _signal(
    *,
    signal_id: str,
    execution_gate: SignalExecutionGateSnapshot | None = None,
    status: str = "actionable",
) -> StrategySignal:
    trade_plan = build_trade_plan_from_legacy_fields(
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        risk_reward=2.5,
        selected_rr=2.5,
        selected_rr_target="final",
        min_rr_ratio=1.5,
    )
    return StrategySignal(
        exchange="bybit",
        symbol="BTCUSDT",
        strategy="trend_pullback_continuation",
        direction="LONG",
        confidence=0.82,
        timestamp=int(datetime(2026, 6, 6, tzinfo=timezone.utc).timestamp()),
        score=82,
        timeframe="1m",
        candle_state="closed",
        status=status,
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        risk_reward=2.5,
        selected_rr=2.5,
        selected_rr_target="final",
        min_rr_ratio=1.5,
        trade_plan=trade_plan,
        trigger=SignalTriggerSnapshot(passed=True, trigger_type="closed_candle"),
        no_trade_filter=NoTradeFilterResult(blocked=False),
        decision=SignalDecisionSnapshot(
            setup_valid=True,
            trade_plan_valid=True,
            market_context_score=82,
            signal_actionable=status == "actionable",
            execution_allowed_virtual=True,
            execution_allowed_real=None,
            blockers=[],
            warnings=[],
        ),
        execution_gate=execution_gate or _gate(),
        explanation=[signal_id],
    )


def _gate(
    *,
    feed_kind: str = "execution_signal",
    can_enter_now: bool = True,
    can_arm_pending: bool = True,
) -> SignalExecutionGateSnapshot:
    return SignalExecutionGateSnapshot(
        status="passed" if feed_kind == "execution_signal" else "blocked",
        feed_kind=feed_kind,
        can_enter_now=can_enter_now,
        can_arm_pending=can_arm_pending,
        can_show_in_execution_feed=feed_kind == "execution_signal",
    )


def _user_uuid() -> UUID:
    return UUID("22222222-2222-4222-8222-222222222222")


if __name__ == "__main__":
    unittest.main()
