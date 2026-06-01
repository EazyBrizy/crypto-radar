import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.signal_repository import OPEN_SIGNAL_STATUSES, SignalWriteResult
from app.schemas.signal import NoTradeFilterResult, RadarSignal, SignalConfirmationSnapshot, SignalLayerCheck
from app.schemas.trade_plan import build_trade_plan_from_legacy_fields
from app.services.signal_risk_reward import (
    StrategyRiskRewardBlocked,
    ensure_signal_execution_eligible,
    ensure_signal_research_eligible,
    ensure_strategy_rr_eligible,
    signal_rr_warning_reason,
)
from app.services.signal_service import SignalService


class FakeSignalRepository:
    def __init__(self, result: SignalWriteResult) -> None:
        self.result = result

    def list_signals(self, limit: int = 200) -> list[RadarSignal]:
        return [self.result.signal]

    def list_active_signals(self, limit: int = 200) -> list[RadarSignal]:
        return [self.result.signal] if self.result.signal.status == "active" else []

    def list_open_signals(self, limit: int = 200) -> list[RadarSignal]:
        return [self.result.signal] if self.result.signal.status in OPEN_SIGNAL_STATUSES else []

    def list_open_signals_for_series(self, *, exchange: str, symbol: str, timeframe: str, limit: int = 200) -> list[RadarSignal]:
        signal = self.result.signal
        if signal.exchange == exchange and signal.symbol == symbol and signal.timeframe == timeframe:
            return [signal]
        return []

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        return self.result.signal if signal_id == self.result.signal.id else None

    def add_signal(self, signal: RadarSignal) -> SignalWriteResult:
        return self.result

    def upsert_strategy_signal(self, *args, **kwargs) -> SignalWriteResult:
        return self.result

    def confirm_signal(self, *args, **kwargs) -> SignalWriteResult | None:
        return self.result

    def reject_signal(self, *args, **kwargs) -> SignalWriteResult | None:
        return self.result

    def transition_signal(self, *args, **kwargs) -> SignalWriteResult | None:
        return self.result


class SpyAnalyticsWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def write_event(self, event: dict[str, object]) -> None:
        self.events.append(event)


class SpyHotStore:
    def __init__(self) -> None:
        self.results: list[SignalWriteResult] = []

    def write_signal(self, result: SignalWriteResult) -> None:
        self.results.append(result)


class SignalServiceContractTest(unittest.TestCase):
    def test_no_trade_signal_is_not_research_eligible(self) -> None:
        signal = _risk_signal(
            no_trade_filter=NoTradeFilterResult(
                enabled=True,
                blocked=True,
                hard_block=True,
                blockers=["Spread 84.0 bps is above entry limit 25.0 bps"],
            )
        )

        with self.assertRaises(StrategyRiskRewardBlocked) as exc:
            ensure_signal_research_eligible(signal)

        self.assertIn("Spread 84.0 bps", exc.exception.reason)

    def test_low_rr_signal_remains_research_eligible(self) -> None:
        ensure_signal_research_eligible(_low_rr_signal())

    def test_low_rr_signal_remains_virtual_eligible_when_guard_is_soft(self) -> None:
        ensure_signal_execution_eligible(
            _low_rr_signal(),
            mode="virtual",
            rr_guard_mode="soft",
        )

    def test_low_rr_signal_is_rejected_for_real_execution_when_guard_is_hard(self) -> None:
        with self.assertRaises(StrategyRiskRewardBlocked) as exc:
            ensure_signal_execution_eligible(
                _low_rr_signal(),
                mode="real",
                rr_guard_mode="hard",
            )

        self.assertIn("Execution RR policy rejected", exc.exception.reason)

    def test_legacy_strategy_rr_wrapper_still_uses_hard_execution_policy(self) -> None:
        with self.assertRaises(StrategyRiskRewardBlocked):
            ensure_strategy_rr_eligible(_low_rr_signal())

    def test_signal_rr_warning_reason_uses_low_rr_check_metadata(self) -> None:
        signal = _risk_signal(
            confirmation=SignalConfirmationSnapshot(
                passed=True,
                checks=[
                    SignalLayerCheck(
                        name="risk_reward_guard",
                        status="warning",
                        metadata={
                            "selected_rr": 0.8,
                            "selected_rr_target": "nearest",
                            "min_rr_ratio": 1.5,
                        },
                    )
                ],
            )
        )

        reason = signal_rr_warning_reason(signal)

        self.assertIsNotNone(reason)
        self.assertIn("0.80R", reason or "")
        self.assertIn("1.50R", reason or "")

    def test_off_rr_guard_metadata_does_not_emit_warning_but_hard_execution_can_reject(self) -> None:
        signal = _low_rr_signal().model_copy(
            update={
                "confirmation": SignalConfirmationSnapshot(
                    passed=True,
                    checks=[
                        SignalLayerCheck(
                            name="risk_reward_guard",
                            status="skipped",
                            metadata={
                                "selected_rr": 0.8,
                                "selected_rr_target": "nearest",
                                "min_rr_ratio": 1.5,
                                "risk_reward_guard_mode": "off",
                                "risk_reward_warning": False,
                                "risk_reward_blocked": False,
                            },
                        )
                    ],
                )
            }
        )

        self.assertIsNone(signal_rr_warning_reason(signal))
        ensure_signal_execution_eligible(signal, mode="virtual", rr_guard_mode="off")
        with self.assertRaises(StrategyRiskRewardBlocked):
            ensure_signal_execution_eligible(signal, mode="real", rr_guard_mode="hard")

    def test_radar_signal_keeps_legacy_fields_with_trade_plan(self) -> None:
        signal = RadarSignal(
            id=str(uuid4()),
            symbol="BTCUSDT",
            exchange="bybit",
            strategy="trend_pullback_continuation",
            direction="long",
            confidence=0.82,
            status="active",
            score=82,
            entry_min=100.0,
            entry_max=101.0,
            stop_loss=98.0,
            take_profit_1=103.0,
            take_profit_2=105.0,
            risk_reward=2.5,
            trade_plan=build_trade_plan_from_legacy_fields(
                entry_min=100.0,
                entry_max=101.0,
                stop_loss=98.0,
                take_profit_1=103.0,
                take_profit_2=105.0,
                risk_reward=2.5,
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        payload = signal.model_dump(mode="json")

        self.assertEqual(payload["entry_min"], 100.0)
        self.assertEqual(payload["entry_max"], 101.0)
        self.assertEqual(payload["stop_loss"], 98.0)
        self.assertEqual(payload["take_profit_1"], 103.0)
        self.assertEqual(payload["take_profit_2"], 105.0)
        self.assertEqual(payload["trade_plan"]["targets"][0]["label"], "TP1")

    def test_signal_writes_fan_out_to_analytics_and_hot_store(self) -> None:
        signal = RadarSignal(
            id=str(uuid4()),
            symbol="BTCUSDT",
            exchange="bybit",
            strategy="trend_pullback_continuation",
            direction="long",
            confidence=0.82,
            status="active",
            score=82,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        result = SignalWriteResult(
            signal=signal,
            created=True,
            event_type="signal.created",
            analytics_event={"event_type": "signal.created", "signal_id": signal.id},
        )
        analytics = SpyAnalyticsWriter()
        hot_store = SpyHotStore()
        service = SignalService(
            repository=FakeSignalRepository(result),
            analytics_writer=analytics,
            hot_store=hot_store,
        )

        stored = service.add_signal(signal)

        self.assertEqual(stored.id, signal.id)
        self.assertEqual(analytics.events, [result.analytics_event])
        self.assertEqual(hot_store.results, [result])

    def test_lifecycle_transition_fans_out_to_analytics_and_hot_store(self) -> None:
        signal = RadarSignal(
            id=str(uuid4()),
            symbol="BTCUSDT",
            exchange="bybit",
            strategy="trend_pullback_continuation",
            direction="long",
            confidence=0.82,
            status="actionable",
            score=82,
            timeframe="15m",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        result = SignalWriteResult(
            signal=signal,
            created=False,
            event_type="signal.updated",
            analytics_event={"event_type": "signal.updated", "signal_id": signal.id},
        )
        analytics = SpyAnalyticsWriter()
        hot_store = SpyHotStore()
        service = SignalService(
            repository=FakeSignalRepository(result),
            analytics_writer=analytics,
            hot_store=hot_store,
        )

        transitioned = service.transition_signal(
            signal.id,
            new_status="actionable",
            event_type="signal.updated",
            reason="Confirmation candle closed",
        )

        self.assertEqual(transitioned, signal)
        self.assertEqual(analytics.events, [result.analytics_event])
        self.assertEqual(hot_store.results, [result])


def _risk_signal(**updates) -> RadarSignal:
    now = datetime.now(timezone.utc)
    signal = RadarSignal(
        id=str(uuid4()),
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.82,
        status="active",
        score=82,
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=98.0,
        take_profit_1=101.6,
        take_profit_2=105.0,
        risk_reward=2.5,
        selected_rr=2.5,
        selected_rr_target="final",
        min_rr_ratio=1.5,
        created_at=now,
        updated_at=now,
    )
    return signal.model_copy(update=updates) if updates else signal


def _low_rr_signal() -> RadarSignal:
    return _risk_signal(
        selected_rr=0.8,
        selected_rr_target="nearest",
        min_rr_ratio=1.5,
    )


if __name__ == "__main__":
    unittest.main()
