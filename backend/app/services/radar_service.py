from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.domain.signal_status import is_execution_candidate_status
from app.schemas.risk import RadarDisplayMode, RiskDecision, RiskPreviewRequest
from app.schemas.signal_action import SignalActionBlocker, SignalActionMode, SignalActionState
from app.schemas.signal import RadarResponse, RadarRRStatus, RadarSignal
from app.schemas.user import RiskManagementSettings
from app.services.risk_management import (
    ExecutionProfileResolver,
    execution_profile_resolver,
    get_user_risk_management_settings,
)
from app.services.signal_service import signal_service
from app.services.signal_views import annotate_signal_views, build_radar_summary

logger = logging.getLogger(__name__)

MAX_RADAR_ACTION_STATE_SIGNALS = 25


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
        action_state_provider: Callable[[RadarSignal, str, SignalActionMode], SignalActionState] | None = None,
        profile_resolver: ExecutionProfileResolver = execution_profile_resolver,
    ) -> None:
        self._signal_provider = signal_provider
        self._risk_preview_evaluator = risk_preview_evaluator
        self._user_risk_settings_provider = user_risk_settings_provider
        self._strategy_risk_settings_provider = strategy_risk_settings_provider
        self._action_state_provider = action_state_provider
        self._profile_resolver = profile_resolver

    def list_signals(
        self,
        *,
        user_id: str = "demo_user",
        mode: RadarDisplayMode | None = None,
        filters: RadarFilters | None = None,
        include_action_state: bool = False,
    ) -> RadarResponse:
        radar_filters = filters or RadarFilters()
        signals = [
            signal
            for signal in self._signal_provider.list_open_signals()
            if _matches_filters(signal, radar_filters)
        ]
        risk_settings, risk_settings_warning = self._load_risk_settings(user_id)
        strategy_settings_by_signal = (
            {}
            if mode is not None
            else self._strategy_risk_settings_by_signal(signals, user_id=user_id)
        )
        visible_signals: list[RadarSignal] = []
        action_state_count = 0
        for signal in signals:
            resolution = self._resolve_display_mode(
                signal,
                user_id=user_id,
                requested_mode=mode,
                risk_settings=risk_settings,
                risk_settings_warning=risk_settings_warning,
                strategy_risk_settings=strategy_settings_by_signal.get(signal.id),
            )
            if resolution.mode == "all_market_opportunities":
                annotated = _annotated_signal(
                    signal,
                    rr_status=_rr_status(signal),
                    display_reason=_all_market_display_reason(signal, resolution),
                )
                with_action_state = _consume_action_state_budget(
                    include_action_state=include_action_state,
                    current_count=action_state_count,
                )
                if with_action_state:
                    action_state_count += 1
                visible_signals.append(
                    self._with_views(
                        annotated,
                        user_id=user_id,
                        mode="virtual",
                        include_action_state=with_action_state,
                    )
                )
                continue

            if not is_execution_candidate_status(signal.status):
                continue

            decision = self._evaluate_risk_gate(signal, user_id=user_id)
            if decision is None or not decision.can_enter:
                continue
            annotated = _annotated_signal(
                signal,
                rr_status=_rr_status(signal),
                risk_gate_status=decision.status,
                can_enter=decision.can_enter,
                display_reason=_execution_ready_display_reason(resolution),
            )
            with_action_state = _consume_action_state_budget(
                include_action_state=include_action_state,
                current_count=action_state_count,
            )
            if with_action_state:
                action_state_count += 1
            visible_signals.append(
                self._with_views(
                    annotated,
                    user_id=user_id,
                    mode="virtual",
                    include_action_state=with_action_state,
                )
            )
        if include_action_state and len(visible_signals) > MAX_RADAR_ACTION_STATE_SIGNALS:
            logger.warning(
                "Radar include_action_state limited to %s signals out of %s visible signals",
                MAX_RADAR_ACTION_STATE_SIGNALS,
                len(visible_signals),
            )
        return RadarResponse(signals=visible_signals, summary=build_radar_summary(visible_signals))

    def _with_views(
        self,
        signal: RadarSignal,
        *,
        user_id: str,
        mode: SignalActionMode,
        include_action_state: bool,
    ) -> RadarSignal:
        action_state = (
            self._action_state(signal, user_id=user_id, mode=mode)
            if include_action_state
            else None
        )
        return annotate_signal_views(signal, action_state=action_state)

    def _action_state(
        self,
        signal: RadarSignal,
        *,
        user_id: str,
        mode: SignalActionMode,
    ) -> SignalActionState:
        provider = self._action_state_provider or _default_action_state_provider
        try:
            return provider(signal, user_id, mode)
        except Exception as exc:
            logger.warning(
                "Radar action state failed for signal %s: %s",
                signal.id,
                exc,
            )
            return SignalActionState(
                mode=mode,
                environment="virtual" if mode == "virtual" else "real_unresolved",
                disabled_reason_code="action_state_unavailable",
                blockers=[
                    SignalActionBlocker(
                        code="action_state_unavailable",
                        severity="blocker",
                        message=f"Signal action state is unavailable: {exc.__class__.__name__}",
                        display_label="Action state unavailable",
                    )
                ],
                display_labels={"disabled_reason": "Action state unavailable"},
            )

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
        strategy_risk_settings: tuple[dict[str, Any], str] | None = None,
    ) -> _RadarDisplayResolution:
        warnings = [risk_settings_warning] if risk_settings_warning else []
        if requested_mode is not None:
            return _RadarDisplayResolution(
                mode=requested_mode,
                source="request_override",
                warnings=tuple(warnings),
            )
        strategy_settings, strategy_source = strategy_risk_settings or ({}, "not_configured")
        try:
            profile = self._profile_resolver.resolve(
                user_risk_settings=risk_settings,
                strategy_execution_settings=strategy_settings,
                request_override=None,
                mode="virtual",
                instrument_type=_profile_instrument_type(strategy_settings),
                strategy=signal.strategy,
            )
        except Exception as exc:
            logger.warning(
                "Radar display mode resolution failed for signal %s: %s",
                signal.id,
                exc,
            )
            fallback_mode = risk_settings.radar_display_mode or "all_market_opportunities"
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

    def _strategy_risk_settings_by_signal(
        self,
        signals: list[RadarSignal],
        *,
        user_id: str,
    ) -> dict[str, tuple[dict[str, Any], str]]:
        if self._strategy_risk_settings_provider is None:
            return _default_strategy_risk_settings_by_signal(signals, user_id=user_id)

        cache: dict[tuple[str, str, str, str], tuple[dict[str, Any], str]] = {}
        result: dict[str, tuple[dict[str, Any], str]] = {}
        for signal in signals:
            key = _strategy_settings_cache_key(signal)
            if key not in cache:
                cache[key] = self._strategy_risk_settings(signal, user_id=user_id)
            result[signal.id] = cache[key]
        return result

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


def _consume_action_state_budget(
    *,
    include_action_state: bool,
    current_count: int,
) -> bool:
    return include_action_state and current_count < MAX_RADAR_ACTION_STATE_SIGNALS


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


def _default_strategy_risk_settings_by_signal(
    signals: list[RadarSignal],
    *,
    user_id: str,
) -> dict[str, tuple[dict[str, Any], str]]:
    try:
        from app.services.strategy_config_service import strategy_config_service

        configs = strategy_config_service.list_configs(user_id=user_id)
    except Exception as exc:
        source = f"unavailable:{exc.__class__.__name__}"
        return {signal.id: ({}, source) for signal in signals}
    return {
        signal.id: _strategy_risk_settings_from_configs(signal, configs)
        for signal in signals
    }


def _strategy_risk_settings_from_configs(
    signal: RadarSignal,
    configs: list[Any],
) -> tuple[dict[str, Any], str]:
    signal_exchange = signal.exchange.strip().lower()
    signal_symbol = signal.symbol.strip().upper()
    for config in configs:
        if getattr(config, "strategy_code", None) != signal.strategy:
            continue
        timeframes = getattr(config, "timeframes", None)
        if timeframes and signal.timeframe not in timeframes:
            continue
        pairs = getattr(config, "pairs", None)
        if pairs:
            config_pairs = {
                (
                    str(getattr(pair, "exchange", "")).strip().lower(),
                    str(getattr(pair, "symbol", "")).strip().upper(),
                )
                for pair in pairs
            }
            if (signal_exchange, signal_symbol) not in config_pairs:
                continue
        else:
            exchanges = getattr(config, "exchanges", None)
            if exchanges and signal_exchange not in {str(exchange).strip().lower() for exchange in exchanges}:
                continue
        return _legacy_strategy_risk_settings(getattr(config, "risk_settings", None)), "strategy_config"
    return {}, "not_configured"


def _legacy_strategy_risk_settings(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    to_legacy_dict = getattr(value, "to_legacy_dict", None)
    if callable(to_legacy_dict):
        result = to_legacy_dict()
        return dict(result) if isinstance(result, Mapping) else {}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        result = model_dump(mode="json")
        return dict(result) if isinstance(result, Mapping) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def _strategy_settings_cache_key(signal: RadarSignal) -> tuple[str, str, str, str]:
    return (
        signal.strategy,
        signal.exchange.strip().lower(),
        signal.symbol.strip().upper(),
        signal.timeframe,
    )


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


def _default_action_state_provider(
    signal: RadarSignal,
    user_id: str,
    mode: SignalActionMode,
) -> SignalActionState:
    from app.services.signal_actions import signal_action_service

    return signal_action_service.state_for_signal(
        signal,
        mode=mode,
        connection_id=None,
        user_id=user_id,
    )


radar_service = RadarService()
