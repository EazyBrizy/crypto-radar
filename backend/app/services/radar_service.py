from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.schemas.risk import RadarDisplayMode, RiskDecision, RiskPreviewRequest
from app.schemas.signal import RadarResponse, RadarRRStatus, RadarSignal
from app.schemas.user import RiskManagementSettings
from app.services.risk_management import (
    ExecutionProfileResolver,
    execution_profile_resolver,
    get_user_risk_management_settings,
)
from app.services.signal_service import signal_service
from app.services.signal_status import is_execution_actionable_status

logger = logging.getLogger(__name__)


class SignalProvider(Protocol):
    def list_open_signals(self) -> list[RadarSignal]:
        ...


class RiskPreviewEvaluator(Protocol):
    def evaluate(
        self,
        request: RiskPreviewRequest,
        *,
        record_audit: bool = True,
    ) -> RiskDecision:
        ...


@dataclass(frozen=True)
class RadarFilters:
    exchange: str | None = None
    symbol: str | None = None
    timeframe: str | None = None


@dataclass(frozen=True)
class _RadarDisplayResolution:
    mode: RadarDisplayMode
    source: str
    warnings: tuple[str, ...] = ()


class RadarService:
    """Builds the user-facing Radar feed from persisted market opportunities."""

    def __init__(
        self,
        *,
        signal_provider: SignalProvider = signal_service,
        risk_preview_evaluator: RiskPreviewEvaluator | None = None,
        user_risk_settings_provider: Callable[[str], RiskManagementSettings] = get_user_risk_management_settings,
        strategy_risk_settings_provider: Callable[..., tuple[dict[str, Any], str]] | None = None,
        profile_resolver: ExecutionProfileResolver = execution_profile_resolver,
    ) -> None:
        self._signal_provider = signal_provider
        self._risk_preview_evaluator = risk_preview_evaluator
        self._user_risk_settings_provider = user_risk_settings_provider
        self._strategy_risk_settings_provider = strategy_risk_settings_provider
        self._profile_resolver = profile_resolver

    def list_signals(
        self,
        *,
        user_id: str = "demo_user",
        mode: RadarDisplayMode | None = None,
        filters: RadarFilters | None = None,
    ) -> RadarResponse:
        radar_filters = filters or RadarFilters()
        signals = [
            signal
            for signal in self._signal_provider.list_open_signals()
            if _matches_filters(signal, radar_filters)
        ]
        risk_settings, risk_settings_warning = self._load_risk_settings(user_id)
        visible_signals: list[RadarSignal] = []
        for signal in signals:
            resolution = self._resolve_display_mode(
                signal,
                user_id=user_id,
                requested_mode=mode,
                risk_settings=risk_settings,
                risk_settings_warning=risk_settings_warning,
            )
            if resolution.mode == "all_market_opportunities":
                visible_signals.append(
                    _annotated_signal(
                        signal,
                        rr_status=_rr_status(signal),
                        display_reason=_all_market_display_reason(signal, resolution),
                    )
                )
                continue

            if not is_execution_actionable_status(signal.status):
                continue

            decision = self._evaluate_risk_gate(signal, user_id=user_id)
            if decision is None or not decision.can_enter:
                continue
            visible_signals.append(
                _annotated_signal(
                    signal,
                    rr_status=_rr_status(signal),
                    risk_gate_status=decision.status,
                    can_enter=decision.can_enter,
                    display_reason=_execution_ready_display_reason(resolution),
                )
            )
        return RadarResponse(signals=visible_signals)

    def _load_risk_settings(self, user_id: str) -> tuple[RiskManagementSettings, str | None]:
        try:
            return self._user_risk_settings_provider(user_id), None
        except Exception as exc:
            logger.warning(
                "Radar display profile resolution fell back to defaults for user %s: %s",
                user_id,
                exc,
            )
            return RiskManagementSettings(), f"user_risk_settings_unavailable:{exc.__class__.__name__}"

    def _resolve_display_mode(
        self,
        signal: RadarSignal,
        *,
        user_id: str,
        requested_mode: RadarDisplayMode | None,
        risk_settings: RiskManagementSettings,
        risk_settings_warning: str | None,
    ) -> _RadarDisplayResolution:
        strategy_settings, strategy_source = self._strategy_risk_settings(signal, user_id=user_id)
        request_override = (
            {"radar_display_mode": requested_mode}
            if requested_mode is not None
            else None
        )
        warnings = [risk_settings_warning] if risk_settings_warning else []
        try:
            profile = self._profile_resolver.resolve(
                user_risk_settings=risk_settings,
                strategy_execution_settings=strategy_settings,
                request_override=request_override,
                mode="virtual",
                instrument_type=_profile_instrument_type(strategy_settings),
            )
        except Exception as exc:
            logger.warning(
                "Radar display mode resolution failed for signal %s: %s",
                signal.id,
                exc,
            )
            fallback_mode = requested_mode or risk_settings.radar_display_mode or "all_market_opportunities"
            return _RadarDisplayResolution(
                mode=fallback_mode,
                source=f"fallback:{strategy_source}",
                warnings=(*warnings, f"display_profile_resolution_failed:{exc.__class__.__name__}"),
            )
        return _RadarDisplayResolution(
            mode=profile.radar_display_mode,
            source=profile.sources.get("radar_display_mode", "unknown"),
            warnings=(*warnings, *profile.warnings),
        )

    def _strategy_risk_settings(self, signal: RadarSignal, *, user_id: str) -> tuple[dict[str, Any], str]:
        if self._strategy_risk_settings_provider is not None:
            return self._strategy_risk_settings_provider(signal, user_id=user_id)
        from app.services.risk_preview import strategy_risk_settings_for_signal

        return strategy_risk_settings_for_signal(signal, user_id=user_id)

    def _evaluate_risk_gate(self, signal: RadarSignal, *, user_id: str) -> RiskDecision | None:
        try:
            return self._risk_preview().evaluate(
                RiskPreviewRequest(
                    signal_id=signal.id,
                    user_id=user_id,
                ),
                record_audit=False,
            )
        except Exception as exc:
            logger.warning(
                "Radar read-only RiskGate preview failed for signal %s: %s",
                signal.id,
                exc,
            )
            return None

    def _risk_preview(self) -> RiskPreviewEvaluator:
        if self._risk_preview_evaluator is not None:
            return self._risk_preview_evaluator
        from app.services.risk_preview import risk_preview_service

        return risk_preview_service


def _matches_filters(signal: RadarSignal, filters: RadarFilters) -> bool:
    if filters.exchange is not None and signal.exchange.lower() != filters.exchange.strip().lower():
        return False
    if filters.symbol is not None and _normalize_symbol(signal.symbol) != _normalize_symbol(filters.symbol):
        return False
    if filters.timeframe is not None and signal.timeframe != filters.timeframe:
        return False
    return True


def _annotated_signal(
    signal: RadarSignal,
    *,
    rr_status: RadarRRStatus,
    display_reason: str,
    risk_gate_status: str | None = None,
    can_enter: bool | None = None,
) -> RadarSignal:
    return signal.model_copy(
        update={
            "rr_status": rr_status,
            "risk_gate_status": risk_gate_status,
            "can_enter": can_enter,
            "display_reason": display_reason,
        }
    )


def _rr_status(signal: RadarSignal) -> RadarRRStatus:
    for metadata in _rr_metadata_sources(signal):
        value = metadata.get("rr_status")
        if value in {"passed", "warning", "failed", "skipped", "unknown"}:
            return cast(RadarRRStatus, value)
    return "unknown"


def _rr_metadata_sources(signal: RadarSignal) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = []
    if signal.confirmation is not None:
        for check in signal.confirmation.checks:
            if check.name == "risk_reward_guard":
                sources.append(check.metadata)
    if signal.trade_plan is not None:
        sources.append(signal.trade_plan.metadata)
        sources.append(signal.trade_plan.risk_rules.metadata)
    return sources


def _all_market_display_reason(
    signal: RadarSignal,
    resolution: _RadarDisplayResolution,
) -> str:
    reason = (
        f"shown: {resolution.mode} includes open market opportunity "
        f"with status {signal.status}"
    )
    if resolution.warnings:
        return f"{reason}; {'; '.join(resolution.warnings)}"
    return reason


def _execution_ready_display_reason(resolution: _RadarDisplayResolution) -> str:
    reason = "shown: execution_ready RiskGate preview allowed entry"
    if resolution.source:
        reason = f"{reason} ({resolution.source})"
    if resolution.warnings:
        return f"{reason}; {'; '.join(resolution.warnings)}"
    return reason


def _profile_instrument_type(strategy_settings: Mapping[str, Any]) -> str:
    raw_instrument_type = strategy_settings.get("instrument_type")
    if isinstance(raw_instrument_type, str) and raw_instrument_type.strip():
        return raw_instrument_type
    try:
        leverage = float(strategy_settings.get("leverage") or 1)
    except (TypeError, ValueError):
        leverage = 1.0
    return "futures" if leverage > 1 else "spot"


def _normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace(":PERP", "").strip().upper()


radar_service = RadarService()
