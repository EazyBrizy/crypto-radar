from typing import Literal, Optional

from app.schemas.market import Features
from app.schemas.signal import SignalScoreBreakdown, StrategySignal
from app.schemas.trade_plan import TradePlan, build_trade_plan_from_legacy_fields
from app.services.risk_reward_plan import risk_reward_plan_service

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


def risk_reward_score(risk_reward: float) -> int:
    if risk_reward >= 3:
        return 15
    if risk_reward >= 2:
        return 12
    if risk_reward >= 1.5:
        return 8
    if risk_reward >= 1:
        return 5
    return 0


def score_from_breakdown(breakdown: SignalScoreBreakdown) -> int:
    positive = (
        breakdown.trend_score
        + breakdown.volume_score
        + breakdown.liquidity_score
        + breakdown.orderbook_score
        + breakdown.risk_reward_score
        + breakdown.volatility_score
    )
    penalties = breakdown.overheat_penalty + breakdown.news_event_risk_penalty
    return max(0, min(100, positive - penalties))


def score_breakdown(
    *,
    trend_score: int = 0,
    volume_score: int = 0,
    liquidity_score: int = 0,
    orderbook_score: int = 0,
    risk_reward_score: int = 0,
    volatility_score: int = 0,
    overheat_penalty: int = 0,
    news_event_risk_penalty: int = 0,
) -> SignalScoreBreakdown:
    breakdown = SignalScoreBreakdown(
        trend_score=trend_score,
        volume_score=volume_score,
        liquidity_score=liquidity_score,
        orderbook_score=orderbook_score,
        risk_reward_score=risk_reward_score,
        volatility_score=volatility_score,
        overheat_penalty=overheat_penalty,
        news_event_risk_penalty=news_event_risk_penalty,
    )
    return breakdown.model_copy(update={"total": score_from_breakdown(breakdown)})


def legacy_score_breakdown(score: int) -> SignalScoreBreakdown:
    remaining = max(0, min(100, score))
    values: dict[str, int] = {}
    for field, cap in (
        ("trend_score", 25),
        ("volume_score", 20),
        ("liquidity_score", 15),
        ("orderbook_score", 10),
        ("risk_reward_score", 15),
        ("volatility_score", 15),
    ):
        values[field] = min(remaining, cap)
        remaining -= values[field]
    return score_breakdown(**values)


def build_signal(
    features: Features,
    strategy: str,
    direction: Literal["LONG", "SHORT"],
    reasons: list[str],
    risks: Optional[list[str]] = None,
    score: Optional[int] = None,
    scoring: Optional[SignalScoreBreakdown] = None,
    entry: Optional[float] = None,
    stop_loss: Optional[float] = None,
    take_profit_1: Optional[float] = None,
    take_profit_2: Optional[float] = None,
    timeframe: Optional[str] = None,
) -> StrategySignal:
    entry_price = entry if entry is not None else features.close
    atr = features.atr_14 or max(abs(features.close) * 0.002, 1e-8)
    fallback_stop_used = stop_loss is None
    fallback_target_labels: set[str] = set()

    if stop_loss is None:
        if direction == "LONG":
            stop_loss = entry_price - atr * 1.5
        else:
            stop_loss = entry_price + atr * 1.5

    risk = abs(entry_price - stop_loss)
    rr_stop_loss = stop_loss
    if risk == 0:
        risk = max(atr, abs(entry_price) * 0.001, 1e-8)
        rr_stop_loss = entry_price - risk if direction == "LONG" else entry_price + risk

    if take_profit_1 is None:
        take_profit_1 = entry_price + risk if direction == "LONG" else entry_price - risk
        fallback_target_labels.add("TP1")
    if take_profit_2 is None:
        take_profit_2 = (
            entry_price + risk * 2
            if direction == "LONG"
            else entry_price - risk * 2
        )
        fallback_target_labels.add("TP2")

    entry_padding = atr * 0.15
    entry_min = entry_price - entry_padding
    entry_max = entry_price + entry_padding
    first_target_rr = (
        risk_reward_plan_service.calculate_rr(
            entry_price,
            rr_stop_loss,
            take_profit_1,
            direction,
        ).rr_value
        or 0.0
    )
    final_target_rr = (
        risk_reward_plan_service.calculate_rr(
            entry_price,
            rr_stop_loss,
            take_profit_2,
            direction,
        ).rr_value
        or 0.0
    )
    risk_reward = final_target_rr
    if scoring is None:
        scoring = legacy_score_breakdown(score or 0)
    if scoring.risk_reward_score == 0:
        scoring = scoring.model_copy(
            update={"risk_reward_score": risk_reward_score(risk_reward)}
        )
    score = score_from_breakdown(scoring)
    scoring = scoring.model_copy(update={"total": score})

    rounded_entry_min = _round_price(entry_min)
    rounded_entry_max = _round_price(entry_max)
    rounded_stop_loss = _round_price(stop_loss)
    rounded_take_profit_1 = _round_price(take_profit_1)
    rounded_take_profit_2 = _round_price(take_profit_2)
    rounded_risk_reward = round(risk_reward, 2)
    trade_plan = build_trade_plan_from_legacy_fields(
        entry_min=rounded_entry_min,
        entry_max=rounded_entry_max,
        stop_loss=rounded_stop_loss,
        take_profit_1=rounded_take_profit_1,
        take_profit_2=rounded_take_profit_2,
        risk_reward=rounded_risk_reward,
        first_target_rr=round(first_target_rr, 2),
        final_target_rr=rounded_risk_reward,
    )
    trade_plan = _mark_fallback_trade_plan(
        trade_plan,
        fallback_stop_used=fallback_stop_used,
        fallback_target_labels=fallback_target_labels,
    )

    return StrategySignal(
        exchange=features.exchange,
        symbol=features.symbol,
        strategy=strategy,
        direction=direction,
        confidence=confidence_from_score(score),
        timestamp=features.timestamp,
        score=score,
        timeframe=timeframe or features.timeframe,
        candle_state=features.candle_state,
        entry_min=rounded_entry_min,
        entry_max=rounded_entry_max,
        stop_loss=rounded_stop_loss,
        take_profit_1=rounded_take_profit_1,
        take_profit_2=rounded_take_profit_2,
        risk_reward=rounded_risk_reward,
        urgency=urgency_from_score(score),
        explanation=reasons,
        risks=risks or [],
        score_breakdown=scoring,
        trade_plan=trade_plan,
    )


def _mark_fallback_trade_plan(
    trade_plan: TradePlan,
    *,
    fallback_stop_used: bool,
    fallback_target_labels: set[str],
) -> TradePlan:
    if not fallback_stop_used and not fallback_target_labels:
        return trade_plan

    metadata = dict(trade_plan.metadata)
    metadata["fallback_used"] = True
    if fallback_stop_used:
        metadata["fallback_stop_used"] = True
        metadata["fallback_stop_source"] = "atr"
    if fallback_target_labels:
        metadata["fallback_targets_used"] = True
        metadata["fallback_target_source"] = "r_multiple"

    risk_metadata = dict(trade_plan.risk_rules.metadata)
    risk_metadata.update(
        {
            key: value
            for key, value in metadata.items()
            if key.startswith("fallback_")
        }
    )
    risk_rules = trade_plan.risk_rules.model_copy(update={"metadata": risk_metadata})

    targets = []
    for target in trade_plan.targets:
        if target.label not in fallback_target_labels:
            targets.append(target)
            continue
        target_metadata = dict(target.metadata)
        target_metadata.update(
            {
                "fallback_target_used": True,
                "fallback_target_source": "r_multiple",
            }
        )
        targets.append(
            target.model_copy(
                update={
                    "source": "r_multiple_fallback",
                    "metadata": target_metadata,
                }
            )
        )

    invalidation = trade_plan.invalidation
    if invalidation is not None and fallback_stop_used:
        invalidation_metadata = dict(invalidation.metadata)
        invalidation_metadata.update(
            {
                "fallback_used": True,
                "fallback_stop_used": True,
                "fallback_stop_source": "atr",
                "source": "atr_fallback",
            }
        )
        invalidation = invalidation.model_copy(update={"metadata": invalidation_metadata})

    return trade_plan.model_copy(
        update={
            "targets": targets,
            "invalidation": invalidation,
            "risk_rules": risk_rules,
            "metadata": metadata,
        },
        deep=True,
    )


def has_minimum_market_data(features: Features, min_history: int = 50) -> bool:
    return features.history_length >= min_history and features.volume > 0
