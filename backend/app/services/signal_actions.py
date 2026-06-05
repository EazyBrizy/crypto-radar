from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.domain.pending_entry_intent import is_active_pending_entry_intent_status
from app.domain.signal_status import (
    can_signal_enter_now,
    is_terminal_signal_status,
    is_waiting_entry_status,
)
from app.schemas.pending_entry import PendingEntryIntentRead
from app.schemas.risk import ResolvedExecutionProfile, StrategyExecutionSettings, VirtualExecutionProfile
from app.schemas.signal import RadarSignal
from app.schemas.signal_action import (
    SignalActionBlocker,
    SignalActionKind,
    SignalActionMode,
    SignalActionRequest,
    SignalActionResponse,
    SignalActionState,
)
from app.schemas.trade import (
    ManualConfirmRequest,
    ManualDecisionResponse,
    VirtualExecutionReport,
)
from app.schemas.user import RiskManagementSettings
from app.services.exchange_account_snapshot import exchange_account_snapshot_service
from app.services.exchange_connection_service import (
    ENABLE_BYBIT_LIVE_ORDER_PLACEMENT_FALSE_REASON_CODE,
    ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT_FALSE_REASON_CODE,
    ENABLE_LIVE_TRADING_FALSE_REASON_CODE,
    MAINNET_CONNECTION_NOT_EXPLICITLY_ENABLED_REASON_CODE,
    ORDER_PLACEMENT_DISABLED_REASON_CODE,
    ORDER_PLACEMENT_DRY_RUN_REASON_CODE,
    exchange_connection_service,
)
from app.services.execution_service import real_execution_service
from app.services.message_broker import realtime_event_broker
from app.services.pending_entry import pending_entry_intent_service
from app.services.realtime_events import signal_updated_event, trade_activated_event
from app.services.risk_fee_rate import risk_fee_rate_service
from app.services.risk_management import get_user_risk_management_settings
from app.services.risk_market_data import risk_market_data_service
from app.services.signal_service import signal_service
from app.services.virtual_trading import virtual_trading_service
from app.services.virtual_execution_profile import (
    default_virtual_execution_profile,
    fill_policy_for_profile,
    normalize_virtual_execution_profile,
)


class SignalActionUnavailable(ValueError):
    pass


REAL_PENDING_NOT_IMPLEMENTED_REASON_CODE = "REAL_PENDING_NOT_IMPLEMENTED"


@dataclass(frozen=True)
class _ResolvedActionContext:
    request: ManualConfirmRequest
    risk_settings: RiskManagementSettings | None
    execution_profile: ResolvedExecutionProfile | None
    environment: str
    blockers: list[SignalActionBlocker] = field(default_factory=list)
    warnings: list[SignalActionBlocker] = field(default_factory=list)


@dataclass(frozen=True)
class _MarketFeeContext:
    warnings: list[SignalActionBlocker] = field(default_factory=list)
    request_updates: dict[str, Any] = field(default_factory=dict)


class SignalActionService:
    """Backend-owned signal action boundary.

    Frontend action requests describe intent only. This service resolves user,
    virtual/real account context, risk profile, execution profile, market data
    and exchange safety state before it delegates to the existing execution
    services.
    """

    def __init__(
        self,
        *,
        signals: Any = signal_service,
        pending_entries: Any = pending_entry_intent_service,
        virtual_trading: Any = virtual_trading_service,
        real_execution: Any = real_execution_service,
        risk_settings_provider: Any = get_user_risk_management_settings,
        market_data_service: Any = risk_market_data_service,
        fee_rate_service: Any = risk_fee_rate_service,
        exchange_connections: Any = exchange_connection_service,
        account_snapshots: Any = exchange_account_snapshot_service,
        realtime_broker: Any = realtime_event_broker,
        virtual_execution_profile_provider: Any = default_virtual_execution_profile,
    ) -> None:
        self._signals = signals
        self._pending_entries = pending_entries
        self._virtual_trading = virtual_trading
        self._real_execution = real_execution
        self._risk_settings_provider = risk_settings_provider
        self._market_data_service = market_data_service
        self._fee_rate_service = fee_rate_service
        self._exchange_connections = exchange_connections
        self._account_snapshots = account_snapshots
        self._realtime_broker = realtime_broker
        self._virtual_execution_profile_provider = virtual_execution_profile_provider

    def get_action_state(
        self,
        signal_id: str,
        *,
        mode: SignalActionMode = "virtual",
        connection_id: str | None = None,
        user_id: str,
    ) -> SignalActionState:
        signal = self._get_signal_or_raise(signal_id)
        return self.state_for_signal(
            signal,
            mode=mode,
            connection_id=connection_id,
            user_id=user_id,
        )

    def state_for_signal(
        self,
        signal: RadarSignal,
        *,
        mode: SignalActionMode = "virtual",
        connection_id: str | None = None,
        user_id: str,
    ) -> SignalActionState:
        active_intent = self._active_pending_intent(
            signal_id=signal.id,
            user_id=user_id,
            mode=mode,
        )
        context = self._resolve_context(
            signal,
            mode=mode,
            connection_id=connection_id,
            user_id=user_id,
        )

        blockers = list(context.blockers)
        warnings = list(context.warnings)
        can_enter_now = False
        can_arm_pending = False
        can_reconfirm = False
        can_cancel = False

        if is_terminal_signal_status(signal.status):
            blockers.append(
                _blocker(
                    "signal_terminal",
                    f"Signal status {signal.status!r} is terminal.",
                    display_label="Signal is terminal",
                    metadata={"signal_status": signal.status},
                )
            )
        elif active_intent is not None:
            can_cancel = True
            blockers.append(
                _blocker(
                    _pending_entry_blocker_code(active_intent),
                    _pending_entry_blocker_message(active_intent),
                    display_label=_pending_entry_blocker_label(active_intent),
                    metadata={
                        "pending_entry_intent_id": str(active_intent.id),
                        "pending_entry_status": active_intent.status,
                    },
                )
            )
            can_reconfirm = active_intent.status == "requires_reconfirmation"
        elif context.blockers:
            can_enter_now = False
            can_arm_pending = False
        else:
            can_enter_now = can_signal_enter_now(
                signal.status,
                decision=signal.decision,
                can_enter=signal.can_enter,
                mode=mode,
            )
            can_arm_pending = is_waiting_entry_status(signal.status)
            if not can_enter_now and not can_arm_pending:
                blockers.extend(_signal_action_blockers(signal, mode=mode))

        if mode == "real" and can_arm_pending:
            can_arm_pending = False
            blockers.append(
                _blocker(
                    REAL_PENDING_NOT_IMPLEMENTED_REASON_CODE,
                    "Tick-driven real pending entry execution is not implemented.",
                    display_label="Real pending is not implemented",
                )
            )

        primary_action = _primary_action(
            can_enter_now=can_enter_now,
            can_arm_pending=can_arm_pending,
            can_reconfirm=can_reconfirm,
            can_cancel=can_cancel,
        )
        blockers = _dedupe_blockers(blockers)
        warnings = _dedupe_blockers(warnings)
        disabled_reason_code = blockers[0].code if blockers else None
        accepted_snapshot = (
            active_intent.accepted_trade_plan_snapshot
            if active_intent is not None
            else None
        )
        return SignalActionState(
            can_enter_now=can_enter_now,
            can_arm_pending=can_arm_pending,
            can_reconfirm=can_reconfirm,
            can_cancel=can_cancel,
            mode=mode,
            environment=context.environment,
            primary_action=primary_action,
            disabled_reason_code=disabled_reason_code,
            blockers=blockers,
            warnings=warnings,
            accepted_trade_plan_snapshot=accepted_snapshot,
            display_labels=_display_labels(primary_action, disabled_reason_code, blockers),
        )

    async def execute_action(
        self,
        signal_id: str,
        action: SignalActionRequest,
        *,
        user_id: str,
    ) -> SignalActionResponse:
        signal = self._get_signal_or_raise(signal_id)
        return await self._execute_action_for_signal(
            signal,
            kind=action.kind,
            mode=action.mode,
            connection_id=action.connection_id,
            user_id=user_id,
        )

    async def confirm_legacy(
        self,
        signal_id: str,
        request: ManualConfirmRequest,
    ) -> ManualDecisionResponse:
        signal = self._get_signal_or_raise(signal_id)
        mode: SignalActionMode = "real" if request.mode == "real" else "virtual"
        state = self._legacy_state_for_signal(
            signal,
            connection_id=_metadata_connection_id(request),
            request=request,
        )
        if request.auto_enter_on_confirmation and not state.can_enter_now:
            kind: SignalActionKind = "arm_pending_entry"
        else:
            kind = "enter_now"
        response = await self._execute_action_for_signal(
            signal,
            kind=kind,
            mode=mode,
            connection_id=_metadata_connection_id(request),
            user_id=request.user_id,
            legacy_request=request,
        )
        return ManualDecisionResponse(
            signal=response.signal,
            virtual_trade=response.virtual_trade,
            real_execution=response.real_execution,
            real_execution_result=response.real_execution_result,
            pending_entry_intent=response.pending_entry_intent,
            message=response.message,
        )

    def build_backend_confirm_request(
        self,
        signal: RadarSignal,
        *,
        mode: SignalActionMode,
        connection_id: str | None,
        user_id: str,
    ) -> ManualConfirmRequest:
        return _request_from_resolved_context(self._resolve_context(
            signal,
            mode=mode,
            connection_id=connection_id,
            user_id=user_id,
        ))

    async def _execute_action_for_signal(
        self,
        signal: RadarSignal,
        *,
        kind: SignalActionKind,
        mode: SignalActionMode,
        connection_id: str | None,
        user_id: str,
        legacy_request: ManualConfirmRequest | None = None,
    ) -> SignalActionResponse:
        state = (
            self._legacy_state_for_signal(
                signal,
                connection_id=connection_id,
                request=legacy_request,
            )
            if legacy_request is not None
            else self.state_for_signal(
                signal,
                mode=mode,
                connection_id=connection_id,
                user_id=user_id,
            )
        )
        if not _action_allowed(kind, state):
            raise SignalActionUnavailable(_blocked_action_message(kind, state))

        request = legacy_request or _request_from_resolved_context(
            self._resolve_context(
                signal,
                mode=mode,
                connection_id=connection_id,
                user_id=user_id,
            )
        )
        if legacy_request is None:
            request = request.model_copy(
                update={
                    "mode": mode,
                    "user_id": user_id,
                    "auto_enter_on_confirmation": kind != "enter_now",
                    "metadata": {
                        **request.metadata,
                        "source": "signal_action_service",
                        "action_kind": kind,
                        **({"connection_id": connection_id} if connection_id else {}),
                    },
                }
        )

        if kind == "arm_pending_entry":
            arm_workflow = getattr(self._pending_entries, "arm_signal_workflow", None)
            if not callable(arm_workflow):
                raise SignalActionUnavailable("Pending entry service is unavailable.")
            intent = arm_workflow(
                signal_id=signal.id,
                request=request,
            )
            updated_signal = self._signals.get_signal(signal.id) or signal
            await self._publish_signal_update(updated_signal)
            next_state = self.state_for_signal(
                updated_signal,
                mode=mode,
                connection_id=connection_id,
                user_id=user_id,
            )
            return SignalActionResponse(
                state=next_state,
                signal=updated_signal,
                pending_entry_intent=intent,
                message="Pending entry armed; waiting for accepted entry zone",
            )

        if kind == "cancel_pending_entry":
            intent = self._active_pending_intent_or_raise(
                signal_id=signal.id,
                user_id=user_id,
                mode=mode,
            )
            cancelled = self._pending_entries.cancel_intent(
                intent.id,
                user_id=user_id,
                reason="Cancelled by user.",
            )
            updated_signal = self._signals.get_signal(signal.id) or signal
            next_state = self.state_for_signal(
                updated_signal,
                mode=mode,
                connection_id=connection_id,
                user_id=user_id,
            )
            return SignalActionResponse(
                state=next_state,
                signal=updated_signal,
                pending_entry_intent=cancelled,
                message="Pending entry cancelled",
            )

        if kind == "reconfirm_pending_entry":
            intent = self._active_pending_intent_or_raise(
                signal_id=signal.id,
                user_id=user_id,
                mode=mode,
            )
            reconfirmed = self._pending_entries.reconfirm_intent(
                intent.id,
                request=request,
            )
            updated_signal = self._signals.get_signal(signal.id) or signal
            await self._publish_signal_update(updated_signal)
            next_state = self.state_for_signal(
                updated_signal,
                mode=mode,
                connection_id=connection_id,
                user_id=user_id,
            )
            return SignalActionResponse(
                state=next_state,
                signal=updated_signal,
                pending_entry_intent=reconfirmed,
                message="Pending entry reconfirmed",
            )

        if mode == "real":
            real_execution = await self._real_execution.place_order(
                signal,
                request,
                connection_id=connection_id,
            )
            return SignalActionResponse(
                state=state,
                signal=signal,
                real_execution=real_execution,
                real_execution_result=real_execution,
                message=real_execution.message,
            )

        updated_signal, virtual_trade = self._virtual_trading.confirm_signal(signal, request)
        await self._publish_signal_update(updated_signal)
        await self._realtime_broker.publish(trade_activated_event(virtual_trade))
        next_state = self.state_for_signal(
            updated_signal,
            mode=mode,
            connection_id=connection_id,
            user_id=user_id,
        )
        return SignalActionResponse(
            state=next_state,
            signal=updated_signal,
            virtual_trade=virtual_trade,
            message="Virtual trade opened",
        )

    def preview_virtual_execution(
        self,
        signal_id: str,
        *,
        user_id: str,
    ) -> VirtualExecutionReport:
        signal = self._get_signal_or_raise(signal_id)
        request = self.build_backend_confirm_request(
            signal,
            mode="virtual",
            connection_id=None,
            user_id=user_id,
        )
        return self._virtual_trading.preview_virtual_execution(signal, request)

    def _resolve_context(
        self,
        signal: RadarSignal,
        *,
        mode: SignalActionMode,
        connection_id: str | None,
        user_id: str,
    ) -> _ResolvedActionContext:
        environment = "virtual" if mode == "virtual" else "real_unresolved"
        blockers: list[SignalActionBlocker] = []
        warnings: list[SignalActionBlocker] = []
        risk_settings: RiskManagementSettings | None = None
        account_balance = 1.0
        connection_metadata: dict[str, Any] = {}
        max_open_positions = _positive_int_setting(
            settings.virtual_max_open_positions,
            fallback=3,
            code="max_open_positions_unavailable",
            label="Max open positions unavailable",
            blockers=blockers,
        )
        virtual_max_slippage_bps = _non_negative_float_setting(
            settings.virtual_max_slippage_bps,
            fallback=150.0,
            code="max_slippage_profile_unavailable",
            label="Max slippage profile unavailable",
            blockers=blockers,
        )
        virtual_min_fill_ratio = _bounded_float_setting(
            settings.virtual_min_fill_ratio,
            minimum=0.0,
            maximum=1.0,
            fallback=0.25,
            code="fill_ratio_profile_unavailable",
            label="Fill ratio profile unavailable",
            blockers=blockers,
        )

        try:
            risk_settings = self._risk_settings_provider(user_id)
        except Exception as exc:
            blockers.append(
                _blocker(
                    "risk_profile_unavailable",
                    f"Risk profile is unavailable: {exc}",
                    display_label="Risk profile unavailable",
                )
            )

        if mode == "virtual":
            try:
                account = self._virtual_trading.get_virtual_account(user_id)
            except Exception as exc:
                blockers.append(
                    _blocker(
                        "virtual_account_unavailable",
                        f"Virtual account is unavailable: {exc}",
                        display_label="Virtual account unavailable",
                    )
                )
            else:
                account_balance = float(account.equity)
                if account_balance <= 0:
                    blockers.append(
                        _blocker(
                            "virtual_account_depleted",
                            "Virtual account equity must be positive.",
                            display_label="Virtual balance depleted",
                        )
                    )
        else:
            connection = None
            if connection_id is None:
                blockers.append(
                    _blocker(
                        "exchange_connection_required",
                        "Real actions require an exchange connection.",
                        display_label="Exchange connection required",
                    )
                )
            else:
                try:
                    connection = self._exchange_connections.get_connection_for_user(
                        connection_id,
                        user_id=user_id,
                    )
                except PermissionError:
                    blockers.append(
                        _blocker(
                            "exchange_connection_forbidden",
                            "Exchange connection belongs to another user.",
                            display_label="Exchange connection unavailable",
                        )
                    )
                except LookupError as exc:
                    blockers.append(
                        _blocker(
                            "exchange_connection_missing",
                            str(exc),
                            display_label="Exchange connection missing",
                        )
                    )
                except Exception as exc:
                    blockers.append(
                        _blocker(
                            "exchange_connection_unavailable",
                            str(exc),
                            display_label="Exchange connection unavailable",
                        )
                    )
            if connection is not None:
                connection_metadata = {
                    "id": str(connection.id),
                    "exchange_code": connection.exchange_code,
                    "environment": connection.environment,
                    "order_placement_mode": connection.order_placement_mode,
                    "can_place_orders": connection.can_place_orders,
                    "mainnet_explicitly_enabled": connection.mainnet_explicitly_enabled,
                    "safety_blockers": list(connection.safety_blockers),
                }
                environment = connection.environment
                if str(connection.status).strip().lower() not in {"active", "connected"}:
                    blockers.append(
                        _blocker(
                            "exchange_connection_inactive",
                            "Exchange connection is not active.",
                            display_label="Exchange connection inactive",
                        )
                    )
                for blocker_code in _real_connection_action_blockers(connection):
                    blockers.append(
                        _blocker(
                            blocker_code,
                            _real_connection_blocker_message(blocker_code),
                            display_label=_real_connection_blocker_label(blocker_code),
                            metadata={
                                "connection_id": str(connection.id),
                                "environment": connection.environment,
                                "order_placement_mode": connection.order_placement_mode,
                            },
                        )
                    )
                snapshot = self._real_account_snapshot(
                    user_id=user_id,
                    exchange=signal.exchange,
                    connection_id=connection_id,
                )
                if snapshot is not None and snapshot.account_equity is not None:
                    account_balance = float(snapshot.account_equity)
                if snapshot is not None:
                    for warning in snapshot.warnings:
                        warnings.append(
                            _warning(
                                "real_account_snapshot_warning",
                                warning,
                                display_label="Account snapshot warning",
                            )
                        )
            if connection is None:
                blockers.extend(_real_environment_blockers(environment))

        instrument_type = _instrument_type_for_signal(signal, risk_settings)
        leverage = _leverage_for_instrument(instrument_type, risk_settings)
        if risk_settings is not None:
            virtual_max_slippage_bps = min(
                virtual_max_slippage_bps,
                float(risk_settings.max_slippage_bps),
            )
        virtual_execution_profile: VirtualExecutionProfile | None = None
        if mode == "virtual":
            try:
                virtual_execution_profile = normalize_virtual_execution_profile(
                    self._virtual_execution_profile_provider(
                        user_id,
                        risk_settings,
                    )
                )
            except Exception as exc:
                virtual_execution_profile = "realistic"
                blockers.append(
                    _blocker(
                        "virtual_execution_profile_unavailable",
                        f"Virtual execution profile is unavailable: {exc}",
                        display_label="Virtual profile unavailable",
                    )
                )
        execution_settings = StrategyExecutionSettings(
            instrument_type=instrument_type,
            leverage=Decimal(str(leverage)),
        )
        virtual_profile_metadata = (
            {
                "virtual_execution_profile": virtual_execution_profile,
                "virtual_fill_policy": fill_policy_for_profile(virtual_execution_profile),
            }
            if virtual_execution_profile is not None
            else {}
        )
        request = ManualConfirmRequest(
            mode=mode,
            user_id=user_id,
            connection_id=connection_id,
            auto_enter_on_confirmation=False,
            account_balance=max(account_balance, 1.0),
            execution_profile=execution_settings,
            leverage=leverage,
            simulation_mode="auto",
            max_virtual_slippage_bps=virtual_max_slippage_bps,
            allow_partial_fill=settings.virtual_allow_partial_fill,
            min_fill_ratio=virtual_min_fill_ratio,
            max_open_positions=max_open_positions,
            metadata={
                "source": "signal_action_service",
                "backend_owned_execution_context": True,
                "environment": environment,
                **virtual_profile_metadata,
                **({"connection_id": connection_id} if connection_id else {}),
                **({"exchange_connection": connection_metadata} if connection_metadata else {}),
            },
        )

        execution_profile = None
        if risk_settings is not None:
            try:
                execution_profile = self._pending_entries.resolve_execution_profile(
                    signal,
                    request,
                    mode=mode,
                )
                request = request.model_copy(update={"leverage": int(execution_profile.leverage)})
            except Exception as exc:
                blockers.append(
                    _blocker(
                        "execution_profile_unavailable",
                        f"Execution profile is unavailable: {exc}",
                        display_label="Execution profile unavailable",
                    )
                )
        market_fee_context = self._market_and_fee_context(
            signal,
            request,
            mode=mode,
            risk_settings=risk_settings,
            execution_profile=execution_profile,
            virtual_execution_profile=virtual_execution_profile,
        )
        warnings.extend(market_fee_context.warnings)
        if market_fee_context.request_updates:
            request = request.model_copy(update=market_fee_context.request_updates)
        return _ResolvedActionContext(
            request=request,
            risk_settings=risk_settings,
            execution_profile=execution_profile,
            environment=environment,
            blockers=_dedupe_blockers(blockers),
            warnings=_dedupe_blockers(warnings),
        )

    def _legacy_state_for_signal(
        self,
        signal: RadarSignal,
        *,
        connection_id: str | None,
        request: ManualConfirmRequest | None,
    ) -> SignalActionState:
        if request is None:
            raise ValueError("Legacy action state requires ManualConfirmRequest")
        mode: SignalActionMode = "real" if request.mode == "real" else "virtual"
        active_intent = self._active_pending_intent(
            signal_id=signal.id,
            user_id=request.user_id,
            mode=mode,
        )
        blockers: list[SignalActionBlocker] = []
        can_cancel = False
        can_reconfirm = False
        can_enter_now = False
        can_arm_pending = False
        if is_terminal_signal_status(signal.status):
            blockers.append(
                _blocker(
                    "signal_terminal",
                    f"Signal status {signal.status!r} is terminal.",
                    display_label="Signal is terminal",
                )
            )
        elif active_intent is not None:
            can_cancel = True
            can_reconfirm = active_intent.status == "requires_reconfirmation"
            blockers.append(
                _blocker(
                    _pending_entry_blocker_code(active_intent),
                    _pending_entry_blocker_message(active_intent),
                    display_label=_pending_entry_blocker_label(active_intent),
                )
            )
        else:
            can_enter_now = can_signal_enter_now(
                signal.status,
                decision=signal.decision,
                can_enter=signal.can_enter,
                mode=mode,
            )
            can_arm_pending = is_waiting_entry_status(signal.status)
            if not can_enter_now and not can_arm_pending:
                blockers.extend(_signal_action_blockers(signal, mode=mode))
        if mode == "real" and can_arm_pending:
            can_arm_pending = False
            blockers.append(
                _blocker(
                    REAL_PENDING_NOT_IMPLEMENTED_REASON_CODE,
                    "Tick-driven real pending entry execution is not implemented.",
                    display_label="Real pending is not implemented",
                )
            )
        primary_action = _primary_action(
            can_enter_now=can_enter_now,
            can_arm_pending=can_arm_pending,
            can_reconfirm=can_reconfirm,
            can_cancel=can_cancel,
        )
        environment = "virtual" if mode == "virtual" else ("real" if connection_id else "real_unresolved")
        disabled_reason_code = blockers[0].code if blockers else None
        return SignalActionState(
            can_enter_now=can_enter_now,
            can_arm_pending=can_arm_pending,
            can_reconfirm=can_reconfirm,
            can_cancel=can_cancel,
            mode=mode,
            environment=environment,
            primary_action=primary_action,
            disabled_reason_code=disabled_reason_code,
            blockers=blockers,
            accepted_trade_plan_snapshot=(
                active_intent.accepted_trade_plan_snapshot
                if active_intent is not None
                else None
            ),
            display_labels=_display_labels(primary_action, disabled_reason_code, blockers),
        )

    def _market_and_fee_context(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        *,
        mode: SignalActionMode,
        risk_settings: RiskManagementSettings | None,
        execution_profile: ResolvedExecutionProfile | None,
        virtual_execution_profile: VirtualExecutionProfile | None = None,
    ) -> _MarketFeeContext:
        if risk_settings is None or execution_profile is None:
            return _MarketFeeContext()
        if mode == "virtual" and virtual_execution_profile == "deterministic_test":
            return _MarketFeeContext()
        warnings: list[SignalActionBlocker] = []
        request_updates: dict[str, Any] = {}
        try:
            market = self._market_data_service.build_snapshot(
                exchange=signal.exchange,
                symbol=signal.symbol,
                side=signal.direction,
                mode=mode,
                instrument_type=execution_profile.instrument_type,
                fallback_entry_price=_entry_price(signal),
                manual_slippage_bps=request.slippage_bps,
                user_id=request.user_id,
            )
        except Exception as exc:
            warnings.append(
                _warning(
                    "market_data_unavailable",
                    f"Market data snapshot is unavailable: {exc}",
                    display_label="Market data unavailable",
                )
            )
            market = None
        if market is not None:
            for message in market.warnings:
                warnings.append(
                    _warning(
                        "market_data_warning",
                        message,
                        display_label="Market data warning",
                    )
                )
            request_updates["slippage_bps"] = float(market.slippage_bps)

        try:
            fee_rate = self._fee_rate_service.resolve(
                user_id=request.user_id,
                exchange=signal.exchange,
                mode=mode,
                instrument_type=execution_profile.instrument_type,
                symbol=signal.symbol,
                risk_settings=risk_settings,
                requested_fee_rate=request.fee_rate,
            )
        except Exception as exc:
            warnings.append(
                _warning(
                    "fee_profile_unavailable",
                    f"Fee profile is unavailable: {exc}",
                    display_label="Fee profile unavailable",
                )
            )
        else:
            request_updates["fee_rate"] = float(fee_rate.fee_rate)
            for message in fee_rate.warnings:
                warnings.append(
                    _warning(
                        "fee_profile_warning",
                        message,
                        display_label="Fee profile warning",
                    )
                )
        return _MarketFeeContext(warnings=warnings, request_updates=request_updates)

    def _real_account_snapshot(
        self,
        *,
        user_id: str,
        exchange: str,
        connection_id: str | None,
    ) -> Any | None:
        if connection_id is None:
            return None
        try:
            return self._account_snapshots.get_snapshot(
                user_id=user_id,
                exchange=exchange,
                connection_id=UUID(str(connection_id)),
                mode="real",
            )
        except Exception:
            return None

    def _active_pending_intent(
        self,
        *,
        signal_id: str,
        user_id: str,
        mode: SignalActionMode,
    ) -> PendingEntryIntentRead | None:
        try:
            intent = self._pending_entries.get_active_for_signal(
                signal_id=signal_id,
                user_id=user_id,
                mode=mode,
            )
        except Exception:
            return None
        if intent is None:
            return None
        return intent if is_active_pending_entry_intent_status(intent.status) else None

    def _active_pending_intent_or_raise(
        self,
        *,
        signal_id: str,
        user_id: str,
        mode: SignalActionMode,
    ) -> PendingEntryIntentRead:
        intent = self._active_pending_intent(
            signal_id=signal_id,
            user_id=user_id,
            mode=mode,
        )
        if intent is None:
            raise ValueError("Active pending entry intent is not found.")
        return intent

    async def _publish_signal_update(self, signal: RadarSignal) -> None:
        await self._realtime_broker.publish(signal_updated_event(signal))

    def _get_signal_or_raise(self, signal_id: str) -> RadarSignal:
        signal = self._signals.get_signal(signal_id)
        if signal is None:
            raise LookupError("Signal is not found")
        return signal


def _request_from_resolved_context(context: _ResolvedActionContext) -> ManualConfirmRequest:
    if context.blockers:
        raise SignalActionUnavailable(_context_unavailable_message(context.blockers))
    return context.request


def _action_allowed(kind: SignalActionKind, state: SignalActionState) -> bool:
    if kind == "enter_now":
        return state.can_enter_now
    if kind == "arm_pending_entry":
        return state.can_arm_pending
    if kind == "cancel_pending_entry":
        return state.can_cancel
    if kind == "reconfirm_pending_entry":
        return state.can_reconfirm
    return False


def _blocked_action_message(kind: SignalActionKind, state: SignalActionState) -> str:
    reason = state.blockers[0] if state.blockers else None
    label = reason.display_label or reason.message or reason.code if reason is not None else None
    return label or f"Signal action {kind} is not available."


def _context_unavailable_message(blockers: list[SignalActionBlocker]) -> str:
    reason = blockers[0] if blockers else None
    if reason is None:
        return "Signal action context is unavailable."
    return reason.display_label or reason.message or reason.code


def _positive_int_setting(
    value: object,
    *,
    fallback: int,
    code: str,
    label: str,
    blockers: list[SignalActionBlocker],
) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        resolved = fallback
        valid = False
    else:
        valid = resolved >= 1
    if valid:
        return resolved
    blockers.append(
        _blocker(
            code,
            f"{label} must be a positive integer.",
            display_label=label,
            metadata={"configured_value": str(value)},
        )
    )
    return fallback


def _non_negative_float_setting(
    value: object,
    *,
    fallback: float,
    code: str,
    label: str,
    blockers: list[SignalActionBlocker],
) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        resolved = fallback
        valid = False
    else:
        valid = resolved >= 0
    if valid:
        return resolved
    blockers.append(
        _blocker(
            code,
            f"{label} must be non-negative.",
            display_label=label,
            metadata={"configured_value": str(value)},
        )
    )
    return fallback


def _bounded_float_setting(
    value: object,
    *,
    minimum: float,
    maximum: float,
    fallback: float,
    code: str,
    label: str,
    blockers: list[SignalActionBlocker],
) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        resolved = fallback
        valid = False
    else:
        valid = minimum <= resolved <= maximum
    if valid:
        return resolved
    blockers.append(
        _blocker(
            code,
            f"{label} must be between {minimum} and {maximum}.",
            display_label=label,
            metadata={"configured_value": str(value)},
        )
    )
    return fallback


def _signal_action_blockers(signal: RadarSignal, *, mode: SignalActionMode) -> list[SignalActionBlocker]:
    blockers: list[SignalActionBlocker] = []
    if signal.can_enter is False:
        blockers.append(
            _blocker(
                "risk_gate_blocked",
                signal.display_reason or "Risk gate blocks entry right now.",
                display_label=signal.display_reason or "Risk gate blocks entry",
            )
        )
    if signal.decision is not None:
        scoped = [
            reason
            for reason in signal.decision.blockers
            if reason.scope in {"discovery", mode}
        ]
        for reason in scoped:
            blockers.append(
                _blocker(
                    reason.code,
                    reason.message,
                    display_label=reason.message,
                    metadata=reason.metadata,
                )
            )
    if not blockers:
        blockers.append(
            _blocker(
                "signal_not_actionable",
                f"Signal status {signal.status!r} is not available for this action.",
                display_label="Signal is not actionable",
                metadata={"signal_status": signal.status},
            )
        )
    return blockers


def _real_connection_action_blockers(connection: Any) -> list[str]:
    blockers = list(getattr(connection, "safety_blockers", []) or [])
    order_mode = str(getattr(connection, "order_placement_mode", "") or "").strip().lower()
    if order_mode == "dry_run":
        return []
    return [code for code in blockers if code != ORDER_PLACEMENT_DRY_RUN_REASON_CODE]


def _real_connection_blocker_message(code: str) -> str:
    return {
        ORDER_PLACEMENT_DISABLED_REASON_CODE: "Order placement is disabled for this exchange connection.",
        ENABLE_LIVE_TRADING_FALSE_REASON_CODE: "ENABLE_LIVE_TRADING=false blocks live order placement.",
        ENABLE_BYBIT_LIVE_ORDER_PLACEMENT_FALSE_REASON_CODE: (
            "ENABLE_BYBIT_LIVE_ORDER_PLACEMENT=false blocks Bybit live order placement."
        ),
        ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT_FALSE_REASON_CODE: (
            "ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT=false blocks Bybit mainnet order placement."
        ),
        MAINNET_CONNECTION_NOT_EXPLICITLY_ENABLED_REASON_CODE: (
            "Mainnet live order placement requires explicit connection opt-in."
        ),
    }.get(code, code)


def _real_connection_blocker_label(code: str) -> str:
    return {
        ORDER_PLACEMENT_DISABLED_REASON_CODE: "Order placement disabled",
        ENABLE_LIVE_TRADING_FALSE_REASON_CODE: "Live trading disabled",
        ENABLE_BYBIT_LIVE_ORDER_PLACEMENT_FALSE_REASON_CODE: "Bybit live disabled",
        ENABLE_BYBIT_MAINNET_ORDER_PLACEMENT_FALSE_REASON_CODE: "Bybit mainnet disabled",
        MAINNET_CONNECTION_NOT_EXPLICITLY_ENABLED_REASON_CODE: "Mainnet opt-in required",
    }.get(code, "Exchange safety blocker")


def _real_environment_blockers(environment: str) -> list[SignalActionBlocker]:
    if environment != "mainnet":
        return []
    if (
        settings.enable_live_trading
        and settings.enable_bybit_live_order_placement
        and settings.enable_bybit_mainnet_order_placement
    ):
        return []
    return [
        _blocker(
            "mainnet_order_placement_disabled",
            "Mainnet order placement is disabled by backend safety flags.",
            display_label="Mainnet trading disabled",
            metadata={
                "enable_live_trading": settings.enable_live_trading,
                "enable_bybit_live_order_placement": settings.enable_bybit_live_order_placement,
                "enable_bybit_mainnet_order_placement": settings.enable_bybit_mainnet_order_placement,
            },
        )
    ]


def _primary_action(
    *,
    can_enter_now: bool,
    can_arm_pending: bool,
    can_reconfirm: bool,
    can_cancel: bool,
) -> SignalActionKind | None:
    if can_reconfirm:
        return "reconfirm_pending_entry"
    if can_enter_now:
        return "enter_now"
    if can_arm_pending:
        return "arm_pending_entry"
    if can_cancel:
        return "cancel_pending_entry"
    return None


def _display_labels(
    primary_action: SignalActionKind | None,
    disabled_reason_code: str | None,
    blockers: list[SignalActionBlocker],
) -> dict[str, str]:
    labels: dict[str, str] = {}
    if primary_action is not None:
        labels["primary_action"] = {
            "enter_now": "Enter now",
            "arm_pending_entry": "Wait for entry",
            "cancel_pending_entry": "Cancel pending entry",
            "reconfirm_pending_entry": "Reconfirm pending entry",
        }[primary_action]
    if disabled_reason_code is not None:
        blocker = next((item for item in blockers if item.code == disabled_reason_code), None)
        labels["disabled_reason"] = (
            blocker.display_label
            if blocker is not None and blocker.display_label
            else disabled_reason_code
        )
    return labels


def _pending_entry_blocker_code(intent: PendingEntryIntentRead) -> str:
    if intent.status == "requires_reconfirmation":
        return "pending_entry_requires_reconfirmation"
    return "pending_entry_active"


def _pending_entry_blocker_message(intent: PendingEntryIntentRead) -> str:
    if intent.status == "requires_reconfirmation":
        return intent.failure_reason or "Pending entry requires reconfirmation before execution."
    return "Active pending entry already exists for this signal."


def _pending_entry_blocker_label(intent: PendingEntryIntentRead) -> str:
    if intent.status == "requires_reconfirmation":
        return "Pending entry requires reconfirmation"
    return "Pending entry already active"


def _instrument_type_for_signal(
    signal: RadarSignal,
    risk_settings: RiskManagementSettings | None,
) -> str:
    symbol = signal.symbol.upper()
    if ":PERP" in symbol or "PERP" in symbol:
        return "futures"
    if risk_settings is not None and risk_settings.futures_max_leverage > 1:
        return "futures"
    return "spot"


def _leverage_for_instrument(
    instrument_type: str,
    risk_settings: RiskManagementSettings | None,
) -> int:
    if instrument_type != "futures":
        return 1
    if risk_settings is None:
        return 1
    return max(1, int(risk_settings.futures_max_leverage))


def _entry_price(signal: RadarSignal) -> float:
    if signal.entry_min is not None and signal.entry_max is not None:
        return (signal.entry_min + signal.entry_max) / 2
    if signal.entry_min is not None:
        return signal.entry_min
    if signal.entry_max is not None:
        return signal.entry_max
    trade_plan = signal.trade_plan
    if trade_plan is not None:
        for value in (
            trade_plan.entry.price,
            trade_plan.entry.min_price,
            trade_plan.entry.max_price,
        ):
            if value is not None:
                return float(value)
    raise ValueError("Signal action requires an entry price.")


def _metadata_connection_id(request: ManualConfirmRequest) -> str | None:
    value = request.metadata.get("connection_id")
    return str(value) if value else None


def _blocker(
    code: str,
    message: str | None = None,
    *,
    display_label: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SignalActionBlocker:
    return SignalActionBlocker(
        code=code,
        severity="blocker",
        message=message,
        display_label=display_label,
        metadata=metadata or {},
    )


def _warning(
    code: str,
    message: str | None = None,
    *,
    display_label: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SignalActionBlocker:
    return SignalActionBlocker(
        code=code,
        severity="warning",
        message=message,
        display_label=display_label,
        metadata=metadata or {},
    )


def _dedupe_blockers(items: list[SignalActionBlocker]) -> list[SignalActionBlocker]:
    seen: set[tuple[str, str | None]] = set()
    result: list[SignalActionBlocker] = []
    for item in items:
        key = (item.code, item.message)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


signal_action_service = SignalActionService()
