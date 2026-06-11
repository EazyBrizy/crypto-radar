from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, Sequence

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models.strategy_testing import StrategyExecutionEligibilityProfile
from app.services.strategy_testing.schemas import StrategyTestCalibrationSource


class StrategyExecutionEligibilityProfileRecord(BaseModel):
    strategy_code: str
    exchange: str
    symbol_scope: str
    timeframe: str
    market_regime: str
    score_bucket: str
    direction: str
    eligible: bool
    source: StrategyTestCalibrationSource
    metrics: dict[str, Any] = Field(default_factory=dict)
    sample_size: int = Field(ge=0)
    expectancy_after_costs_r: float | None = None
    profit_factor: float | None = None
    entry_touch_rate: float | None = None
    no_entry_rate: float | None = None
    max_drawdown_r: float | None = None
    run_ids: list[str] = Field(default_factory=list)
    reason_code: str
    reason: str


class StrategyExecutionEligibilityProfileStore(Protocol):
    def upsert_profiles(
        self,
        profiles: Sequence[StrategyExecutionEligibilityProfileRecord],
    ) -> list[StrategyExecutionEligibilityProfileRecord]:
        ...

    def find_best_profile(
        self,
        *,
        strategy: str,
        exchange: str,
        symbol: str,
        timeframe: str,
        market_regime: str | None,
        score_bucket: str | None,
        direction: str | None,
    ) -> StrategyExecutionEligibilityProfileRecord | None:
        ...


class PostgresStrategyExecutionEligibilityProfileStore:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def upsert_profiles(
        self,
        profiles: Sequence[StrategyExecutionEligibilityProfileRecord],
    ) -> list[StrategyExecutionEligibilityProfileRecord]:
        if not profiles:
            return []
        updated_records: list[StrategyExecutionEligibilityProfileRecord] = []
        with self._session_factory() as session:
            for profile in profiles:
                existing = self._find_exact(session, profile)
                now = datetime.now(timezone.utc)
                if existing is None:
                    row = StrategyExecutionEligibilityProfile(
                        strategy_code=profile.strategy_code,
                        exchange=profile.exchange,
                        symbol_scope=profile.symbol_scope,
                        timeframe=profile.timeframe,
                        market_regime=profile.market_regime,
                        score_bucket=profile.score_bucket,
                        direction=profile.direction,
                        eligible=profile.eligible,
                        source=profile.source,
                        metrics=dict(profile.metrics),
                        sample_size=profile.sample_size,
                        expectancy_after_costs_r=profile.expectancy_after_costs_r,
                        profit_factor=profile.profit_factor,
                        entry_touch_rate=profile.entry_touch_rate,
                        no_entry_rate=profile.no_entry_rate,
                        max_drawdown_r=profile.max_drawdown_r,
                        run_ids=list(profile.run_ids),
                        reason_code=profile.reason_code,
                        reason=profile.reason,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                    session.flush()
                    updated_records.append(_row_to_record(row))
                    continue

                existing.eligible = profile.eligible
                existing.source = _merge_source(existing.source, profile.source)
                existing.metrics = dict(profile.metrics)
                existing.sample_size = profile.sample_size
                existing.expectancy_after_costs_r = profile.expectancy_after_costs_r
                existing.profit_factor = profile.profit_factor
                existing.entry_touch_rate = profile.entry_touch_rate
                existing.no_entry_rate = profile.no_entry_rate
                existing.max_drawdown_r = profile.max_drawdown_r
                existing.run_ids = _merge_run_ids(existing.run_ids, profile.run_ids)
                existing.reason_code = profile.reason_code
                existing.reason = profile.reason
                existing.updated_at = now
                session.flush()
                updated_records.append(_row_to_record(existing))
            session.commit()
        return updated_records

    def find_best_profile(
        self,
        *,
        strategy: str,
        exchange: str,
        symbol: str,
        timeframe: str,
        market_regime: str | None,
        score_bucket: str | None,
        direction: str | None,
    ) -> StrategyExecutionEligibilityProfileRecord | None:
        candidates = _lookup_candidates(
            symbol_scope=_normalize_symbol_scope(symbol),
            market_regime=_normalize_dimension(market_regime),
            score_bucket=_normalize_dimension(score_bucket),
            direction=_normalize_direction(direction),
        )
        with self._session_factory() as session:
            for candidate in candidates:
                row = session.scalars(
                    select(StrategyExecutionEligibilityProfile).where(
                        StrategyExecutionEligibilityProfile.strategy_code == strategy,
                        StrategyExecutionEligibilityProfile.exchange == exchange,
                        StrategyExecutionEligibilityProfile.symbol_scope == candidate["symbol_scope"],
                        StrategyExecutionEligibilityProfile.timeframe == timeframe,
                        StrategyExecutionEligibilityProfile.market_regime == candidate["market_regime"],
                        StrategyExecutionEligibilityProfile.score_bucket == candidate["score_bucket"],
                        StrategyExecutionEligibilityProfile.direction == candidate["direction"],
                    )
                ).first()
                if row is not None:
                    return _row_to_record(row)
        return None

    @staticmethod
    def _find_exact(
        session: Session,
        profile: StrategyExecutionEligibilityProfileRecord,
    ) -> StrategyExecutionEligibilityProfile | None:
        return session.scalars(
            select(StrategyExecutionEligibilityProfile).where(
                StrategyExecutionEligibilityProfile.strategy_code == profile.strategy_code,
                StrategyExecutionEligibilityProfile.exchange == profile.exchange,
                StrategyExecutionEligibilityProfile.symbol_scope == profile.symbol_scope,
                StrategyExecutionEligibilityProfile.timeframe == profile.timeframe,
                StrategyExecutionEligibilityProfile.market_regime == profile.market_regime,
                StrategyExecutionEligibilityProfile.score_bucket == profile.score_bucket,
                StrategyExecutionEligibilityProfile.direction == profile.direction,
            )
        ).first()


def _row_to_record(row: StrategyExecutionEligibilityProfile) -> StrategyExecutionEligibilityProfileRecord:
    return StrategyExecutionEligibilityProfileRecord(
        strategy_code=row.strategy_code,
        exchange=row.exchange,
        symbol_scope=row.symbol_scope,
        timeframe=row.timeframe,
        market_regime=row.market_regime,
        score_bucket=row.score_bucket,
        direction=row.direction,
        eligible=row.eligible,
        source=row.source,  # type: ignore[arg-type]
        metrics=dict(row.metrics or {}),
        sample_size=int(row.sample_size or 0),
        expectancy_after_costs_r=row.expectancy_after_costs_r,
        profit_factor=row.profit_factor,
        entry_touch_rate=row.entry_touch_rate,
        no_entry_rate=row.no_entry_rate,
        max_drawdown_r=row.max_drawdown_r,
        run_ids=[str(value) for value in row.run_ids or []],
        reason_code=row.reason_code,
        reason=row.reason,
    )


def _lookup_candidates(
    *,
    symbol_scope: str,
    market_regime: str,
    score_bucket: str,
    direction: str,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for symbol_value in (symbol_scope, "all"):
        for regime_value in (market_regime, "all", "unknown"):
            for bucket_value in (score_bucket, "all", "unknown"):
                for direction_value in (direction, "all", "unknown"):
                    key = (symbol_value, regime_value, bucket_value, direction_value)
                    if key in seen:
                        continue
                    seen.add(key)
                    result.append(
                        {
                            "symbol_scope": symbol_value,
                            "market_regime": regime_value,
                            "score_bucket": bucket_value,
                            "direction": direction_value,
                        }
                    )
    return result


def _merge_source(existing: str, incoming: StrategyTestCalibrationSource) -> StrategyTestCalibrationSource:
    if existing == incoming:
        return incoming
    return "mixed"


def _merge_run_ids(existing: Sequence[Any], incoming: Sequence[str]) -> list[str]:
    merged: list[str] = []
    for value in [*existing, *incoming]:
        text = str(value)
        if text not in merged:
            merged.append(text)
    return merged


def _normalize_dimension(value: object) -> str:
    text = str(value or "unknown").strip()
    return text or "unknown"


def _normalize_symbol_scope(value: object) -> str:
    return _normalize_dimension(value).replace("/", "").replace(":PERP", "").upper()


def _normalize_direction(value: object) -> str:
    text = str(value or "unknown").strip().lower()
    if text in {"long", "short"}:
        return text
    return text or "unknown"
