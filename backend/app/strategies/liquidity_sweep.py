from typing import List, Literal, Optional

from app.schemas.market import Features
from app.schemas.signal import SignalScoreBreakdown, StrategySignal
from app.strategies.common import (
    WATCHLIST_SCORE,
    build_signal,
    has_minimum_market_data,
    score_breakdown,
)

STRATEGY_NAME = "liquidity_sweep_reversal"


class LiquiditySweepReversalStrategy:
    name = STRATEGY_NAME
    version = "1.0"
    required_data = [
        "swing_high",
        "swing_low",
        "upper_wick_ratio",
        "lower_wick_ratio",
        "volume_spike",
        "rsi_14",
        "atr_14",
    ]

    async def evaluate(self, features: Features) -> List[StrategySignal]:
        if not has_minimum_market_data(features, min_history=30):
            return []

        direction = self._direction(features)
        if direction is None:
            return []

        scoring, reasons, risks = self._score(features, direction)

        atr = features.atr_14 or 0
        if direction == "LONG":
            sweep_level = features.swing_low or features.low
            stop_loss = features.low - atr * 0.3
            take_profit_1 = (features.close + (features.swing_high or features.close)) / 2
            take_profit_2 = features.swing_high
        else:
            sweep_level = features.swing_high or features.high
            stop_loss = features.high + atr * 0.3
            take_profit_1 = (features.close + (features.swing_low or features.close)) / 2
            take_profit_2 = features.swing_low

        reasons.append(f"Sweep level: {sweep_level:.8f}")

        signal = build_signal(
            features=features,
            strategy=self.name,
            direction=direction,
            scoring=scoring,
            reasons=reasons,
            risks=risks,
            entry=features.close,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
        )
        if signal.score < WATCHLIST_SCORE:
            return []
        return [signal]

    def _direction(self, features: Features) -> Optional[Literal["LONG", "SHORT"]]:
        if features.swing_low is not None and features.low < features.swing_low < features.close:
            return "LONG"
        if features.swing_high is not None and features.high > features.swing_high > features.close:
            return "SHORT"
        return None

    def _score(
        self,
        features: Features,
        direction: Literal["LONG", "SHORT"],
    ) -> tuple[SignalScoreBreakdown, list[str], list[str]]:
        liquidity_score = 0
        volume_score = 0
        orderbook_score = 0
        overheat_penalty = 0
        reasons: list[str] = []
        risks: list[str] = []

        if direction == "LONG":
            liquidity_score += 35
            reasons.append("Price swept the previous swing low")
            liquidity_score += 25
            reasons.append("Close returned above the sweep level")
            if (features.lower_wick_ratio or 0) >= 0.35:
                orderbook_score += 20
                reasons.append("Large lower wick shows sellers were absorbed")
            if features.rsi_14 is not None and features.rsi_14 < 25:
                risks.append("RSI below 25: downside momentum may continue")
                overheat_penalty += 10
        else:
            liquidity_score += 35
            reasons.append("Price swept the previous swing high")
            liquidity_score += 25
            reasons.append("Close returned below the sweep level")
            if (features.upper_wick_ratio or 0) >= 0.35:
                orderbook_score += 20
                reasons.append("Large upper wick shows buyers were rejected")
            if features.rsi_14 is not None and features.rsi_14 > 75:
                risks.append("RSI above 75: upside momentum may continue")
                overheat_penalty += 10

        if features.volume_spike > 1.3:
            volume_score += 20
            reasons.append(f"Sweep volume above average: {features.volume_spike:.2f}x")
        else:
            risks.append("Sweep lacks strong volume confirmation")
            overheat_penalty += 10

        return (
            score_breakdown(
                volume_score=volume_score,
                liquidity_score=liquidity_score,
                orderbook_score=orderbook_score,
                overheat_penalty=overheat_penalty,
            ),
            reasons,
            risks,
        )
