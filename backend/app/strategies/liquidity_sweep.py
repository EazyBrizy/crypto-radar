from typing import List, Literal, Optional

from app.schemas.market import Features
from app.schemas.signal import StrategySignal
from app.strategies.common import WATCHLIST_SCORE, build_signal, has_minimum_market_data

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

        score, reasons, risks = self._score(features, direction)
        if score < WATCHLIST_SCORE:
            return []

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
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
            )
        ]

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
    ) -> tuple[int, list[str], list[str]]:
        score = 0
        reasons: list[str] = []
        risks: list[str] = []

        if direction == "LONG":
            score += 35
            reasons.append("Цена сняла предыдущий swing low")
            score += 25
            reasons.append("Закрытие вернулось выше sweep level")
            if (features.lower_wick_ratio or 0) >= 0.35:
                score += 20
                reasons.append("Нижняя тень крупная: продавцов выкупили")
            if features.rsi_14 is not None and features.rsi_14 < 25:
                risks.append("RSI ниже 25: momentum может продолжить падение")
                score -= 10
        else:
            score += 35
            reasons.append("Цена сняла предыдущий swing high")
            score += 25
            reasons.append("Закрытие вернулось ниже sweep level")
            if (features.upper_wick_ratio or 0) >= 0.35:
                score += 20
                reasons.append("Верхняя тень крупная: покупателей продавили")
            if features.rsi_14 is not None and features.rsi_14 > 75:
                risks.append("RSI выше 75: рост может продолжиться")
                score -= 10

        if features.volume_spike > 1.3:
            score += 20
            reasons.append(f"Объем на sweep выше среднего: {features.volume_spike:.2f}x")
        else:
            risks.append("Нет сильного объемного подтверждения sweep")
            score -= 10

        return max(0, min(100, score)), reasons, risks
