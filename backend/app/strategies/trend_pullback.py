from typing import List, Literal, Optional

from app.schemas.market import Features
from app.schemas.signal import StrategySignal
from app.strategies.common import WATCHLIST_SCORE, build_signal, has_minimum_market_data

STRATEGY_NAME = "trend_pullback_continuation"


class TrendPullbackContinuationStrategy:
    name = STRATEGY_NAME
    version = "1.0"
    required_data = ["ema_20", "ema_50", "ema_200", "rsi_14", "atr_14", "volume_spike"]

    async def evaluate(self, features: Features) -> List[StrategySignal]:
        if not has_minimum_market_data(features, min_history=200):
            return []

        direction = self._direction(features)
        if direction is None:
            return []

        score, reasons, risks = self._score(features, direction)
        if score < WATCHLIST_SCORE:
            return []

        atr = features.atr_14 or 0
        if direction == "LONG":
            stop_loss = (features.swing_low or features.close) - atr * 0.5
        else:
            stop_loss = (features.swing_high or features.close) + atr * 0.5

        return [
            build_signal(
                features=features,
                strategy=self.name,
                direction=direction,
                score=score,
                reasons=reasons,
                risks=risks,
                entry=features.close,
                stop_loss=stop_loss,
            )
        ]

    def _direction(self, features: Features) -> Optional[Literal["LONG", "SHORT"]]:
        if (
            features.ema_50 is None
            or features.ema_200 is None
            or features.ema_20 is None
            or features.rsi_14 is None
        ):
            return None

        near_pullback_zone = self._near_pullback_zone(features)
        if (
            features.close > features.ema_200
            and features.ema_50 > features.ema_200
            and near_pullback_zone
            and 45 <= features.rsi_14 <= 60
            and features.candle_bullish
        ):
            return "LONG"

        if (
            features.close < features.ema_200
            and features.ema_50 < features.ema_200
            and near_pullback_zone
            and 40 <= features.rsi_14 <= 55
            and features.candle_bearish
        ):
            return "SHORT"

        return None

    def _near_pullback_zone(self, features: Features) -> bool:
        atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
        return any(
            ema is not None and abs(features.close - ema) <= atr
            for ema in (features.ema_20, features.ema_50)
        )

    def _score(
        self,
        features: Features,
        direction: Literal["LONG", "SHORT"],
    ) -> tuple[int, list[str], list[str]]:
        score = 0
        reasons: list[str] = []
        risks: list[str] = []

        if direction == "LONG":
            if features.close > (features.ema_200 or features.close):
                score += 30
                reasons.append("Цена выше EMA200: рынок в восходящем режиме")
            if (features.ema_50 or 0) > (features.ema_200 or 0):
                score += 20
                reasons.append("EMA50 выше EMA200: тренд подтвержден")
            if features.close > (features.ema_50 or features.close):
                score += 20
                reasons.append("Цена удержалась выше EMA50 после отката")
            if features.rsi_14 is not None and features.rsi_14 > 50:
                score += 15
                reasons.append(f"RSI {features.rsi_14:.1f}: momentum поддерживает long")
        else:
            if features.close < (features.ema_200 or features.close):
                score += 30
                reasons.append("Цена ниже EMA200: рынок в нисходящем режиме")
            if (features.ema_50 or 0) < (features.ema_200 or 0):
                score += 20
                reasons.append("EMA50 ниже EMA200: тренд подтвержден")
            if features.close < (features.ema_50 or features.close):
                score += 20
                reasons.append("Цена удержалась ниже EMA50 после отката")
            if features.rsi_14 is not None and features.rsi_14 < 50:
                score += 15
                reasons.append(f"RSI {features.rsi_14:.1f}: momentum поддерживает short")

        if features.adx_rising:
            score += 15
            reasons.append("ADX proxy растет: тренд усиливается")

        if features.volume_spike >= 1.1:
            reasons.append(f"Объем подтверждает откат: {features.volume_spike:.2f}x")
        else:
            risks.append("Объем слабее нужного подтверждения")
            score -= 10

        return max(0, min(100, score)), reasons, risks
