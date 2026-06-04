import unittest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.models.signal import SignalOutcome, TradingSignal
from app.services.signal_outcome_service import SignalOutcomeService, _tracking_plan_from_signal
from app.schemas.candle import OHLCVCandle


class SignalOutcomeServiceTest(unittest.TestCase):
    def test_long_entry_touched(self) -> None:
        outcome = _outcome(direction="long")
        service = SignalOutcomeService(tracking_min_score=0)

        service.update_with_closed_candle(outcome, _candle(high=101.2, low=99.4, close=100.5))

        self.assertEqual(outcome.status, "entry_touched")
        self.assertEqual(outcome.outcome, "open")
        self.assertEqual(outcome.bars_to_entry, 1)

    def test_short_entry_touched(self) -> None:
        outcome = _outcome(
            direction="short",
            entry=100,
            stop=102,
            targets=[("TP1", 98, 1), ("TP2", 96, 2)],
        )
        service = SignalOutcomeService(tracking_min_score=0)

        service.update_with_closed_candle(outcome, _candle(high=100.6, low=99.4, close=99.8))

        self.assertEqual(outcome.status, "entry_touched")
        self.assertEqual(outcome.outcome, "open")
        self.assertEqual(outcome.bars_to_entry, 1)

    def test_tp_outcome_closes_with_realized_r(self) -> None:
        outcome = _outcome(direction="long", selected_rr=1, selected_rr_target="nearest")
        service = SignalOutcomeService(tracking_min_score=0)

        service.update_with_closed_candle(outcome, _candle(high=102.2, low=99.6, close=101.8))

        self.assertEqual(outcome.status, "tp1")
        self.assertEqual(outcome.outcome, "win")
        self.assertEqual(float(outcome.realized_r), 1.0)
        self.assertEqual(outcome.bars_to_outcome, 1)

    def test_sl_outcome_closes_with_loss(self) -> None:
        outcome = _outcome(direction="long")
        service = SignalOutcomeService(tracking_min_score=0)

        service.update_with_closed_candle(outcome, _candle(high=100.8, low=97.8, close=98.2))

        self.assertEqual(outcome.status, "stop_loss")
        self.assertEqual(outcome.outcome, "loss")
        self.assertEqual(float(outcome.realized_r), -1.0)

    def test_same_candle_tp_and_sl_uses_conservative_stop_first_by_default(self) -> None:
        outcome = _outcome(direction="long", selected_rr=1, selected_rr_target="nearest")
        service = SignalOutcomeService(tracking_min_score=0)

        service.update_with_closed_candle(outcome, _candle(high=102.4, low=97.6, close=101.0))

        self.assertEqual(outcome.status, "stop_loss")
        self.assertEqual(outcome.outcome, "loss")
        self.assertEqual(float(outcome.realized_r), -1.0)
        self.assertEqual(
            outcome.metadata_["same_candle_ambiguous"]["policy"],
            "conservative_stop_first",
        )
        self.assertEqual(
            outcome.metadata_["same_candle_ambiguous"]["canonical_policy"],
            "conservative_stop_first",
        )

    def test_same_candle_tp_and_sl_target_first_closes_win(self) -> None:
        outcome = _outcome(direction="long", selected_rr=1, selected_rr_target="nearest")
        service = SignalOutcomeService(
            tracking_min_score=0,
            same_candle_resolution="target_first",
        )

        service.update_with_closed_candle(outcome, _candle(high=102.4, low=97.6, close=101.0))

        self.assertEqual(outcome.status, "tp1")
        self.assertEqual(outcome.outcome, "win")
        self.assertEqual(float(outcome.realized_r), 1.0)
        self.assertEqual(
            outcome.metadata_["same_candle_ambiguous"]["canonical_policy"],
            "target_first",
        )

    def test_same_candle_tp_and_sl_intrabar_unknown_stays_open(self) -> None:
        outcome = _outcome(direction="long", selected_rr=1, selected_rr_target="nearest")
        service = SignalOutcomeService(
            tracking_min_score=0,
            same_candle_resolution="intrabar_unknown",
        )

        service.update_with_closed_candle(outcome, _candle(high=102.4, low=97.6, close=101.0))

        self.assertEqual(outcome.status, "entry_touched")
        self.assertEqual(outcome.outcome, "open")
        self.assertEqual(float(outcome.realized_r), 0.0)
        self.assertEqual(
            outcome.metadata_["same_candle_ambiguous"]["canonical_policy"],
            "intrabar_unknown",
        )

    def test_expired_outcome_before_entry(self) -> None:
        close_time = 1_779_796_800_000
        outcome = _outcome(
            direction="long",
            metadata={"expires_at": datetime.fromtimestamp((close_time - 60_000) / 1000, tz=timezone.utc).isoformat()},
        )
        service = SignalOutcomeService(tracking_min_score=0)

        service.update_with_closed_candle(
            outcome,
            _candle(high=95.0, low=94.0, close=94.5, close_time=close_time),
        )

        self.assertEqual(outcome.status, "expired")
        self.assertEqual(outcome.outcome, "expired")
        self.assertEqual(float(outcome.realized_r), 0.0)
        self.assertIsNone(outcome.bars_to_entry)

    def test_mfe_mae_calculation_in_r(self) -> None:
        outcome = _outcome(
            direction="long",
            entry=100,
            stop=95,
            targets=[("TP1", 120, 4)],
            selected_rr=4,
        )
        service = SignalOutcomeService(tracking_min_score=0)

        service.update_with_closed_candle(outcome, _candle(high=110, low=97, close=105))

        self.assertEqual(outcome.status, "entry_touched")
        self.assertAlmostEqual(float(outcome.mfe_r), 2.0)
        self.assertAlmostEqual(float(outcome.mae_r), -0.6)

    def test_invalid_signal_without_targets_does_not_create_tracking_plan(self) -> None:
        signal = _trading_signal(take_profit=[])

        plan = _tracking_plan_from_signal(signal, tracking_min_score=70)

        self.assertIsNone(plan)

    def test_tracking_plan_calculates_target_r_from_rr_helper(self) -> None:
        signal = _trading_signal(take_profit=[102, 104])

        plan = _tracking_plan_from_signal(signal, tracking_min_score=70)

        self.assertIsNotNone(plan)
        targets = plan.targets if plan is not None else []
        self.assertEqual([target.label for target in targets], ["TP1", "TP2"])
        self.assertEqual(
            [target.r_multiple for target in targets],
            [Decimal("1.0"), Decimal("2.0")],
        )


def _outcome(
    *,
    direction: str,
    entry: float = 100,
    stop: float = 98,
    targets: list[tuple[str, float, float]] | None = None,
    selected_rr: float | None = 2,
    selected_rr_target: str | None = "final",
    metadata: dict | None = None,
) -> SignalOutcome:
    now = datetime.now(timezone.utc)
    targets = targets or [("TP1", 102, 1), ("TP2", 104, 2)]
    return SignalOutcome(
        id=uuid4(),
        signal_id=uuid4(),
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        strategy="trend_pullback_continuation",
        direction=direction,
        signal_score=Decimal("82"),
        entry_price=Decimal(str(entry)),
        entry_min=Decimal(str(entry - 0.5)),
        entry_max=Decimal(str(entry + 0.5)),
        stop_loss=Decimal(str(stop)),
        targets=[
            {"label": label, "price": price, "r_multiple": r_multiple}
            for label, price, r_multiple in targets
        ],
        status="tracking",
        outcome="open",
        selected_rr=Decimal(str(selected_rr)) if selected_rr is not None else None,
        realized_r=Decimal("0"),
        mfe_r=Decimal("0"),
        mae_r=Decimal("0"),
        created_at=now,
        updated_at=now,
        metadata_={"selected_rr_target": selected_rr_target, **(metadata or {})},
    )


def _candle(
    *,
    high: float,
    low: float,
    close: float,
    close_time: int = 1_779_796_800_000,
) -> OHLCVCandle:
    return OHLCVCandle(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        open_time=close_time - 900_000,
        close_time=close_time,
        open=100.0,
        high=high,
        low=low,
        close=close,
        volume=100,
        trades=10,
        is_closed=True,
    )


def _trading_signal(take_profit: list[float]) -> TradingSignal:
    now = datetime.now(timezone.utc)
    return TradingSignal(
        id=uuid4(),
        signal_key="test-signal",
        strategy_version_id=uuid4(),
        exchange_id=uuid4(),
        pair_id=uuid4(),
        timeframe="15m",
        direction="long",
        status="actionable",
        confidence=Decimal("0.82"),
        score=Decimal("82"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("98"),
        take_profit=take_profit,
        risk_reward=Decimal("2"),
        detected_at=now,
        expires_at=None,
        features_snapshot={"entry_min": 99.5, "entry_max": 100.5},
        explanation="test",
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
