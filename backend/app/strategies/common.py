from typing import Literal, Optional

from app.schemas.market import Features
from app.schemas.signal import StrategySignal

ACTIONABLE_SCORE = 70
WATCHLIST_SCORE = 60


def _round_price(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value, 8)


def urgency_from_score(score: int) -> Literal["low", "medium", "high"]:
    if score >= 80:
        return "high"
    if score >= ACTIONABLE_SCORE:
        return "medium"
    return "low"


def confidence_from_score(score: int) -> float:
    return min(1.0, max(0.0, score / 100))


def build_signal(
    features: Features,
    strategy: str,
    direction: Literal["LONG", "SHORT"],
    score: int,
    reasons: list[str],
    risks: Optional[list[str]] = None,
    entry: Optional[float] = None,
    stop_loss: Optional[float] = None,
    take_profit_1: Optional[float] = None,
    take_profit_2: Optional[float] = None,
    timeframe: Optional[str] = None,
) -> StrategySignal:
    entry_price = entry if entry is not None else features.close
    atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)

    if stop_loss is None:
        if direction == "LONG":
            stop_loss = entry_price - atr * 1.5
        else:
            stop_loss = entry_price + atr * 1.5

    risk = abs(entry_price - stop_loss)
    if risk == 0:
        risk = max(atr, abs(entry_price) * 0.001, 1e-8)

    if take_profit_1 is None:
        take_profit_1 = entry_price + risk if direction == "LONG" else entry_price - risk
    if take_profit_2 is None:
        take_profit_2 = (
            entry_price + risk * 2
            if direction == "LONG"
            else entry_price - risk * 2
        )

    entry_padding = atr * 0.15
    entry_min = entry_price - entry_padding
    entry_max = entry_price + entry_padding
    risk_reward = abs(take_profit_2 - entry_price) / risk

    return StrategySignal(
        exchange=features.exchange,
        symbol=features.symbol,
        strategy=strategy,
        direction=direction,
        confidence=confidence_from_score(score),
        timestamp=features.timestamp,
        score=score,
        timeframe=timeframe or features.timeframe,
        entry_min=_round_price(entry_min),
        entry_max=_round_price(entry_max),
        stop_loss=_round_price(stop_loss),
        take_profit_1=_round_price(take_profit_1),
        take_profit_2=_round_price(take_profit_2),
        risk_reward=round(risk_reward, 2),
        urgency=urgency_from_score(score),
        explanation=reasons,
        risks=risks or [],
    )


def has_minimum_market_data(features: Features, min_history: int = 50) -> bool:
    return features.history_length >= min_history and features.volume > 0
