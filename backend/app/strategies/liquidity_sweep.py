from typing import Any, List, Literal, Mapping, Optional

from app.schemas.market import Features
from app.schemas.signal import SignalScoreBreakdown, StrategySignal
from app.strategies.common import build_signal, has_minimum_market_data, score_breakdown

STRATEGY_NAME = "liquidity_sweep_reversal"
MIN_VISIBLE_SETUP_SCORE = 45


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

    async def evaluate(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> List[StrategySignal]:
        if not has_minimum_market_data(features, min_history=30):
            return []

        setup = self._setup_state(features)
        if setup is None:
            return []
        direction, stage_status, status_reason = setup

        scoring, reasons, risks = self._score(features, direction, stage_status)

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
        if signal.score < MIN_VISIBLE_SETUP_SCORE:
            return []
        return [signal.model_copy(update={"status": stage_status, "status_reason": status_reason})]

    def _direction(self, features: Features) -> Optional[Literal["LONG", "SHORT"]]:
        setup = self._setup_state(features)
        return setup[0] if setup is not None else None

    def _setup_state(
        self,
        features: Features,
    ) -> Optional[tuple[Literal["LONG", "SHORT"], str, str]]:
        atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
        if features.swing_low is not None and features.low < features.swing_low < features.close:
            if features.volume_spike > 1.3 and (features.lower_wick_ratio or 0) >= 0.35:
                return ("LONG", "actionable", "Swept low was reclaimed with volume and absorption wick")
            return ("LONG", "ready", "Swept low was reclaimed; waiting for stronger wick or volume confirmation")
        if features.swing_low is not None and features.low < features.swing_low:
            return ("LONG", "ready", "Previous swing low was swept; waiting for reclaim above the level")
        if features.swing_high is not None and features.high > features.swing_high > features.close:
            if features.volume_spike > 1.3 and (features.upper_wick_ratio or 0) >= 0.35:
                return ("SHORT", "actionable", "Swept high was rejected with volume and rejection wick")
            return ("SHORT", "ready", "Swept high was rejected; waiting for stronger wick or volume confirmation")
        if features.swing_high is not None and features.high > features.swing_high:
            return ("SHORT", "ready", "Previous swing high was swept; waiting for rejection below the level")
        if features.swing_low is not None and 0 <= features.close - features.swing_low <= atr * 0.6:
            return ("LONG", "watchlist", "Price is testing previous swing low; waiting for liquidity sweep and reclaim")
        if features.swing_high is not None and 0 <= features.swing_high - features.close <= atr * 0.6:
            return ("SHORT", "watchlist", "Price is testing previous swing high; waiting for liquidity sweep and rejection")
        return None

    def _score(
        self,
        features: Features,
        direction: Literal["LONG", "SHORT"],
        stage_status: str,
    ) -> tuple[SignalScoreBreakdown, list[str], list[str]]:
        liquidity_score = 0
        volume_score = 0
        orderbook_score = 0
        overheat_penalty = 0
        reasons: list[str] = []
        risks: list[str] = []

        if direction == "LONG":
            if stage_status == "watchlist":
                liquidity_score += 35
                reasons.append("Price is testing the previous swing low")
            else:
                liquidity_score += 35
                reasons.append("Price swept the previous swing low")
                if features.swing_low is not None and features.close > features.swing_low:
                    liquidity_score += 25
                    reasons.append("Close returned above the sweep level")
                else:
                    risks.append("Sweep has not reclaimed the level yet")
                    overheat_penalty += 10
            if (features.lower_wick_ratio or 0) >= 0.35:
                orderbook_score += 20
                reasons.append("Large lower wick shows sellers were absorbed")
            if features.rsi_14 is not None and features.rsi_14 < 25:
                risks.append("RSI below 25: downside momentum may continue")
                overheat_penalty += 10
        else:
            if stage_status == "watchlist":
                liquidity_score += 35
                reasons.append("Price is testing the previous swing high")
            else:
                liquidity_score += 35
                reasons.append("Price swept the previous swing high")
                if features.swing_high is not None and features.close < features.swing_high:
                    liquidity_score += 25
                    reasons.append("Close returned below the sweep level")
                else:
                    risks.append("Sweep has not rejected the level yet")
                    overheat_penalty += 10
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
