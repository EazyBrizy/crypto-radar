from typing import List, Literal, Optional

from app.schemas.market import Features
from app.schemas.signal import SignalScoreBreakdown, StrategySignal
from app.strategies.common import build_signal, has_minimum_market_data, score_breakdown

STRATEGY_NAME = "trend_pullback_continuation"
MIN_VISIBLE_SETUP_SCORE = 45


class TrendPullbackContinuationStrategy:
    name = STRATEGY_NAME
    version = "1.0"
    required_data = ["ema_20", "ema_50", "ema_200", "rsi_14", "atr_14", "volume_spike"]

    async def evaluate(self, features: Features) -> List[StrategySignal]:
        if not has_minimum_market_data(features, min_history=200):
            return []

        setup = self._setup_state(features)
        if setup is None:
            return []
        direction, stage_status, status_reason = setup

        scoring, reasons, risks = self._score(features, direction)

        atr = features.atr_14 or 0
        if direction == "LONG":
            stop_loss = (features.swing_low or features.close) - atr * 0.5
        else:
            stop_loss = (features.swing_high or features.close) + atr * 0.5

        signal = build_signal(
            features=features,
            strategy=self.name,
            direction=direction,
            scoring=scoring,
            reasons=reasons,
            risks=risks,
            entry=features.close,
            stop_loss=stop_loss,
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
        if (
            features.ema_50 is None
            or features.ema_200 is None
            or features.ema_20 is None
            or features.rsi_14 is None
        ):
            return None

        near_pullback_zone = self._near_pullback_zone(features)
        approaching_pullback_zone = self._approaching_pullback_zone(features)
        long_trend = features.close > features.ema_200 and features.ema_50 > features.ema_200
        short_trend = features.close < features.ema_200 and features.ema_50 < features.ema_200

        if long_trend and approaching_pullback_zone:
            if near_pullback_zone and 45 <= features.rsi_14 <= 60 and features.candle_bullish:
                if features.volume_spike >= 1.1:
                    return ("LONG", "actionable", "Pullback held EMA zone with bullish candle and volume confirmation")
                return ("LONG", "ready", "Pullback held EMA zone; waiting for volume confirmation")
            if near_pullback_zone:
                return ("LONG", "ready", "Price is in the EMA pullback zone; waiting for bullish confirmation")
            return ("LONG", "watchlist", "Uptrend is intact and price is approaching the EMA pullback zone")

        if short_trend and approaching_pullback_zone:
            if near_pullback_zone and 40 <= features.rsi_14 <= 55 and features.candle_bearish:
                if features.volume_spike >= 1.1:
                    return ("SHORT", "actionable", "Pullback rejected EMA zone with bearish candle and volume confirmation")
                return ("SHORT", "ready", "Pullback rejected EMA zone; waiting for volume confirmation")
            if near_pullback_zone:
                return ("SHORT", "ready", "Price is in the EMA pullback zone; waiting for bearish confirmation")
            return ("SHORT", "watchlist", "Downtrend is intact and price is approaching the EMA pullback zone")

        return None

    def _near_pullback_zone(self, features: Features) -> bool:
        atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
        return any(
            ema is not None and abs(features.close - ema) <= atr
            for ema in (features.ema_20, features.ema_50)
        )

    def _approaching_pullback_zone(self, features: Features) -> bool:
        atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
        return any(
            ema is not None and abs(features.close - ema) <= atr * 1.8
            for ema in (features.ema_20, features.ema_50)
        )

    def _score(
        self,
        features: Features,
        direction: Literal["LONG", "SHORT"],
    ) -> tuple[SignalScoreBreakdown, list[str], list[str]]:
        trend_score = 0
        volume_score = 0
        overheat_penalty = 0
        reasons: list[str] = []
        risks: list[str] = []

        if direction == "LONG":
            if features.close > (features.ema_200 or features.close):
                trend_score += 30
                reasons.append("Price is above EMA200: market is in an uptrend")
            if (features.ema_50 or 0) > (features.ema_200 or 0):
                trend_score += 20
                reasons.append("EMA50 is above EMA200: trend is confirmed")
            if features.close > (features.ema_50 or features.close):
                trend_score += 20
                reasons.append("Price held above EMA50 after the pullback")
            if features.rsi_14 is not None and features.rsi_14 > 50:
                trend_score += 15
                reasons.append(f"RSI {features.rsi_14:.1f}: momentum supports long")
        else:
            if features.close < (features.ema_200 or features.close):
                trend_score += 30
                reasons.append("Price is below EMA200: market is in a downtrend")
            if (features.ema_50 or 0) < (features.ema_200 or 0):
                trend_score += 20
                reasons.append("EMA50 is below EMA200: trend is confirmed")
            if features.close < (features.ema_50 or features.close):
                trend_score += 20
                reasons.append("Price held below EMA50 after the pullback")
            if features.rsi_14 is not None and features.rsi_14 < 50:
                trend_score += 15
                reasons.append(f"RSI {features.rsi_14:.1f}: momentum supports short")

        if features.adx_rising:
            trend_score += 15
            reasons.append("ADX proxy is rising: trend strength is increasing")

        if features.volume_spike >= 1.1:
            volume_score += 10
            reasons.append(f"Volume confirms the pullback: {features.volume_spike:.2f}x")
        else:
            risks.append("Volume is weaker than required confirmation")
            overheat_penalty += 10

        return (
            score_breakdown(
                trend_score=trend_score,
                volume_score=volume_score,
                overheat_penalty=overheat_penalty,
            ),
            reasons,
            risks,
        )
