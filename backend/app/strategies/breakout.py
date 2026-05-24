from typing import List, Literal, Optional

from app.schemas.market import Features
from app.schemas.signal import StrategySignal
from app.strategies.common import WATCHLIST_SCORE, build_signal, has_minimum_market_data

STRATEGY_NAME = "volatility_squeeze_breakout"


class VolatilitySqueezeBreakoutStrategy:
    name = STRATEGY_NAME
    version = "1.0"
    required_data = [
        "bb_width_percentile",
        "donchian_high_20",
        "donchian_low_20",
        "volume_spike",
        "atr_14",
        "rsi_14",
    ]

    async def evaluate(self, features: Features) -> List[StrategySignal]:
        if not has_minimum_market_data(features, min_history=60):
            return []

        direction = self._direction(features)
        if direction is None:
            return []

        score, reasons, risks = self._score(features, direction)
        if score < WATCHLIST_SCORE:
            return []

        entry = features.close
        atr = features.atr_14 or 0
        if direction == "LONG":
            breakout_level = features.donchian_high_20 or entry
            stop_loss = breakout_level - atr
        else:
            breakout_level = features.donchian_low_20 or entry
            stop_loss = breakout_level + atr

        return [
            build_signal(
                features=features,
                strategy=self.name,
                direction=direction,
                score=score,
                reasons=reasons,
                risks=risks,
                entry=entry,
                stop_loss=stop_loss,
                timeframe="stream",
            )
        ]

    def _direction(self, features: Features) -> Optional[Literal["LONG", "SHORT"]]:
        if (
            features.donchian_high_20 is not None
            and features.close > features.donchian_high_20
        ):
            return "LONG"
        if (
            features.donchian_low_20 is not None
            and features.close < features.donchian_low_20
        ):
            return "SHORT"
        return None

    def _score(
        self,
        features: Features,
        direction: Literal["LONG", "SHORT"],
    ) -> tuple[int, list[str], list[str]]:
        score = 0
        reasons: list[str] = []
        risks: list[str] = []

        if (
            features.bb_width_percentile is not None
            and features.bb_width_percentile < 20
        ):
            score += 40
            reasons.append("Волатильность сжата: BB width percentile ниже 20")

        if direction == "LONG" and features.donchian_high_20 is not None:
            score += 25
            reasons.append("Цена закрылась выше Donchian high 20")
        if direction == "SHORT" and features.donchian_low_20 is not None:
            score += 25
            reasons.append("Цена закрылась ниже Donchian low 20")

        if features.volume_spike > 1.5:
            score += 20
            reasons.append(f"Объем выше среднего: {features.volume_spike:.2f}x")

        if features.atr_increasing:
            score += 15
            reasons.append("ATR расширяется после сжатия")

        if direction == "LONG":
            if features.rsi_14 is not None and 55 <= features.rsi_14 <= 70:
                reasons.append(f"RSI {features.rsi_14:.1f}, импульс без перегрева")
            elif features.rsi_14 is not None and features.rsi_14 > 75:
                risks.append("RSI выше 75: риск позднего входа")
                score -= 10
        else:
            if features.rsi_14 is not None and 30 <= features.rsi_14 <= 45:
                reasons.append(f"RSI {features.rsi_14:.1f}, шорт-импульс без перегрева")
            elif features.rsi_14 is not None and features.rsi_14 < 25:
                risks.append("RSI ниже 25: риск входа после сильного движения")
                score -= 10

        if features.atr_14 is not None and abs(features.close - features.open) > features.atr_14 * 2.5:
            risks.append("Тело текущего движения больше 2.5 ATR")
            score -= 15

        return max(0, min(100, score)), reasons, risks
