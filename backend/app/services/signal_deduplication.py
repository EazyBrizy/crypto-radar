from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from app.schemas.signal import RadarSignal, StrategySignal

SignalLike: TypeAlias = RadarSignal | StrategySignal
DedupAction: TypeAlias = Literal["keep", "suppress", "replace"]
Rank: TypeAlias = tuple[int, int, int, int, float, int, float, int]

FEED_KIND_PRIORITY = {
    "execution_signal": 3,
    "watchlist": 2,
    "market_idea": 1,
    "blocked": 0,
}
STATUS_PRIORITY = {
    "entry_touched": 8,
    "actionable": 7,
    "confirmed": 6,
    "wait_for_pullback": 5,
    "ready": 4,
    "watchlist": 3,
    "active": 2,
    "new": 1,
}
EDGE_PRIORITY = {
    "positive": 3,
    "unknown": 1,
    "insufficient_sample": 1,
    "negative": 0,
}
TIMEFRAME_PRIORITY = {
    "15m": 6,
    "5m": 5,
    "1h": 4,
    "4h": 3,
    "1m": 2,
    "1d": 1,
}


@dataclass(frozen=True)
class DedupDecision:
    action: DedupAction
    reason: str
    suppressed_by_signal_id: str | None = None
    replaced_signal_ids: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


class SignalDeduplicationService:
    def decide(self, candidate: SignalLike, existing_signals: list[SignalLike]) -> DedupDecision:
        key = dedup_key(candidate)
        candidate_rank = rank_signal(candidate)
        matching = [
            signal
            for signal in existing_signals
            if dedup_key(signal) == key and _signal_id(signal) != _signal_id(candidate)
        ]
        if not matching:
            return DedupDecision(
                action="keep",
                reason="dedup_no_matching_market_direction",
                metadata=_metadata(key, candidate_rank),
            )

        ranked = sorted(
            ((signal, rank_signal(signal)) for signal in matching),
            key=lambda item: item[1],
            reverse=True,
        )
        best_signal, best_rank = ranked[0]
        if best_rank >= candidate_rank:
            return DedupDecision(
                action="suppress",
                reason="dedup_suppressed_by_better_signal",
                suppressed_by_signal_id=_signal_id(best_signal),
                metadata={
                    **_metadata(key, candidate_rank),
                    "suppressed_by_rank": list(best_rank),
                },
            )

        replaced = tuple(_signal_id(signal) for signal, signal_rank in ranked if signal_rank < candidate_rank)
        return DedupDecision(
            action="replace" if replaced else "keep",
            reason="dedup_replaces_weaker_signal" if replaced else "dedup_no_weaker_matching_signal",
            replaced_signal_ids=replaced,
            metadata={
                **_metadata(key, candidate_rank),
                "replaced_ranks": {
                    _signal_id(signal): list(signal_rank)
                    for signal, signal_rank in ranked
                    if signal_rank < candidate_rank
                },
            },
        )


def dedup_key(signal: SignalLike) -> tuple[str, str, str]:
    return (
        str(signal.exchange).strip().lower(),
        _normalize_symbol(str(signal.symbol)),
        str(signal.direction).strip().lower(),
    )


def rank_signal(signal: SignalLike) -> Rank:
    gate = getattr(signal, "execution_gate", None)
    feed_kind = str(getattr(gate, "feed_kind", "") or "").strip().lower()
    can_show = bool(getattr(gate, "can_show_in_execution_feed", False))
    edge = getattr(signal, "edge", None)
    edge_status = str(getattr(edge, "status", "") or "").strip().lower()
    selected_rr = _float_or_zero(getattr(signal, "selected_rr", None))
    if selected_rr <= 0:
        selected_rr = _float_or_zero(getattr(signal, "risk_reward", None))
    return (
        1 if can_show else 0,
        FEED_KIND_PRIORITY.get(feed_kind, 0),
        STATUS_PRIORITY.get(str(signal.status).strip().lower(), 0),
        1 if getattr(signal, "candle_state", None) == "closed" else 0,
        _float_or_zero(getattr(signal, "score", None)),
        EDGE_PRIORITY.get(edge_status, 0),
        selected_rr,
        TIMEFRAME_PRIORITY.get(str(signal.timeframe).strip().lower(), 0),
    )


def _metadata(key: tuple[str, str, str], rank: Rank) -> dict[str, object]:
    return {
        "key": list(key),
        "rank": list(rank),
    }


def _signal_id(signal: SignalLike) -> str:
    return str(getattr(signal, "id", ""))


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().replace("/", "").replace(":PERP", "").upper()


def _float_or_zero(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


signal_deduplication_service = SignalDeduplicationService()
