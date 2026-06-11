from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models.strategy_execution_eligibility import StrategyExecutionEligibilityProfile


StrategyExecutionEligibilitySource = Literal["historical_backtest", "forward_virtual", "mixed"]


@dataclass(frozen=True)
class StrategyExecutionEligibilityProfileKey:
    strategy_code: str
    exchange: str
    symbol_scope: str
    timeframe: str
    market_regime: str
    score_bucket: str
    direction: str


@dataclass(frozen=True)
class StrategyExecutionEligibilityProfileRecord:
    id: UUID | None
    strategy_code: str
    exchange: str
    symbol_scope: str
    timeframe: str
    market_regime: str
    score_bucket: str
    direction: str
    eligible: bool
    source: StrategyExecutionEligibilitySource
    metrics: dict[str, Any]
    sample_size: int
    expectancy_after_costs_r: float | None
    profit_factor: float | None
    entry_touch_rate: float | None
    no_entry_rate: float | None
    max_drawdown_r: float | None
    run_ids: list[str]
    reason_code: str
    reason: str
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class StrategyExecutionEligibilityProfileUpsert:
    strategy_code: str
    exchange: str
    symbol_scope: str
    timeframe: str
    market_regime: str
    score_bucket: str
    direction: str
    eligible: bool
    source: StrategyExecutionEligibilitySource
    metrics: dict[str, Any] = field(default_factory=dict)
    sample_size: int = 0
    expectancy_after_costs_r: float | None = None
    profit_factor: float | None = None
    entry_touch_rate: float | None = None
    no_entry_rate: float | None = None
    max_drawdown_r: float | None = None
    run_ids: list[str] = field(default_factory=list)
    reason_code: str = "strategy_eligibility_missing"
    reason: str = "No execution edge profile is available for this strategy."
    updated_at: datetime | None = None

    @property
    def key(self) -> StrategyExecutionEligibilityProfileKey:
        return StrategyExecutionEligibilityProfileKey(
            strategy_code=self.strategy_code,
            exchange=self.exchange,
            symbol_scope=self.symbol_scope,
            timeframe=self.timeframe,
            market_regime=self.market_regime,
            score_bucket=self.score_bucket,
            direction=self.direction,
        )


class StrategyExecutionEligibilityProfileRepository:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def get_profile(
        self,
        *,
        strategy_code: str,
        exchange: str,
        symbol_scope: str,
        timeframe: str,
        market_regime: str,
        score_bucket: str,
        direction: str,
    ) -> StrategyExecutionEligibilityProfileRecord | None:
        key = _normalize_key(
            StrategyExecutionEligibilityProfileKey(
                strategy_code=strategy_code,
                exchange=exchange,
                symbol_scope=symbol_scope,
                timeframe=timeframe,
                market_regime=market_regime,
                score_bucket=score_bucket,
                direction=direction,
            )
        )
        with self._session_factory() as session:
            profile = session.scalars(_profile_select(key)).one_or_none()
            return _profile_to_record(profile) if profile is not None else None

    def upsert_profile(
        self,
        profile: StrategyExecutionEligibilityProfileUpsert,
    ) -> StrategyExecutionEligibilityProfileRecord:
        normalized = _normalize_upsert(profile)
        now = normalized.updated_at or datetime.now(timezone.utc)
        with self._session_factory() as session:
            existing = session.scalars(_profile_select(normalized.key)).one_or_none()
            if existing is None:
                existing = StrategyExecutionEligibilityProfile(
                    id=uuid4(),
                    strategy_code=normalized.strategy_code,
                    exchange=normalized.exchange,
                    symbol_scope=normalized.symbol_scope,
                    timeframe=normalized.timeframe,
                    market_regime=normalized.market_regime,
                    score_bucket=normalized.score_bucket,
                    direction=normalized.direction,
                    created_at=now,
                )
                session.add(existing)

            existing.eligible = bool(normalized.eligible)
            existing.source = _merged_source(existing.source, normalized.source)
            existing.metrics = dict(normalized.metrics)
            existing.sample_size = int(normalized.sample_size)
            existing.expectancy_after_costs_r = normalized.expectancy_after_costs_r
            existing.profit_factor = normalized.profit_factor
            existing.entry_touch_rate = normalized.entry_touch_rate
            existing.no_entry_rate = normalized.no_entry_rate
            existing.max_drawdown_r = normalized.max_drawdown_r
            existing.run_ids = _merged_run_ids(existing.run_ids, normalized.run_ids)
            existing.reason_code = normalized.reason_code
            existing.reason = normalized.reason
            existing.updated_at = now
            session.flush()
            record = _profile_to_record(existing)
            session.commit()
            return record


def _profile_select(key: StrategyExecutionEligibilityProfileKey) -> Any:
    return select(StrategyExecutionEligibilityProfile).where(
        StrategyExecutionEligibilityProfile.strategy_code == key.strategy_code,
        StrategyExecutionEligibilityProfile.exchange == key.exchange,
        StrategyExecutionEligibilityProfile.symbol_scope == key.symbol_scope,
        StrategyExecutionEligibilityProfile.timeframe == key.timeframe,
        StrategyExecutionEligibilityProfile.market_regime == key.market_regime,
        StrategyExecutionEligibilityProfile.score_bucket == key.score_bucket,
        StrategyExecutionEligibilityProfile.direction == key.direction,
    )


def _normalize_upsert(
    profile: StrategyExecutionEligibilityProfileUpsert,
) -> StrategyExecutionEligibilityProfileUpsert:
    key = _normalize_key(profile.key)
    return StrategyExecutionEligibilityProfileUpsert(
        strategy_code=key.strategy_code,
        exchange=key.exchange,
        symbol_scope=key.symbol_scope,
        timeframe=key.timeframe,
        market_regime=key.market_regime,
        score_bucket=key.score_bucket,
        direction=key.direction,
        eligible=profile.eligible,
        source=_source(profile.source),
        metrics=dict(profile.metrics),
        sample_size=max(0, int(profile.sample_size or 0)),
        expectancy_after_costs_r=_optional_float(profile.expectancy_after_costs_r),
        profit_factor=_optional_float(profile.profit_factor),
        entry_touch_rate=_optional_float(profile.entry_touch_rate),
        no_entry_rate=_optional_float(profile.no_entry_rate),
        max_drawdown_r=_optional_float(profile.max_drawdown_r),
        run_ids=_dedupe_strings(profile.run_ids),
        reason_code=_text(profile.reason_code, "strategy_eligibility_missing"),
        reason=_text(profile.reason, "No execution edge profile is available for this strategy."),
        updated_at=profile.updated_at,
    )


def _normalize_key(key: StrategyExecutionEligibilityProfileKey) -> StrategyExecutionEligibilityProfileKey:
    return StrategyExecutionEligibilityProfileKey(
        strategy_code=_text(key.strategy_code, "unknown"),
        exchange=_text(key.exchange, "unknown").lower(),
        symbol_scope=_normalize_symbol_scope(key.symbol_scope),
        timeframe=_text(key.timeframe, "unknown"),
        market_regime=_text(key.market_regime, "unknown"),
        score_bucket=_text(key.score_bucket, "unknown"),
        direction="short" if str(key.direction).strip().lower() == "short" else "long",
    )


def _profile_to_record(profile: StrategyExecutionEligibilityProfile) -> StrategyExecutionEligibilityProfileRecord:
    return StrategyExecutionEligibilityProfileRecord(
        id=profile.id,
        strategy_code=profile.strategy_code,
        exchange=profile.exchange,
        symbol_scope=profile.symbol_scope,
        timeframe=profile.timeframe,
        market_regime=profile.market_regime,
        score_bucket=profile.score_bucket,
        direction=profile.direction,
        eligible=profile.eligible,
        source=_source(profile.source),
        metrics=dict(profile.metrics or {}),
        sample_size=int(profile.sample_size or 0),
        expectancy_after_costs_r=_optional_float(profile.expectancy_after_costs_r),
        profit_factor=_optional_float(profile.profit_factor),
        entry_touch_rate=_optional_float(profile.entry_touch_rate),
        no_entry_rate=_optional_float(profile.no_entry_rate),
        max_drawdown_r=_optional_float(profile.max_drawdown_r),
        run_ids=_dedupe_strings(profile.run_ids if isinstance(profile.run_ids, list) else []),
        reason_code=profile.reason_code,
        reason=profile.reason,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _merged_source(
    existing_source: str | None,
    new_source: StrategyExecutionEligibilitySource,
) -> StrategyExecutionEligibilitySource:
    existing = _source(existing_source) if existing_source else None
    if existing is None or existing == new_source:
        return new_source
    return "mixed"


def _source(value: object) -> StrategyExecutionEligibilitySource:
    if value in {"historical_backtest", "forward_virtual", "mixed"}:
        return value  # type: ignore[return-value]
    raise ValueError(f"Unknown strategy execution eligibility source: {value}")


def _merged_run_ids(existing: object, new_values: list[str]) -> list[str]:
    current = existing if isinstance(existing, list) else []
    return _dedupe_strings([*current, *new_values])


def _dedupe_strings(values: list[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def _normalize_symbol_scope(value: object) -> str:
    text = _text(value, "unknown")
    return text.replace("/", "").replace(":PERP", "").upper()


def _text(value: object, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
