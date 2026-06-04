from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.schemas.signal import RadarSignal
from app.schemas.trade_plan import TradePlan, TradePlanEntry, TradePlanRiskRules, TradePlanTarget
from app.services.trade_plan_fingerprint import fingerprint_signal_trade_plan

SIGNAL_ID = UUID("9f4f02c2-6721-4e06-95f6-63fc3d72b7c1")


class TradePlanFingerprintTest(unittest.TestCase):
    def test_score_and_volatile_metadata_do_not_change_hash(self) -> None:
        first = _signal(
            score=70,
            confidence=0.7,
            updated_at=datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc),
            trade_plan=_trade_plan(metadata={"updated_at": "2026-06-04T09:00:00Z"}, selected_rr=2.0),
        )
        second = _signal(
            score=95,
            confidence=0.95,
            updated_at=datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc),
            trade_plan=_trade_plan(metadata={"updated_at": "2026-06-04T10:00:00Z"}, selected_rr=3.0),
        )

        self.assertEqual(fingerprint_signal_trade_plan(first).hash, fingerprint_signal_trade_plan(second).hash)

    def test_decimal_and_symbol_normalization_are_stable(self) -> None:
        first = _signal(symbol="BTC/USDT:PERP", entry_min=100.0, entry_max=101.0)
        second = _signal(symbol="BTCUSDT", entry_min=100.00, entry_max=101.00)

        self.assertEqual(fingerprint_signal_trade_plan(first).hash, fingerprint_signal_trade_plan(second).hash)

    def test_entry_stop_and_target_changes_change_hash(self) -> None:
        base_hash = fingerprint_signal_trade_plan(_signal()).hash

        self.assertNotEqual(base_hash, fingerprint_signal_trade_plan(_signal(entry_min=99.0)).hash)
        self.assertNotEqual(base_hash, fingerprint_signal_trade_plan(_signal(stop_loss=94.0)).hash)
        self.assertNotEqual(base_hash, fingerprint_signal_trade_plan(_signal(take_profit_1=111.0)).hash)


def _signal(
    *,
    symbol: str = "BTCUSDT",
    score: int = 82,
    confidence: float = 0.82,
    entry_min: float = 100.0,
    entry_max: float = 101.0,
    stop_loss: float = 95.0,
    take_profit_1: float = 110.0,
    updated_at: datetime | None = None,
    trade_plan: TradePlan | None = None,
) -> RadarSignal:
    now = datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc)
    return RadarSignal(
        id=str(SIGNAL_ID),
        symbol=symbol,
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=confidence,
        risk_reward=2.0,
        status="active",
        score=score,
        timeframe="15m",
        entry_min=entry_min,
        entry_max=entry_max,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        created_at=now,
        updated_at=updated_at or now + timedelta(minutes=1),
        trade_plan=trade_plan,
    )


def _trade_plan(*, metadata: dict[str, object], selected_rr: float) -> TradePlan:
    return TradePlan(
        entry=TradePlanEntry(price=100.5, min_price=100.0, max_price=101.0),
        stop_loss=95.0,
        targets=[TradePlanTarget(label="TP1", price=110.0, action="partial_close", close_percent="50.0")],
        risk_rules=TradePlanRiskRules(selected_rr=selected_rr, metadata=metadata),
        metadata=metadata,
    )


if __name__ == "__main__":
    unittest.main()
