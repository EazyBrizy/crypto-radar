from typing import List, Literal, Optional

from app.schemas.market import Features
from app.schemas.signal import SignalScoreBreakdown, StrategySignal
from app.strategies.common import build_signal, has_minimum_market_data, score_breakdown

STRATEGY_NAME = "volatility_squeeze_breakout"
MIN_VISIBLE_SETUP_SCORE = 45


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

        setup = self._setup_state(features)
        if setup is None:
            return []
        direction, stage_status, status_reason = setup

        scoring, reasons, risks = self._score(features, direction, stage_status)

        entry = features.close
        atr = features.atr_14 or 0
        if direction == "LONG":
            breakout_level = features.donchian_high_20 or entry
            stop_loss = breakout_level - atr
        else:
            breakout_level = features.donchian_low_20 or entry
            stop_loss = breakout_level + atr

        signal = build_signal(
            features=features,
            strategy=self.name,
            direction=direction,
            scoring=scoring,
            reasons=reasons,
            risks=risks,
            entry=entry,
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
        upper = features.donchian_high_20
        lower = features.donchian_low_20
        atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
        if (
            upper is not None
            and features.close > upper
        ):
            if features.volume_spike > 1.5 and features.atr_increasing:
                return (
                    "LONG",
                    "actionable",
                    "Breakout closed above range with volume and ATR expansion",
                )
            return (
                "LONG",
                "ready",
                "Breakout exists, but volume or ATR expansion is not confirmed yet",
            )
        if (
            lower is not None
            and features.close < lower
        ):
            if features.volume_spike > 1.5 and features.atr_increasing:
                return (
                    "SHORT",
                    "actionable",
                    "Breakdown closed below range with volume and ATR expansion",
                )
            return (
                "SHORT",
                "ready",
                "Breakdown exists, but volume or ATR expansion is not confirmed yet",
            )
        if features.bb_width_percentile is None or features.bb_width_percentile >= 20:
            return None
        if upper is not None and 0 <= upper - features.close <= atr * 0.6:
            return (
                "LONG",
                "watchlist",
                "Volatility is compressed and price is near the upper range boundary; waiting for breakout volume",
            )
        if lower is not None and 0 <= features.close - lower <= atr * 0.6:
            return (
                "SHORT",
                "watchlist",
                "Volatility is compressed and price is near the lower range boundary; waiting for breakdown volume",
            )
        return None

    def _score(
        self,
        features: Features,
        direction: Literal["LONG", "SHORT"],
        stage_status: str,
    ) -> tuple[SignalScoreBreakdown, list[str], list[str]]:
        trend_score = 0
        volume_score = 0
        volatility_score = 0
        overheat_penalty = 0
        reasons: list[str] = []
        risks: list[str] = []

        if (
            features.bb_width_percentile is not None
            and features.bb_width_percentile < 20
        ):
            volatility_score += 15
            reasons.append("Волатильность сжата: BB width percentile ниже 20")

        if stage_status == "watchlist":
            trend_score += 20
            reasons.append("Price is near the Donchian boundary, but breakout has not confirmed yet")
        elif direction == "LONG" and features.donchian_high_20 is not None:
            trend_score += 25
            reasons.append("Цена закрылась выше Donchian high 20")
        elif direction == "SHORT" and features.donchian_low_20 is not None:
            trend_score += 25
            reasons.append("Цена закрылась ниже Donchian low 20")

        if features.volume_spike > 1.5:
            volume_score += 20
            reasons.append(f"Объем выше среднего: {features.volume_spike:.2f}x")

        if features.atr_increasing:
            volatility_score += 15
            reasons.append("ATR расширяется после сжатия")

        if direction == "LONG":
            if features.rsi_14 is not None and 55 <= features.rsi_14 <= 70:
                reasons.append(f"RSI {features.rsi_14:.1f}, импульс без перегрева")
            elif features.rsi_14 is not None and features.rsi_14 > 75:
                risks.append("RSI выше 75: риск позднего входа")
                overheat_penalty += 10
        else:
            if features.rsi_14 is not None and 30 <= features.rsi_14 <= 45:
                reasons.append(f"RSI {features.rsi_14:.1f}, шорт-импульс без перегрева")
            elif features.rsi_14 is not None and features.rsi_14 < 25:
                risks.append("RSI ниже 25: риск входа после сильного движения")
                overheat_penalty += 10

        if features.atr_14 is not None and abs(features.close - features.open) > features.atr_14 * 2.5:
            risks.append("Тело текущего движения больше 2.5 ATR")
            overheat_penalty += 15

        return (
            score_breakdown(
                trend_score=trend_score,
                volume_score=volume_score,
                volatility_score=volatility_score,
                overheat_penalty=overheat_penalty,
            ),
            reasons,
            risks,
        )
