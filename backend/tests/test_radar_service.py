import unittest
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.signal import RadarSignal, SignalConfirmationSnapshot, SignalExecutionGateSnapshot, SignalLayerCheck
from app.schemas.signal_action import SignalActionState
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
    blockers: list[str] = field(default_factory=list)
    technical_messages: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    technical_message: str | None = None
    reason_code: str | None = None


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

    def test_radar_service_all_feed_hides_blocked_low_score(self) -> None:
        blocked_low = _signal(
            status="ready",
            score=23,
            execution_gate=_execution_gate(
                can_show=False,
                feed_kind="blocked",
                status="blocked",
            ),
        )
        visible_market = _signal(
            status="active",
            score=64,
            symbol="ETHUSDT",
            execution_gate=_execution_gate(
                can_show=False,
                feed_kind="market_idea",
                status="warning",
            ),
        )
        low_market = _signal(
            status="active",
            score=49,
            symbol="XRPUSDT",
            execution_gate=_execution_gate(
                can_show=False,
                feed_kind="market_idea",
                status="warning",
            ),
        )
        service = _service(
            [blocked_low, visible_market, low_market],
            risk_preview=FakeRiskPreviewEvaluator({}),
            user_mode="all_market_opportunities",
        )

        response = service.list_signals(user_id="demo_user", mode="all_market_opportunities")

        self.assertEqual([signal.id for signal in response.signals], [visible_market.id])
        self.assertEqual(response.summary.hidden_blocked_ideas, 1)
        self.assertEqual(response.summary.hidden_low_score_ideas, 1)
        self.assertEqual(response.summary.visible_market_ideas, 1)

    def test_radar_service_blocked_mode_shows_blocked_diagnostics(self) -> None:
        blocked_low = _signal(
            status="ready",
            score=23,
            execution_gate=_execution_gate(
                can_show=False,
                feed_kind="blocked",
                status="blocked",
            ),
        )
        service = _service(
            [blocked_low],
            risk_preview=FakeRiskPreviewEvaluator({}),
            user_mode="all_market_opportunities",
        )

        response = service.list_signals(user_id="demo_user", mode="blocked")

        self.assertEqual([signal.id for signal in response.signals], [blocked_low.id])
        self.assertEqual(response.summary.diagnostic_blocked_ideas, 1)

    def test_radar_summary_counts_hidden_blocked(self) -> None:
        blocked = _signal(
            status="ready",
            score=82,
            execution_gate=_execution_gate(
                can_show=False,
                feed_kind="blocked",
                status="blocked",
            ),
        )
        service = _service(
            [blocked],
            risk_preview=FakeRiskPreviewEvaluator({}),
            user_mode="all_market_opportunities",
        )

        response = service.list_signals(user_id="demo_user", mode="all_market_opportunities")

        self.assertEqual(response.signals, [])
        self.assertEqual(response.summary.hidden_blocked_ideas, 1)
        self.assertEqual(response.summary.diagnostic_blocked_ideas, 1)

    def test_radar_list_does_not_call_action_state_by_default(self) -> None:
        signal = _signal(status="actionable", rr_status="passed")
        calls: list[str] = []

        def action_state_provider(signal: RadarSignal, _user_id: str, _mode: str) -> SignalActionState:
            calls.append(signal.id)
            return SignalActionState(can_enter_now=True)

        service = _service(
            [signal],
            risk_preview=FakeRiskPreviewEvaluator({}),
            user_mode="all_market_opportunities",
            action_state_provider=action_state_provider,
        )

        response = service.list_signals(user_id="demo_user", mode="all_market_opportunities")

        self.assertEqual([item.id for item in response.signals], [signal.id])
        self.assertEqual(calls, [])
        self.assertIsNotNone(response.signals[0].card_view)
        self.assertIsNotNone(response.signals[0].details_view)

    def test_radar_list_include_action_state_true_calls_provider(self) -> None:
        signal = _signal(status="actionable", rr_status="passed")
        calls: list[tuple[str, str, str]] = []

        def action_state_provider(signal: RadarSignal, user_id: str, mode: str) -> SignalActionState:
            calls.append((signal.id, user_id, mode))
            return SignalActionState(can_enter_now=True, primary_action="enter_now")

        service = _service(
            [signal],
            risk_preview=FakeRiskPreviewEvaluator({}),
            user_mode="all_market_opportunities",
            action_state_provider=action_state_provider,
        )

        response = service.list_signals(
            user_id="demo_user",
            mode="all_market_opportunities",
            include_action_state=True,
        )

        self.assertEqual(calls, [(signal.id, "demo_user", "virtual")])
        self.assertTrue(response.signals[0].details_view.can_enter_now)
        self.assertEqual(response.summary.execution_ready_signals, 1)

    def test_execution_ready_returns_only_actionable_or_entry_touched_with_risk_gate_can_enter(self) -> None:
        actionable = _signal(status="actionable", rr_status="passed")
        entry_touched = _signal(status="entry_touched", rr_status="passed", direction="short")
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

    def test_execution_ready_uses_execution_gate_as_source_of_truth(self) -> None:
        gate_passed = _signal(
            status="actionable",
            rr_status="passed",
            execution_gate=_execution_gate(can_show=True),
        )
        status_ready_but_gate_blocked = _signal(
            status="actionable",
            rr_status="passed",
            execution_gate=_execution_gate(can_show=False, feed_kind="blocked", status="blocked"),
        )
        risk_preview = FakeRiskPreviewEvaluator(
            {
                gate_passed.id: FakeRiskDecision(status="passed", can_enter=True),
                status_ready_but_gate_blocked.id: FakeRiskDecision(status="passed", can_enter=True),
            }
        )
        service = _service(
            [gate_passed, status_ready_but_gate_blocked],
            risk_preview=risk_preview,
            user_mode="all_market_opportunities",
        )

        response = service.list_signals(user_id="demo_user", mode="execution_ready")

        self.assertEqual([signal.id for signal in response.signals], [gate_passed.id])
        self.assertEqual(risk_preview.calls, [{"signal_id": gate_passed.id, "user_id": "demo_user", "record_audit": False}])

    def test_execution_ready_dedupes_same_pair_and_direction_by_score(self) -> None:
        lower_score = _signal(
            status="actionable",
            rr_status="passed",
            score=78,
            execution_gate=_execution_gate(can_show=True),
        )
        higher_score = _signal(
            status="actionable",
            rr_status="passed",
            score=91,
            strategy="liquidity_sweep_reversal",
            execution_gate=_execution_gate(can_show=True),
        )
        short_signal = _signal(
            status="actionable",
            rr_status="passed",
            direction="short",
            score=79,
            execution_gate=_execution_gate(can_show=True),
        )
        risk_preview = FakeRiskPreviewEvaluator(
            {
                lower_score.id: FakeRiskDecision(status="passed", can_enter=True),
                higher_score.id: FakeRiskDecision(status="passed", can_enter=True),
                short_signal.id: FakeRiskDecision(status="passed", can_enter=True),
            }
        )
        service = _service(
            [lower_score, higher_score, short_signal],
            risk_preview=risk_preview,
            user_mode="all_market_opportunities",
        )

        response = service.list_signals(user_id="demo_user", mode="execution_ready")

        self.assertEqual([signal.id for signal in response.signals], [higher_score.id, short_signal.id])

    def test_blocked_mode_includes_execution_signals_denied_by_risk_gate(self) -> None:
        gate_passed = _signal(
            status="actionable",
            rr_status="passed",
            execution_gate=_execution_gate(can_show=True),
        )
        gate_blocked = _signal(
            status="actionable",
            rr_status="passed",
            execution_gate=_execution_gate(can_show=False, feed_kind="blocked", status="blocked"),
        )
        risk_preview = FakeRiskPreviewEvaluator(
            {
                gate_passed.id: FakeRiskDecision(
                    status="failed",
                    can_enter=False,
                    blockers=["Daily risk limit reached"],
                )
            }
        )
        service = _service(
            [gate_passed, gate_blocked],
            risk_preview=risk_preview,
            user_mode="all_market_opportunities",
        )

        response = service.list_signals(user_id="demo_user", mode="blocked")

        self.assertEqual([signal.id for signal in response.signals], [gate_passed.id, gate_blocked.id])
        self.assertEqual(response.signals[0].risk_gate_status, "failed")
        self.assertFalse(response.signals[0].can_enter)
        self.assertIn("Daily risk limit reached", response.signals[0].display_reason or "")
        self.assertEqual(risk_preview.calls, [{"signal_id": gate_passed.id, "user_id": "demo_user", "record_audit": False}])

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

    def test_strategy_display_mode_override_is_cached_when_request_mode_is_absent(self) -> None:
        active = _signal(status="active", rr_status="passed")
        ready = _signal(status="ready", rr_status="passed")
        strategy_calls: list[str] = []

        def strategy_risk_settings_provider(signal: RadarSignal, *, user_id: str):
            strategy_calls.append(signal.id)
            return {"radar_display_mode": "all_market_opportunities"}, "strategy_config"

        service = _service(
            [active, ready],
            risk_preview=FakeRiskPreviewEvaluator({}),
            user_mode="execution_ready",
            strategy_risk_settings_provider=strategy_risk_settings_provider,
        )

        response = service.list_signals(user_id="demo_user")

        self.assertEqual([signal.id for signal in response.signals], [active.id, ready.id])
        self.assertEqual(len(strategy_calls), 1)

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

    def test_radar_list_handles_200_market_opportunities_without_heavy_providers(self) -> None:
        signals = [
            _signal(
                status="active",
                rr_status="passed",
                symbol=f"COIN{index}USDT",
            )
            for index in range(200)
        ]

        def action_state_provider(_signal: RadarSignal, _user_id: str, _mode: str) -> SignalActionState:
            raise AssertionError("action state should not be used by lightweight radar list")

        def strategy_risk_settings_provider(_signal: RadarSignal, *, user_id: str):
            raise AssertionError("strategy risk settings should not be used by lightweight radar list")

        risk_preview = FakeRiskPreviewEvaluator({})
        service = _service(
            signals,
            risk_preview=risk_preview,
            user_mode="all_market_opportunities",
            action_state_provider=action_state_provider,
            strategy_risk_settings_provider=strategy_risk_settings_provider,
        )

        started_at = time.perf_counter()
        response = service.list_signals(user_id="demo_user", mode="all_market_opportunities")
        duration = time.perf_counter() - started_at

        self.assertEqual(len(response.signals), 200)
        self.assertEqual(response.summary.total_signals, 200)
        self.assertEqual(risk_preview.calls, [])
        self.assertLess(duration, 0.5)


def _service(
    signals: list[RadarSignal],
    *,
    risk_preview: FakeRiskPreviewEvaluator,
    user_mode: str,
    action_state_provider=None,
    strategy_risk_settings_provider=None,
) -> RadarService:
    provider = strategy_risk_settings_provider or (lambda signal, *, user_id: ({}, "not_configured"))
    return RadarService(
        signal_provider=FakeSignalProvider(signals),
        risk_preview_evaluator=risk_preview,
        user_risk_settings_provider=lambda user_id: RiskManagementSettings(radar_display_mode=user_mode),
        strategy_risk_settings_provider=provider,
        action_state_provider=action_state_provider,
    )


def _signal(
    *,
    status: str = "actionable",
    rr_status: str = "passed",
    symbol: str = "BTCUSDT",
    exchange: str = "bybit",
    timeframe: str = "15m",
    direction: str = "long",
    strategy: str = "trend_pullback_continuation",
    score: int = 82,
    execution_gate: SignalExecutionGateSnapshot | None = None,
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=str(uuid4()),
        symbol=symbol,
        exchange=exchange,
        strategy=strategy,
        direction=direction,
        confidence=0.82,
        risk_reward=2.5,
        selected_rr=2.5,
        selected_rr_target="final",
        min_rr_ratio=1.5,
        urgency="medium",
        status=status,
        score=score,
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
        execution_gate=execution_gate,
    )


def _execution_gate(
    *,
    can_show: bool,
    feed_kind: str = "execution_signal",
    status: str = "passed",
) -> SignalExecutionGateSnapshot:
    return SignalExecutionGateSnapshot(
        status=status,
        feed_kind=feed_kind,
        can_notify=can_show,
        can_enter_now=can_show,
        can_arm_pending=can_show,
        can_show_in_execution_feed=can_show,
    )


if __name__ == "__main__":
    unittest.main()
