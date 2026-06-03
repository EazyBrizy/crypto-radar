import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.signal import RadarSignal, SignalConfirmationSnapshot, SignalLayerCheck
from app.schemas.user import RiskManagementSettings
from app.services.radar_service import RadarFilters, RadarService


class FakeSignalProvider:
    def __init__(self, signals: list[RadarSignal]) -> None:
        self.signals = signals

    def list_open_signals(self) -> list[RadarSignal]:
        return self.signals


@dataclass(frozen=True)
class FakeRiskDecision:
    status: str
    can_enter: bool


class FakeRiskPreviewEvaluator:
    def __init__(self, decisions: dict[str, FakeRiskDecision]) -> None:
        self.decisions = decisions
        self.calls: list[dict[str, object]] = []

    def evaluate(self, request, *, record_audit: bool = True) -> FakeRiskDecision:
        self.calls.append(
            {
                "signal_id": request.signal_id,
                "user_id": request.user_id,
                "record_audit": record_audit,
            }
        )
        return self.decisions.get(
            request.signal_id,
            FakeRiskDecision(status="failed", can_enter=False),
        )


class RadarServiceTest(unittest.TestCase):
    def test_all_mode_returns_actionable_blocked_by_rr_and_waiting_setups(self) -> None:
        active = _signal(status="active", rr_status="passed")
        blocked_by_rr = _signal(status="ready", rr_status="failed")
        waiting_entry = _signal(status="wait_for_pullback", rr_status="warning")
        risk_preview = FakeRiskPreviewEvaluator({})
        service = _service(
            [active, blocked_by_rr, waiting_entry],
            risk_preview=risk_preview,
            user_mode="all_market_opportunities",
        )

        response = service.list_signals(
            user_id="demo_user",
            mode="all_market_opportunities",
        )

        self.assertEqual(
            [signal.id for signal in response.signals],
            [active.id, blocked_by_rr.id, waiting_entry.id],
        )
        self.assertEqual(
            [signal.rr_status for signal in response.signals],
            ["passed", "failed", "warning"],
        )
        self.assertEqual([signal.can_enter for signal in response.signals], [None, None, None])
        self.assertTrue(all("all_market_opportunities" in (signal.display_reason or "") for signal in response.signals))
        self.assertEqual(risk_preview.calls, [])

    def test_execution_ready_returns_only_actionable_or_entry_touched_with_risk_gate_can_enter(self) -> None:
        actionable = _signal(status="actionable", rr_status="passed")
        entry_touched = _signal(status="entry_touched", rr_status="passed")
        waiting_entry = _signal(status="ready", rr_status="passed")
        denied = _signal(status="actionable", rr_status="passed")
        risk_preview = FakeRiskPreviewEvaluator(
            {
                actionable.id: FakeRiskDecision(status="passed", can_enter=True),
                entry_touched.id: FakeRiskDecision(status="warning", can_enter=True),
                denied.id: FakeRiskDecision(status="failed", can_enter=False),
            }
        )
        service = _service(
            [actionable, entry_touched, waiting_entry, denied],
            risk_preview=risk_preview,
            user_mode="all_market_opportunities",
        )

        response = service.list_signals(
            user_id="demo_user",
            mode="execution_ready",
        )

        self.assertEqual([signal.id for signal in response.signals], [actionable.id, entry_touched.id])
        self.assertEqual([signal.risk_gate_status for signal in response.signals], ["passed", "warning"])
        self.assertEqual([signal.can_enter for signal in response.signals], [True, True])
        self.assertTrue(all("RiskGate preview allowed" in (signal.display_reason or "") for signal in response.signals))
        self.assertEqual(
            risk_preview.calls,
            [
                {"signal_id": actionable.id, "user_id": "demo_user", "record_audit": False},
                {"signal_id": entry_touched.id, "user_id": "demo_user", "record_audit": False},
                {"signal_id": denied.id, "user_id": "demo_user", "record_audit": False},
            ],
        )

    def test_user_execution_ready_mode_is_resolved_when_request_mode_is_absent(self) -> None:
        actionable = _signal(status="actionable", rr_status="passed")
        waiting_entry = _signal(status="ready", rr_status="passed")
        risk_preview = FakeRiskPreviewEvaluator(
            {actionable.id: FakeRiskDecision(status="passed", can_enter=True)}
        )
        service = _service(
            [actionable, waiting_entry],
            risk_preview=risk_preview,
            user_mode="execution_ready",
        )

        response = service.list_signals(user_id="demo_user")

        self.assertEqual([signal.id for signal in response.signals], [actionable.id])
        self.assertEqual(risk_preview.calls[0]["record_audit"], False)

    def test_filters_apply_before_display_mode(self) -> None:
        btc = _signal(symbol="BTCUSDT", exchange="bybit", timeframe="15m")
        eth = _signal(symbol="ETHUSDT", exchange="bybit", timeframe="15m")
        other_timeframe = _signal(symbol="BTCUSDT", exchange="bybit", timeframe="1h")
        service = _service(
            [btc, eth, other_timeframe],
            risk_preview=FakeRiskPreviewEvaluator({}),
            user_mode="all_market_opportunities",
        )

        response = service.list_signals(
            user_id="demo_user",
            mode="all_market_opportunities",
            filters=RadarFilters(exchange="BYBIT", symbol="BTC/USDT", timeframe="15m"),
        )

        self.assertEqual([signal.id for signal in response.signals], [btc.id])


def _service(
    signals: list[RadarSignal],
    *,
    risk_preview: FakeRiskPreviewEvaluator,
    user_mode: str,
) -> RadarService:
    return RadarService(
        signal_provider=FakeSignalProvider(signals),
        risk_preview_evaluator=risk_preview,
        user_risk_settings_provider=lambda user_id: RiskManagementSettings(radar_display_mode=user_mode),
        strategy_risk_settings_provider=lambda signal, *, user_id: ({}, "not_configured"),
    )


def _signal(
    *,
    status: str = "actionable",
    rr_status: str = "passed",
    symbol: str = "BTCUSDT",
    exchange: str = "bybit",
    timeframe: str = "15m",
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=str(uuid4()),
        symbol=symbol,
        exchange=exchange,
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.82,
        risk_reward=2.5,
        selected_rr=2.5,
        selected_rr_target="final",
        min_rr_ratio=1.5,
        urgency="medium",
        status=status,
        score=82,
        timeframe=timeframe,
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=105.0,
        confirmation=SignalConfirmationSnapshot(
            passed=rr_status != "failed",
            checks=[
                SignalLayerCheck(
                    name="risk_reward_guard",
                    status=rr_status if rr_status in {"passed", "warning", "failed", "skipped"} else "skipped",
                    metadata={"rr_status": rr_status},
                )
            ],
        ),
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
