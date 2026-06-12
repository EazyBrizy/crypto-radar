"""Virtual trading application service boundary.

This module owns the simulated-trading write path only: virtual execution
checks, PostgreSQL persistence through the repository, ClickHouse analytics,
and Redis portfolio fanout. It must not place real exchange orders.

Future process split:
- input events: signal.confirm_requested, market.price_tick, virtual_trade.close_requested
- output events: virtual_trade.opened, virtual_trade.updated, virtual_trade.closed
- durable state: PostgreSQL orders/order_fills/positions/portfolio ledger
- analytics/hot side effects: ClickHouse analytics.virtual_trade_events, Redis pubsub:portfolio:{user_id}
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
import math
from typing import Any, Protocol
from typing import Optional
from uuid import uuid4

from app.core.clickhouse_client import get_clickhouse_client
from app.core.redis_client import get_redis_client
from app.domain.signal_status import is_execution_candidate_status
from app.domain.virtual_trade_status import (
    ACTIVE_VIRTUAL_TRADE_STATUSES,
    TERMINAL_VIRTUAL_TRADE_STATUSES,
    is_active_virtual_trade_status,
    is_terminal_virtual_trade_status,
)
from app.repositories.signal_repository import SignalWriteResult
from app.schemas.signal import RadarSignal
from app.schemas.risk import ResolvedExecutionProfile, RiskDecision, VirtualExecutionProfile
from app.schemas.trade import (
    CloseReason,
    CloseVirtualTradeRequest,
    ManualConfirmRequest,
    TradeOrigin,
    TradeJournalEntry,
    VirtualAccount,
    VirtualExecutionReport,
    VirtualMarketSnapshot,
    VirtualTrade,
    VirtualTradeLifecycleEvent,
)
from app.schemas.user import RiskManagementSettings
from app.services.risk_audit import RiskAuditService, risk_audit_service
from app.services.risk_fee_rate import RiskFeeRateService, RiskFeeRateSnapshot, risk_fee_rate_service
from app.services.risk_gate import RiskContextService, RiskGateService
from app.services.risk_management import (
    execution_profile_resolver,
    get_user_risk_management_settings,
    request_risk_override_to_execution_settings,
    resolved_risk_profile_source,
)
from app.services.risk_market_data import (
    RiskMarketDataService,
    RiskMarketDataSnapshot,
    offline_virtual_market_data_snapshot,
    risk_market_data_service,
)
from app.services.risk_state import RiskStateService, risk_state_service
from app.services.signal_risk_reward import ensure_signal_execution_eligible, signal_rr_warning_reason
from app.services.signal_service import ClickHouseSignalAnalyticsWriter, RedisSignalHotStore
from app.services.strategy_config_service import strategy_config_service
from app.services.trade_repository import (
    PostgresVirtualTradeRepository,
    TradeRepository,
    VirtualTradeConfirmationResult,
    VirtualTradePersistenceEvent,
)
from app.services.virtual_trade_lifecycle import (
    arm_virtual_trade_time_stop,
    initialize_virtual_trade_lifecycle,
)
from app.services.position_management import position_management_engine
from app.services.virtual_trading.execution_engine import (
    VirtualExecutionEngine,
    VirtualExecutionRejected,
)
from app.services.virtual_execution_profile import (
    default_virtual_execution_profile,
    fill_policy_for_profile,
    normalize_virtual_execution_profile,
)

logger = logging.getLogger(__name__)
MAX_STORED_TRADES = 500
TEST_FALLBACK_VIRTUAL_STARTING_BALANCE = 100.0
TEST_FALLBACK_VIRTUAL_RISK_PER_TRADE_PERCENT = 10.0
TEST_FALLBACK_VIRTUAL_MIN_RR = 3.0


@dataclass(frozen=True)
class _VirtualEntrySimulation:
    execution: VirtualExecutionReport
    account: VirtualAccount
    side: str
    stop_loss: float


@dataclass(frozen=True)
class _VirtualLifecycleCandle:
    high: float
    low: float
    close: float
    open_time: int | None = None
    close_time: int | None = None


class SignalWriteSideEffect(Protocol):
    def write_event(self, event: dict[str, Any]) -> None:
        ...


class SignalHotSideEffect(Protocol):
    def write_signal(self, result: SignalWriteResult) -> None:
        ...


class RiskSettingsProvider(Protocol):
    def __call__(self, user_id: str) -> RiskManagementSettings:
        ...


class VirtualExecutionProfileProvider(Protocol):
    def __call__(
        self,
        user_id: str,
        risk_settings: RiskManagementSettings | None = None,
    ) -> VirtualExecutionProfile:
        ...


class VirtualTradingService:
    """Coordinates virtual-only trade execution through the configured repository."""

    def __init__(
        self,
        repository: TradeRepository | None = None,
        signal_analytics_writer: SignalWriteSideEffect | None = None,
        signal_hot_store: SignalHotSideEffect | None = None,
        execution_engine: VirtualExecutionEngine | None = None,
        risk_settings_provider: RiskSettingsProvider | None = None,
        risk_context_service: RiskContextService | None = None,
        risk_gate_service: RiskGateService | None = None,
        risk_audit: RiskAuditService | None = None,
        risk_state: RiskStateService | None = None,
        market_data_service: RiskMarketDataService | None = None,
        fee_rate_service: RiskFeeRateService | None = None,
        virtual_execution_profile_provider: VirtualExecutionProfileProvider | None = None,
    ) -> None:
        self._repository = repository or PostgresVirtualTradeRepository()
        self._signal_analytics_writer = signal_analytics_writer or ClickHouseSignalAnalyticsWriter()
        self._signal_hot_store = signal_hot_store or RedisSignalHotStore()
        self._execution_engine = execution_engine or VirtualExecutionEngine()
        self._risk_settings_provider = risk_settings_provider
        self._risk_context_service = risk_context_service or RiskContextService()
        self._risk_gate_service = risk_gate_service or RiskGateService()
        self._risk_audit = risk_audit
        self._risk_state = risk_state
        self._market_data_service = market_data_service or risk_market_data_service
        self._fee_rate_service = fee_rate_service or risk_fee_rate_service
        self._virtual_execution_profile_provider = (
            virtual_execution_profile_provider or default_virtual_execution_profile
        )
        self._trade_by_signal: dict[str, str] = {}
        self._account_balance_by_user: dict[str, float] = {}
        self._realized_pnl_by_user: dict[str, float] = {}
        self._account_stats_by_user: dict[str, dict[str, int]] = {}

    def list_virtual_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[VirtualTrade]:
        if status == "open":
            trades = self._list_active_virtual_trades()
            if signal_id is not None:
                trades = [trade for trade in trades if trade.signal_id == signal_id]
            return sorted(trades, key=lambda trade: trade.opened_at, reverse=True)
        if status == "closed":
            trades_by_id: dict[str, VirtualTrade] = {}
            for terminal_status in TERMINAL_VIRTUAL_TRADE_STATUSES:
                for trade in self._repository.list_virtual_trades(
                    status=terminal_status,
                    signal_id=signal_id,
                ):
                    if is_terminal_virtual_trade_status(trade.status):
                        trades_by_id[trade.id] = trade
            return sorted(trades_by_id.values(), key=lambda trade: trade.opened_at, reverse=True)
        return self._repository.list_virtual_trades(
            status=status,
            signal_id=signal_id,
        )

    def get_virtual_trade(self, trade_id: str) -> Optional[VirtualTrade]:
        return self._repository.get_virtual_trade(trade_id)

    def _list_active_virtual_trades(self) -> list[VirtualTrade]:
        trades_by_id: dict[str, VirtualTrade] = {}
        for status in ACTIVE_VIRTUAL_TRADE_STATUSES:
            for trade in self._repository.list_virtual_trades(status=status):
                if is_active_virtual_trade_status(trade.status):
                    trades_by_id[trade.id] = trade
        return list(trades_by_id.values())

    def list_real_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[TradeJournalEntry]:
        return [
            TradeJournalEntry.model_validate(trade.model_dump())
            for trade in self._repository.list_real_trades(
                status=status,
                signal_id=signal_id,
            )
        ]

    def get_real_trade(self, trade_id: str) -> Optional[TradeJournalEntry]:
        trade = self._repository.get_real_trade(trade_id)
        if trade is None:
            return None
        return TradeJournalEntry.model_validate(trade.model_dump())

    def list_trade_journal(
        self,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[TradeJournalEntry]:
        trades: list[TradeJournalEntry] = []
        if mode in {None, "virtual"}:
            trades.extend(
                TradeJournalEntry.model_validate(trade.model_dump())
                for trade in self.list_virtual_trades(status=status, signal_id=signal_id)
            )
        if mode in {None, "real"}:
            trades.extend(self.list_real_trades(status=status, signal_id=signal_id))
        return sorted(trades, key=lambda trade: trade.opened_at, reverse=True)

    def get_virtual_account(self, user_id: str = "demo_user") -> VirtualAccount:
        repository_account = getattr(self._repository, "get_virtual_account", None)
        if repository_account is not None:
            return self._account_with_risk_settings(repository_account(user_id))

        starting_balance = self._virtual_starting_balance_for_user(user_id)
        balance = self._account_balance_by_user.setdefault(
            user_id,
            starting_balance,
        )
        realized_pnl = self._realized_pnl_by_user.setdefault(user_id, 0.0)
        stats = self._account_stats_by_user.setdefault(
            user_id,
            {
                "closed_trades": 0,
                "wins": 0,
                "losses": 0,
                "breakeven": 0,
            },
        )
        open_trades = [
            trade
            for trade in self._list_active_virtual_trades()
            if trade.user_id == user_id
        ]
        open_realized_pnl = sum(trade.realized_pnl for trade in open_trades)
        unrealized_pnl = sum(
            self._gross_pnl(trade, trade.current_price)
            for trade in open_trades
        )
        updated_at = max(
            (trade.updated_at for trade in open_trades),
            default=datetime.now(timezone.utc),
        )
        account = VirtualAccount(
            user_id=user_id,
            starting_balance=starting_balance,
            balance=balance,
            equity=balance + open_realized_pnl + unrealized_pnl,
            realized_pnl=realized_pnl + open_realized_pnl,
            unrealized_pnl=unrealized_pnl,
            risk_per_trade=TEST_FALLBACK_VIRTUAL_RISK_PER_TRADE_PERCENT,
            risk_reward=TEST_FALLBACK_VIRTUAL_MIN_RR,
            open_positions=len(open_trades),
            closed_trades=stats["closed_trades"],
            wins=stats["wins"],
            losses=stats["losses"],
            breakeven=stats["breakeven"],
            updated_at=updated_at,
        )
        return self._account_with_risk_settings(account)

    def _account_with_risk_settings(self, account: VirtualAccount) -> VirtualAccount:
        settings = self._risk_settings_for_user(account.user_id)
        if settings is None:
            return account
        risk_percent = (
            settings.virtual_risk_per_trade_percent
            if settings.virtual_risk_mode == "custom"
            else settings.risk_per_trade_percent
        )
        risk_amount = max(account.equity, 0.0) * risk_percent / 100
        return account.model_copy(
            update={
                "risk_per_trade": risk_amount,
                "risk_reward": settings.min_rr_ratio,
            }
        )

    def _risk_settings_for_user(self, user_id: str) -> RiskManagementSettings | None:
        if self._risk_settings_provider is None:
            return None
        return self._risk_settings_provider(user_id)

    def _virtual_starting_balance_for_user(self, user_id: str) -> float:
        settings = self._risk_settings_for_user(user_id)
        if settings is not None:
            return settings.virtual_starting_balance
        return TEST_FALLBACK_VIRTUAL_STARTING_BALANCE

    @staticmethod
    def _fallback_risk_settings(request: ManualConfirmRequest) -> RiskManagementSettings:
        # Explicit isolated-test fallback for in-memory callers without a user risk profile.
        return RiskManagementSettings(
            risk_profile="custom",
            risk_per_trade_percent=TEST_FALLBACK_VIRTUAL_RISK_PER_TRADE_PERCENT,
            spot_risk_per_trade_percent=TEST_FALLBACK_VIRTUAL_RISK_PER_TRADE_PERCENT,
            futures_risk_per_trade_percent=TEST_FALLBACK_VIRTUAL_RISK_PER_TRADE_PERCENT,
            min_rr_ratio=TEST_FALLBACK_VIRTUAL_MIN_RR,
            max_daily_loss_percent=50.0,
            max_account_drawdown_percent=90.0,
            max_open_risk_percent=100.0,
            max_symbol_risk_percent=100.0,
            max_strategy_exposure_percent=100.0,
            max_correlated_risk_percent=100.0,
            futures_max_open_risk_percent=100.0,
            include_fees_in_risk=True,
            include_slippage_in_risk=True,
            stop_loss_mode="structure",
        )

    def get_virtual_trade_by_signal(self, signal_id: str) -> Optional[VirtualTrade]:
        trade_id = self._trade_by_signal.get(signal_id)
        if trade_id is not None:
            trade = self.get_virtual_trade(trade_id)
            if trade is not None:
                return trade
        trades = self._repository.list_virtual_trades(signal_id=signal_id)
        return trades[0] if trades else None

    def preview_virtual_execution(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> VirtualExecutionReport:
        return self._simulate_entry_execution(
            signal=signal,
            request=request,
            enforce_position_limit=False,
        ).execution

    def confirm_signal(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> tuple[RadarSignal, VirtualTrade]:
        _ensure_signal_execution_candidate(signal)
        confirm_with_trade = getattr(self._repository, "confirm_signal_with_trade", None)
        existing = self.get_virtual_trade_by_signal(signal.id)
        risk_settings = self._risk_settings_for_user(request.user_id) or self._fallback_risk_settings(request)
        request, risk_settings, execution_profile, _ = self._resolved_execution_profile(
            signal=signal,
            request=request,
            risk_settings=risk_settings,
        )
        if existing is None or signal.status != "confirmed":
            ensure_signal_execution_eligible(
                signal,
                mode="virtual",
                rr_guard_mode=execution_profile.rr_guard_mode,
            )
        if existing is not None and confirm_with_trade is not None and signal.status != "confirmed":
            result: VirtualTradeConfirmationResult = confirm_with_trade(signal.id, request, existing)
            self._trade_by_signal[signal.id] = result.trade.id
            self._after_signal_write(result.signal_result)
            self._after_virtual_trade_events(result.events)
            return result.signal_result.signal, result.trade
        if existing is not None:
            updated_signal = signal.model_copy(
                update={
                    "status": "confirmed",
                    "confirmed_at": datetime.now(timezone.utc),
                    "decision_mode": request.mode,
                    "decision_note": "Пользователь подтвердил сигнал в virtual mode",
                    "confirmed_trade_id": existing.id,
                }
            )
            return updated_signal, existing

        trade = self._build_virtual_trade(signal, request)
        if confirm_with_trade is None:
            persisted_trade = self._repository.save_virtual_trade(trade)
            self._trade_by_signal[signal.id] = persisted_trade.id
            updated_signal = signal.model_copy(
                update={
                    "status": "confirmed",
                    "confirmed_at": datetime.now(timezone.utc),
                    "decision_mode": request.mode,
                    "decision_note": "Пользователь подтвердил сигнал в virtual mode",
                    "confirmed_trade_id": persisted_trade.id,
                }
            )
            return updated_signal, persisted_trade

        result: VirtualTradeConfirmationResult = confirm_with_trade(signal.id, request, trade)
        self._trade_by_signal[signal.id] = result.trade.id
        self._after_signal_write(result.signal_result)
        self._after_virtual_trade_events(result.events)
        return result.signal_result.signal, result.trade

    def open_virtual_trade(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> VirtualTrade:
        existing = self.get_virtual_trade_by_signal(signal.id)
        if existing is not None:
            return existing
        risk_settings = self._risk_settings_for_user(request.user_id) or self._fallback_risk_settings(request)
        request, risk_settings, execution_profile, _ = self._resolved_execution_profile(
            signal=signal,
            request=request,
            risk_settings=risk_settings,
        )
        ensure_signal_execution_eligible(
            signal,
            mode="virtual",
            rr_guard_mode=execution_profile.rr_guard_mode,
        )
        trade = self._build_virtual_trade(signal, request)
        persisted_trade = self._repository.save_virtual_trade(trade)
        self._trade_by_signal[signal.id] = persisted_trade.id
        self._after_virtual_trade_events(self._consume_repository_events())
        self._trim_trades()
        return persisted_trade

    def _build_virtual_trade(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> VirtualTrade:
        open_user_positions = [
            trade
            for trade in self._list_active_virtual_trades()
            if trade.user_id == request.user_id
        ]
        if len(open_user_positions) >= request.max_open_positions:
            raise ValueError("Достигнут лимит открытых виртуальных позиций")

        return self._build_virtual_trade_through_risk_gate(
            signal=signal,
            request=request,
            open_user_positions=open_user_positions,
        )

    def _simulate_entry_execution(
        self,
        *,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        enforce_position_limit: bool,
    ) -> _VirtualEntrySimulation:
        if enforce_position_limit:
            open_user_positions = [
                trade
                for trade in self._list_active_virtual_trades()
                if trade.user_id == request.user_id
            ]
            if len(open_user_positions) >= request.max_open_positions:
                raise ValueError("Maximum open virtual positions limit reached")

        return self._simulate_entry_execution_through_risk_gate(
            signal=signal,
            request=request,
        )

    def _build_virtual_trade_through_risk_gate(
        self,
        *,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        open_user_positions: list[VirtualTrade],
    ) -> VirtualTrade:
        raw_entry = self._entry_price(signal)
        risk_settings = self._risk_settings_for_user(request.user_id) or self._fallback_risk_settings(request)
        request, risk_settings, execution_profile, strategy_risk_settings_source = self._resolved_execution_profile(
            signal=signal,
            request=request,
            risk_settings=risk_settings,
        )
        virtual_execution_profile = self._virtual_execution_profile_for_user(request.user_id, risk_settings)
        risk_settings_for_gate = _risk_settings_for_virtual_execution_profile(
            risk_settings,
            virtual_execution_profile,
        )
        request = _request_with_virtual_execution_profile(
            request,
            virtual_execution_profile,
        )
        risk_profile_source = resolved_risk_profile_source(execution_profile)
        virtual_rr_guard_mode = execution_profile.rr_guard_mode
        rr_warning = (
            None
            if virtual_rr_guard_mode == "off"
            else signal_rr_warning_reason(signal, respect_guard_mode=False)
        )
        market_data = self._risk_market_snapshot(
            signal,
            request,
            raw_entry,
            instrument_type=execution_profile.instrument_type,
            virtual_execution_profile=virtual_execution_profile,
        )
        fee_rate = self._risk_fee_snapshot(
            signal,
            request,
            risk_settings,
            instrument_type=execution_profile.instrument_type,
            virtual_execution_profile=virtual_execution_profile,
        )
        gate_request = request.model_copy(
            update={
                "fee_rate": fee_rate.fee_rate,
                "slippage_bps": market_data.slippage_bps,
                "liquidation_price": request.liquidation_price or market_data.liquidation_price,
            }
        )
        account = self.get_virtual_account(gate_request.user_id)
        if account.equity <= 0:
            raise ValueError("Virtual account balance is depleted")
        reference = self._risk_reference(
            user_id=gate_request.user_id,
            exchange=signal.exchange,
            symbol=signal.symbol,
            side=signal.direction,
            instrument_type=execution_profile.instrument_type,
        )

        raw_decision = self._risk_gate_service.evaluate(
            context=self._risk_context_service.build_virtual_context(
                signal=signal,
                request=gate_request,
                account=account,
                entry_price=market_data.entry_price,
                open_positions=open_user_positions,
                requested_notional=gate_request.size_usd,
                stage="pre_execution",
                exchange_min_order_size=(
                    reference.exchange_min_order_size
                    if reference is not None
                    else None
                ),
                exchange_max_order_size=(
                    reference.exchange_max_order_size
                    if reference is not None
                    else None
                ),
                exchange_min_notional=(
                    reference.exchange_min_notional
                    if reference is not None
                    else None
                ),
                exchange_max_leverage=(
                    reference.exchange_max_leverage
                    if reference is not None
                    else None
                ),
                exchange_rule_status=(
                    reference.exchange_rule_status
                    if reference is not None
                    else "unknown"
                ),
                exchange_rule_age_seconds=(
                    reference.exchange_rule_age_seconds
                    if reference is not None
                    else None
                ),
                exchange_rule_ttl_seconds=(
                    reference.exchange_rule_ttl_seconds
                    if reference is not None
                    else None
                ),
                instrument_rules=(
                    getattr(reference, "exchange_instrument_rules", None)
                    if reference is not None
                    else None
                ),
                **_market_context_kwargs(market_data),
                **_fee_context_kwargs(fee_rate),
                daily_loss_amount=reference.daily_loss_amount if reference is not None else 0.0,
                correlated_open_risk_amount=(
                    reference.correlated_open_risk_amount
                    if reference is not None
                    else 0.0
                ),
                correlation_group=reference.correlation_group if reference is not None else None,
                protection_state=reference.protection_state if reference is not None else "normal",
                protection_reason=reference.protection_reason if reference is not None else None,
                account_drawdown_percent=(
                    reference.account_drawdown_percent
                    if reference is not None
                    else None
                ),
                max_account_drawdown_percent=(
                    reference.max_account_drawdown_percent
                    if reference is not None
                    else 0.0
                ),
                user_mode_multiplier=reference.user_mode_multiplier if reference is not None else 1.0,
                risk_profile_source=risk_profile_source,
                execution_profile_sources=execution_profile.sources,
                execution_profile=execution_profile,
                instrument_type=execution_profile.instrument_type,
            ),
            risk_settings=risk_settings_for_gate,
        )
        if not raw_decision.can_enter:
            self._record_blocked_risk_decision(
                signal,
                gate_request,
                raw_decision,
                execution_profile=execution_profile,
                strategy_risk_settings_source=strategy_risk_settings_source,
            )
            raise ValueError("; ".join(raw_decision.blockers))

        requested_size_usd = gate_request.size_usd or raw_decision.position_sizing.notional
        execution = self._execution_engine.simulate_entry(
            signal=signal,
            request=gate_request,
            reference_price=market_data.entry_price,
            requested_size_usd=requested_size_usd,
            market_data_status=market_data.market_data_status,
            market_data_source=market_data.market_data_source,
            market_data_warnings=market_data.warnings,
            market_spread_bps=market_data.spread_bps,
            orderbook_depth_usd=market_data.orderbook_depth_usd,
            execution_profile=execution_profile,
            entry_spread_limit_bps=_entry_spread_limit_bps(risk_settings),
            allow_low_liquidity=_strategy_allows_low_liquidity(signal, user_id=gate_request.user_id),
            enforce_conservative_rules=virtual_execution_profile == "realistic",
            virtual_execution_profile=virtual_execution_profile,
        )
        execution = self._execution_with_risk_decision(
            execution,
            raw_decision,
            rr_warning=rr_warning,
        )
        if execution.status == "rejected_virtual_execution" or execution.average_price is None:
            raise VirtualExecutionRejected(execution)

        entry_price = execution.average_price
        size_usd = execution.filled_size_usd
        if size_usd <= 0:
            raise VirtualExecutionRejected(execution)

        filled_decision = self._risk_gate_service.evaluate(
            context=self._risk_context_service.build_virtual_context(
                signal=signal,
                request=gate_request,
                account=account,
                entry_price=entry_price,
                open_positions=open_user_positions,
                requested_notional=size_usd,
                stage="post_execution",
                exchange_min_order_size=(
                    reference.exchange_min_order_size
                    if reference is not None
                    else None
                ),
                exchange_max_order_size=(
                    reference.exchange_max_order_size
                    if reference is not None
                    else None
                ),
                exchange_min_notional=(
                    reference.exchange_min_notional
                    if reference is not None
                    else None
                ),
                exchange_max_leverage=(
                    reference.exchange_max_leverage
                    if reference is not None
                    else None
                ),
                exchange_rule_status=(
                    reference.exchange_rule_status
                    if reference is not None
                    else "unknown"
                ),
                exchange_rule_age_seconds=(
                    reference.exchange_rule_age_seconds
                    if reference is not None
                    else None
                ),
                exchange_rule_ttl_seconds=(
                    reference.exchange_rule_ttl_seconds
                    if reference is not None
                    else None
                ),
                instrument_rules=(
                    getattr(reference, "exchange_instrument_rules", None)
                    if reference is not None
                    else None
                ),
                **_market_context_kwargs(market_data),
                **_fee_context_kwargs(fee_rate),
                daily_loss_amount=reference.daily_loss_amount if reference is not None else 0.0,
                correlated_open_risk_amount=(
                    reference.correlated_open_risk_amount
                    if reference is not None
                    else 0.0
                ),
                correlation_group=reference.correlation_group if reference is not None else None,
                protection_state=reference.protection_state if reference is not None else "normal",
                protection_reason=reference.protection_reason if reference is not None else None,
                account_drawdown_percent=(
                    reference.account_drawdown_percent
                    if reference is not None
                    else None
                ),
                max_account_drawdown_percent=(
                    reference.max_account_drawdown_percent
                    if reference is not None
                    else 0.0
                ),
                user_mode_multiplier=reference.user_mode_multiplier if reference is not None else 1.0,
                risk_profile_source=risk_profile_source,
                execution_profile_sources=execution_profile.sources,
                execution_profile=execution_profile,
                instrument_type=execution_profile.instrument_type,
            ),
            risk_settings=risk_settings,
        )
        if not filled_decision.can_enter:
            self._record_blocked_risk_decision(
                signal,
                gate_request,
                filled_decision,
                execution_profile=execution_profile,
                strategy_risk_settings_source=strategy_risk_settings_source,
            )
            raise ValueError("; ".join(filled_decision.blockers))

        execution = self._execution_with_risk_decision(
            execution,
            filled_decision,
            rr_warning=rr_warning,
        )
        quantity = size_usd / entry_price
        now = datetime.now(timezone.utc)
        trade_id = f"vtr_{uuid4().hex[:12]}"
        lifecycle_trace = filled_decision.lifecycle_trace.model_copy(
            update={
                "signal_id": signal.id,
                "virtual_trade_id": trade_id,
            }
        )
        execution = execution.model_copy(update={"lifecycle_trace": lifecycle_trace})
        origin = _trade_origin(
            signal=signal,
            request=gate_request,
            lifecycle_trace=lifecycle_trace,
            virtual_trade_id=trade_id,
        )
        trade = VirtualTrade(
            id=trade_id,
            user_id=gate_request.user_id,
            signal_id=signal.id,
            pending_entry_intent_id=origin.pending_entry_intent_id,
            accepted_trade_plan_hash=origin.accepted_trade_plan_hash,
            trigger_source=origin.trigger_source,
            origin=origin,
            exchange=signal.exchange,
            symbol=signal.symbol,
            strategy=signal.strategy,
            timeframe=signal.timeframe,
            side=signal.direction,
            entry_price=entry_price,
            current_price=entry_price,
            size_usd=size_usd,
            quantity=quantity,
            leverage=request.leverage,
            risk_percent=filled_decision.checked_position_sizing.risk_per_trade_percent,
            risk_amount=filled_decision.checked_position_sizing.risk_amount,
            risk_reward=filled_decision.take_profit_plan.targets[-1].r_multiple,
            stop_loss=filled_decision.stop_loss_plan.stop_loss_price,
            take_profit=[target.price for target in filled_decision.take_profit_plan.targets],
            fees=size_usd * gate_request.fee_rate,
            slippage_bps=execution.entry_slippage_bps,
            simulation_mode=execution.mode,
            execution_status=execution.status,
            requested_size_usd=execution.requested_size_usd,
            filled_size_usd=execution.filled_size_usd,
            unfilled_size_usd=execution.unfilled_size_usd,
            execution=execution,
            opened_at=now,
            updated_at=now,
            lifecycle_trace=lifecycle_trace,
        )
        trade = initialize_virtual_trade_lifecycle(trade)
        trade = _append_created_from_pending_entry_event(trade, gate_request, now)
        return arm_virtual_trade_time_stop(
            trade,
            _trade_plan_time_stop_metadata(signal),
            now,
        )

    def _simulate_entry_execution_through_risk_gate(
        self,
        *,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> _VirtualEntrySimulation:
        raw_entry = self._entry_price(signal)
        risk_settings = self._risk_settings_for_user(request.user_id) or self._fallback_risk_settings(request)
        request, risk_settings, execution_profile, strategy_risk_settings_source = self._resolved_execution_profile(
            signal=signal,
            request=request,
            risk_settings=risk_settings,
        )
        virtual_execution_profile = self._virtual_execution_profile_for_user(request.user_id, risk_settings)
        risk_settings_for_gate = _risk_settings_for_virtual_execution_profile(
            risk_settings,
            virtual_execution_profile,
        )
        request = _request_with_virtual_execution_profile(
            request,
            virtual_execution_profile,
        )
        risk_profile_source = resolved_risk_profile_source(execution_profile)
        virtual_rr_guard_mode = execution_profile.rr_guard_mode
        rr_warning = (
            None
            if virtual_rr_guard_mode == "off"
            else signal_rr_warning_reason(signal, respect_guard_mode=False)
        )
        market_data = self._risk_market_snapshot(
            signal,
            request,
            raw_entry,
            instrument_type=execution_profile.instrument_type,
            virtual_execution_profile=virtual_execution_profile,
        )
        fee_rate = self._risk_fee_snapshot(
            signal,
            request,
            risk_settings,
            instrument_type=execution_profile.instrument_type,
            virtual_execution_profile=virtual_execution_profile,
        )
        gate_request = request.model_copy(
            update={
                "fee_rate": fee_rate.fee_rate,
                "slippage_bps": market_data.slippage_bps,
                "liquidation_price": request.liquidation_price or market_data.liquidation_price,
            }
        )
        account = self.get_virtual_account(gate_request.user_id)
        open_user_positions = [
            trade
            for trade in self._list_active_virtual_trades()
            if trade.user_id == gate_request.user_id
        ]
        reference = self._risk_reference(
            user_id=gate_request.user_id,
            exchange=signal.exchange,
            symbol=signal.symbol,
            side=signal.direction,
            instrument_type=execution_profile.instrument_type,
        )
        decision = self._risk_gate_service.evaluate(
            context=self._risk_context_service.build_virtual_context(
                signal=signal,
                request=gate_request,
                account=account,
                entry_price=market_data.entry_price,
                open_positions=open_user_positions,
                requested_notional=gate_request.size_usd,
                stage="preview",
                exchange_min_order_size=(
                    reference.exchange_min_order_size
                    if reference is not None
                    else None
                ),
                exchange_max_order_size=(
                    reference.exchange_max_order_size
                    if reference is not None
                    else None
                ),
                exchange_min_notional=(
                    reference.exchange_min_notional
                    if reference is not None
                    else None
                ),
                exchange_max_leverage=(
                    reference.exchange_max_leverage
                    if reference is not None
                    else None
                ),
                exchange_rule_status=(
                    reference.exchange_rule_status
                    if reference is not None
                    else "unknown"
                ),
                exchange_rule_age_seconds=(
                    reference.exchange_rule_age_seconds
                    if reference is not None
                    else None
                ),
                exchange_rule_ttl_seconds=(
                    reference.exchange_rule_ttl_seconds
                    if reference is not None
                    else None
                ),
                instrument_rules=(
                    getattr(reference, "exchange_instrument_rules", None)
                    if reference is not None
                    else None
                ),
                **_market_context_kwargs(market_data),
                **_fee_context_kwargs(fee_rate),
                daily_loss_amount=reference.daily_loss_amount if reference is not None else 0.0,
                correlated_open_risk_amount=(
                    reference.correlated_open_risk_amount
                    if reference is not None
                    else 0.0
                ),
                correlation_group=reference.correlation_group if reference is not None else None,
                protection_state=reference.protection_state if reference is not None else "normal",
                protection_reason=reference.protection_reason if reference is not None else None,
                account_drawdown_percent=(
                    reference.account_drawdown_percent
                    if reference is not None
                    else None
                ),
                max_account_drawdown_percent=(
                    reference.max_account_drawdown_percent
                    if reference is not None
                    else 0.0
                ),
                user_mode_multiplier=reference.user_mode_multiplier if reference is not None else 1.0,
                risk_profile_source=risk_profile_source,
                execution_profile_sources=execution_profile.sources,
                execution_profile=execution_profile,
                instrument_type=execution_profile.instrument_type,
            ),
            risk_settings=risk_settings_for_gate,
        )
        self._record_preview_risk_decision(
            signal,
            gate_request,
            decision,
            execution_profile=execution_profile,
            strategy_risk_settings_source=strategy_risk_settings_source,
        )
        requested_size_usd = gate_request.size_usd or decision.position_sizing.notional
        execution = self._execution_engine.simulate_entry(
            signal=signal,
            request=gate_request,
            reference_price=market_data.entry_price,
            requested_size_usd=requested_size_usd,
            market_data_status=market_data.market_data_status,
            market_data_source=market_data.market_data_source,
            market_data_warnings=market_data.warnings,
            market_spread_bps=market_data.spread_bps,
            orderbook_depth_usd=market_data.orderbook_depth_usd,
            execution_profile=execution_profile,
            entry_spread_limit_bps=_entry_spread_limit_bps(risk_settings),
            allow_low_liquidity=_strategy_allows_low_liquidity(signal, user_id=gate_request.user_id),
            enforce_conservative_rules=virtual_execution_profile == "realistic",
            virtual_execution_profile=virtual_execution_profile,
        )
        execution = self._execution_with_risk_decision(
            execution,
            decision,
            rr_warning=rr_warning,
        )
        return _VirtualEntrySimulation(
            execution=execution,
            account=account,
            side=signal.direction,
            stop_loss=decision.stop_loss_plan.stop_loss_price,
        )

    def _resolved_execution_profile(
        self,
        *,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        risk_settings: RiskManagementSettings,
    ) -> tuple[ManualConfirmRequest, RiskManagementSettings, ResolvedExecutionProfile, str]:
        strategy_risk_settings, strategy_risk_settings_source = _strategy_risk_settings(
            signal,
            user_id=request.user_id,
        )
        if strategy_risk_settings_source == "strategy_config":
            strategy_risk_settings = dict(strategy_risk_settings)
            # Generic legacy strategy rr_guard_mode must not override the user's
            # virtual_rr_guard_mode. Per-strategy user overrides still flow
            # through RiskManagementSettings.strategy_rr_guard_modes.
            strategy_risk_settings.pop("rr_guard_mode", None)
        execution_profile = execution_profile_resolver.resolve(
            user_risk_settings=risk_settings,
            strategy_execution_settings=strategy_risk_settings,
            request_override=request_risk_override_to_execution_settings(request.risk_override),
            mode="virtual",
            instrument_type=_virtual_profile_instrument_type(request),
            strategy=signal.strategy,
        )
        resolved_risk_settings = execution_profile_resolver.apply_to_risk_settings(
            risk_settings,
            execution_profile,
        )
        resolved_request = request.model_copy(update={"leverage": int(execution_profile.leverage)})
        return (
            resolved_request,
            resolved_risk_settings,
            execution_profile,
            strategy_risk_settings_source,
        )

    def _virtual_execution_profile_for_user(
        self,
        user_id: str,
        risk_settings: RiskManagementSettings,
    ) -> VirtualExecutionProfile:
        return normalize_virtual_execution_profile(
            self._virtual_execution_profile_provider(user_id, risk_settings)
        )

    def _risk_market_snapshot(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        fallback_entry_price: float,
        *,
        instrument_type: str,
        virtual_execution_profile: VirtualExecutionProfile,
    ) -> RiskMarketDataSnapshot:
        manual_entry_price = _market_snapshot_reference_price(
            request.market_snapshot,
            signal.direction,
        )
        if virtual_execution_profile == "deterministic_test":
            return offline_virtual_market_data_snapshot(
                exchange=signal.exchange,
                symbol=signal.symbol,
                side=signal.direction,
                instrument_type=instrument_type,
                fallback_entry_price=fallback_entry_price,
                manual_entry_price=manual_entry_price,
                manual_slippage_bps=0.0,
                status="fresh",
                source="deterministic_test",
                warnings=("deterministic_test_profile_no_market_data",),
            )
        try:
            return self._market_data_service.build_snapshot(
                exchange=signal.exchange,
                symbol=signal.symbol,
                side=signal.direction,
                mode="virtual",
                instrument_type=instrument_type,
                fallback_entry_price=fallback_entry_price,
                manual_entry_price=manual_entry_price,
                manual_slippage_bps=request.slippage_bps,
                user_id=request.user_id,
            )
        except Exception as exc:
            if virtual_execution_profile != "relaxed_paper":
                raise
            logger.warning("Relaxed virtual market snapshot fallback used: %s", exc)
            return offline_virtual_market_data_snapshot(
                exchange=signal.exchange,
                symbol=signal.symbol,
                side=signal.direction,
                instrument_type=instrument_type,
                fallback_entry_price=fallback_entry_price,
                manual_entry_price=manual_entry_price,
                manual_slippage_bps=request.slippage_bps,
                status="missing",
                source="relaxed_paper_market_fallback",
                warnings=("market_data_service_failed_relaxed_fallback",),
            )

    def _risk_fee_snapshot(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        risk_settings: RiskManagementSettings,
        *,
        instrument_type: str,
        virtual_execution_profile: VirtualExecutionProfile,
    ) -> RiskFeeRateSnapshot:
        if virtual_execution_profile == "deterministic_test":
            return RiskFeeRateSnapshot(
                fee_rate=0.0,
                maker_fee_rate=0.0,
                taker_fee_rate=0.0,
                source="deterministic_test",
                exchange=signal.exchange.strip().lower(),
                symbol=signal.symbol.strip().upper(),
                warnings=("deterministic_test_profile_no_fee_lookup",),
            )
        return self._fee_rate_service.resolve(
            user_id=request.user_id,
            exchange=signal.exchange,
            mode="virtual",
            instrument_type=instrument_type,
            symbol=signal.symbol,
            risk_settings=risk_settings,
            requested_fee_rate=request.fee_rate,
        )

    def _risk_reference(
        self,
        *,
        user_id: str,
        exchange: str,
        symbol: str,
        side: str,
        instrument_type: str,
    ):
        if self._risk_state is None:
            return None
        try:
            return self._risk_state.get_reference(
                user_id=user_id,
                mode="virtual",
                exchange=exchange,
                symbol=symbol,
                side=side,
                instrument_type=instrument_type,
            )
        except Exception as exc:
            logger.warning("Risk reference lookup failed: %s", exc)
            return None

    def _record_blocked_risk_decision(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        decision: RiskDecision,
        *,
        execution_profile: Any,
        strategy_risk_settings_source: str,
    ) -> None:
        if self._risk_audit is None:
            return
        try:
            self._risk_audit.record_decision(
                decision=decision,
                user_id=request.user_id,
                signal_id=signal.id,
                pending_entry_intent_id=decision.lifecycle_trace.pending_entry_intent_id,
                input_snapshot={
                    "flow": "virtual_trade.blocked_attempt",
                    "lifecycle_trace": decision.lifecycle_trace.model_dump(mode="json", exclude_none=True),
                    "request": request.model_dump(mode="json"),
                    "signal": signal.model_dump(mode="json"),
                    "execution_profile": execution_profile.model_dump(mode="json"),
                    "risk_profile_source": resolved_risk_profile_source(execution_profile),
                    "strategy_risk_settings_source": strategy_risk_settings_source,
                },
            )
        except Exception as exc:
            logger.warning("Risk audit write for blocked virtual attempt failed: %s", exc)

    def _record_preview_risk_decision(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        decision: RiskDecision,
        *,
        execution_profile: Any,
        strategy_risk_settings_source: str,
    ) -> None:
        if self._risk_audit is None:
            return
        try:
            self._risk_audit.record_decision(
                decision=decision,
                user_id=request.user_id,
                signal_id=signal.id,
                pending_entry_intent_id=decision.lifecycle_trace.pending_entry_intent_id,
                input_snapshot={
                    "flow": "virtual_execution.preview",
                    "lifecycle_trace": decision.lifecycle_trace.model_dump(mode="json", exclude_none=True),
                    "request": request.model_dump(mode="json"),
                    "signal": signal.model_dump(mode="json"),
                    "execution_profile": execution_profile.model_dump(mode="json"),
                    "risk_profile_source": resolved_risk_profile_source(execution_profile),
                    "strategy_risk_settings_source": strategy_risk_settings_source,
                },
            )
        except Exception as exc:
            logger.warning("Risk audit write for virtual preview failed: %s", exc)

    @staticmethod
    def _execution_with_risk_decision(
        execution: VirtualExecutionReport,
        decision: RiskDecision,
        *,
        rr_warning: str | None = None,
    ) -> VirtualExecutionReport:
        rr_warning_note = _rr_warning_note(rr_warning)
        risk_decision = _risk_decision_with_rr_warning(decision, rr_warning_note)
        return execution.model_copy(
            update={
                "risk_decision": risk_decision,
                "lifecycle_trace": risk_decision.lifecycle_trace,
                "risk_adjustment_plan": risk_decision.risk_adjustment_plan,
                "risk_check": risk_decision.risk_check,
                "position_sizing": risk_decision.position_sizing,
                "stop_loss_plan": risk_decision.stop_loss_plan,
                "take_profit_plan": risk_decision.take_profit_plan,
                "breakeven_plan": risk_decision.breakeven_plan,
                "trailing_stop_plan": risk_decision.trailing_stop_plan,
                "futures_risk_plan": risk_decision.futures_risk_plan,
                "notes": _dedupe_strings([
                    *execution.notes,
                    *_virtual_execution_quality_notes(execution),
                    *risk_decision.notes,
                ]),
            }
        )

    def close_virtual_trade(
        self,
        trade_id: str,
        request: CloseVirtualTradeRequest,
    ) -> Optional[VirtualTrade]:
        trade = self.get_virtual_trade(trade_id)
        if trade is None:
            return None
        exit_price = request.exit_price or trade.current_price
        return self._close_trade(trade, exit_price, request.reason)

    def update_market_price(
        self,
        exchange: str,
        symbol: str,
        price: float,
    ) -> list[VirtualTrade]:
        return self.process_virtual_positions_tick(
            exchange,
            symbol,
            {"price": price},
        )

    def process_virtual_positions_tick(
        self,
        exchange: str,
        symbol: str,
        market_tick_or_candle: Any,
    ) -> list[VirtualTrade]:
        candle = _virtual_lifecycle_candle(market_tick_or_candle)
        price = _virtual_lifecycle_price(market_tick_or_candle)
        if candle is None and price is None:
            return []

        updated: list[VirtualTrade] = []
        for trade in self._list_active_virtual_trades():
            if not _same_market(trade.exchange, trade.symbol, exchange, symbol):
                continue

            now = _market_event_time(market_tick_or_candle)
            if candle is not None:
                lifecycle_result = position_management_engine.apply_candle(
                    trade,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    now=now,
                    candle_open_time=candle.open_time,
                    candle_close_time=candle.close_time,
                )
            else:
                assert price is not None
                simulated_price = self._private_simulated_price(trade, price, now)
                lifecycle_result = position_management_engine.apply_price(
                    trade,
                    price=simulated_price,
                    now=now,
                )
            updated_trade = self._repository.save_virtual_trade(lifecycle_result.trade)
            self._after_virtual_trade_events(self._consume_repository_events())
            if lifecycle_result.closed or is_terminal_virtual_trade_status(updated_trade.status):
                self._apply_account_close(updated_trade, updated_trade.pnl or 0.0)
            updated.append(updated_trade)
        return updated

    def _close_trade(
        self,
        trade: VirtualTrade,
        exit_price: float,
        reason: CloseReason,
    ) -> VirtualTrade:
        if not is_active_virtual_trade_status(trade.status):
            return trade
        lifecycle_result = position_management_engine.close(
            trade,
            exit_price=exit_price,
            reason=reason,
            now=datetime.now(timezone.utc),
        )
        updated = self._repository.save_virtual_trade(lifecycle_result.trade)
        self._after_virtual_trade_events(self._consume_repository_events())
        if lifecycle_result.closed:
            self._apply_account_close(updated, updated.pnl or 0.0)
        return updated

    def _after_signal_write(self, result: SignalWriteResult) -> None:
        try:
            self._signal_analytics_writer.write_event(result.analytics_event)
        except Exception as exc:
            logger.warning("ClickHouse signal confirm analytics write failed: %s", exc)
        try:
            self._signal_hot_store.write_signal(result)
        except Exception as exc:
            logger.warning("Redis signal confirm hot write failed: %s", exc)

    def _after_virtual_trade_events(self, events: list[VirtualTradePersistenceEvent]) -> None:
        for event in events:
            try:
                _write_virtual_trade_analytics_event(event)
            except Exception as exc:
                logger.warning("ClickHouse virtual trade event write failed: %s", exc)
            try:
                _publish_portfolio_event(event)
            except Exception as exc:
                logger.warning("Redis portfolio publish failed: %s", exc)

    def _consume_repository_events(self) -> list[VirtualTradePersistenceEvent]:
        consume_events = getattr(self._repository, "consume_events", None)
        if consume_events is None:
            return []
        return consume_events()

    def _apply_account_close(self, trade: VirtualTrade, pnl: float) -> None:
        user_id = trade.user_id
        self._account_balance_by_user[user_id] = (
            self._account_balance_by_user.setdefault(
                user_id,
                self._virtual_starting_balance_for_user(user_id),
            )
            + pnl
        )
        self._realized_pnl_by_user[user_id] = (
            self._realized_pnl_by_user.setdefault(user_id, 0.0)
            + pnl
        )
        stats = self._account_stats_by_user.setdefault(
            user_id,
            {
                "closed_trades": 0,
                "wins": 0,
                "losses": 0,
                "breakeven": 0,
            },
        )
        stats["closed_trades"] += 1
        if trade.result == "win":
            stats["wins"] += 1
        elif trade.result == "loss":
            stats["losses"] += 1
        else:
            stats["breakeven"] += 1

    def _trim_trades(self) -> None:
        virtual_trades = self._repository.list_virtual_trades()
        if len(virtual_trades) <= MAX_STORED_TRADES:
            return

        keep_ids = {trade.id for trade in virtual_trades[:MAX_STORED_TRADES]}
        for trade in virtual_trades[MAX_STORED_TRADES:]:
            self._repository.delete_virtual_trade(trade.id)
        self._trade_by_signal = {
            signal_id: trade_id
            for signal_id, trade_id in self._trade_by_signal.items()
            if trade_id in keep_ids
        }

    @staticmethod
    def _entry_price(signal: RadarSignal) -> float:
        if signal.entry_min is not None and signal.entry_max is not None:
            return (signal.entry_min + signal.entry_max) / 2
        if signal.entry_min is not None:
            return signal.entry_min
        if signal.entry_max is not None:
            return signal.entry_max
        raise ValueError("У сигнала нет entry zone")

    @staticmethod
    def _private_simulated_price(
        trade: VirtualTrade,
        real_price: float,
        now: datetime,
    ) -> float:
        simulated_path = trade.execution.simulated_path if trade.execution else None
        if simulated_path is None:
            return real_price

        elapsed_seconds = max((now - trade.opened_at).total_seconds(), 0.0)
        residual_impact = (
            simulated_path.initial_impact_delta
            * math.exp(-simulated_path.decay_lambda * elapsed_seconds)
        )
        return max(real_price + residual_impact, 0.00000001)

    @staticmethod
    def _gross_pnl(trade: VirtualTrade, price: float) -> float:
        quantity = trade.remaining_quantity if trade.remaining_quantity is not None else trade.quantity
        if trade.side == "long":
            return (price - trade.entry_price) * quantity
        return (trade.entry_price - price) * quantity


def _virtual_lifecycle_candle(value: Any) -> _VirtualLifecycleCandle | None:
    high = _positive_market_float(value, "high")
    low = _positive_market_float(value, "low")
    close = _positive_market_float(value, "close", "price")
    if high is None or low is None or close is None:
        return None
    return _VirtualLifecycleCandle(
        high=max(high, low, close),
        low=min(high, low, close),
        close=close,
        open_time=_optional_market_int(value, "open_time"),
        close_time=_optional_market_int(value, "close_time"),
    )


def _virtual_lifecycle_price(value: Any) -> float | None:
    return _positive_market_float(value, "price", "last", "close")


def _positive_market_float(value: Any, *names: str) -> float | None:
    for name in names:
        raw = _market_value(value, name)
        if raw is None:
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _optional_market_int(value: Any, name: str) -> int | None:
    raw = _market_value(value, name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _market_value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _market_event_time(value: Any) -> datetime:
    timestamp = _optional_market_int(value, "close_time") or _optional_market_int(value, "timestamp")
    if timestamp is None:
        return datetime.now(timezone.utc)
    if timestamp > 10_000_000_000:
        timestamp = timestamp // 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _same_market(
    trade_exchange: str,
    trade_symbol: str,
    exchange: str,
    symbol: str,
) -> bool:
    return (
        trade_exchange.strip().lower() == exchange.strip().lower()
        and trade_symbol.strip().upper() == symbol.strip().upper()
    )


virtual_trading_service = VirtualTradingService(
    risk_settings_provider=get_user_risk_management_settings,
    risk_audit=risk_audit_service,
    risk_state=risk_state_service,
)

# Backward-compatible alias while API/tests migrate to the virtual_trading package.
TradeService = VirtualTradingService
trade_service = virtual_trading_service


_VIRTUAL_TRADE_EVENT_COLUMNS = [
    "user_id",
    "portfolio_id",
    "order_id",
    "position_id",
    "signal_id",
    "event_type",
    "exchange",
    "symbol",
    "side",
    "price",
    "quantity",
    "pnl",
    "fee",
    "event_ts",
    "ingest_ts",
]


def _write_virtual_trade_analytics_event(event: VirtualTradePersistenceEvent) -> None:
    trade = event.trade
    event_ts = trade.closed_at or trade.opened_at or datetime.now(timezone.utc)
    price = trade.exit_price or trade.current_price or trade.entry_price
    get_clickhouse_client().insert(
        "analytics.virtual_trade_events",
        [
            [
                event.user_id,
                event.portfolio_id,
                event.order_id,
                event.position_id,
                event.signal_id,
                event.event_type,
                trade.exchange,
                trade.symbol,
                trade.side,
                Decimal(str(price)),
                Decimal(str(trade.quantity)),
                Decimal(str(trade.pnl)) if trade.pnl is not None else None,
                event.fee,
                event_ts,
                datetime.now(timezone.utc),
            ]
        ],
        column_names=_VIRTUAL_TRADE_EVENT_COLUMNS,
    )


def _publish_portfolio_event(event: VirtualTradePersistenceEvent) -> None:
    payload = {
        "event_type": event.event_type,
        "user_id": str(event.user_id),
        "portfolio_id": str(event.portfolio_id),
        "order_id": str(event.order_id),
        "position_id": str(event.position_id),
        "signal_id": str(event.signal_id) if event.signal_id is not None else None,
        "trade": event.trade.model_dump(mode="json"),
    }
    get_redis_client().publish(
        f"pubsub:portfolio:{event.user_id}",
        json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")),
    )


def _risk_settings_for_virtual_execution_profile(
    risk_settings: RiskManagementSettings,
    virtual_execution_profile: VirtualExecutionProfile,
) -> RiskManagementSettings:
    if virtual_execution_profile == "realistic":
        return risk_settings
    return risk_settings.model_copy(
        update={
            "max_orderbook_liquidity_ratio": 0.0,
        }
    )


def _request_with_virtual_execution_profile(
    request: ManualConfirmRequest,
    virtual_execution_profile: VirtualExecutionProfile,
) -> ManualConfirmRequest:
    metadata = dict(request.metadata)
    metadata["virtual_execution_profile"] = virtual_execution_profile
    metadata["virtual_fill_policy"] = fill_policy_for_profile(virtual_execution_profile)
    return request.model_copy(update={"metadata": metadata})


def _market_context_kwargs(market_data: RiskMarketDataSnapshot) -> dict[str, Any]:
    return {
        "liquidation_price": market_data.liquidation_price,
        "funding_buffer_per_unit": market_data.funding_buffer_per_unit,
        "best_bid": market_data.best_bid,
        "best_ask": market_data.best_ask,
        "mark_price": market_data.mark_price,
        "funding_rate": market_data.funding_rate,
        "spread_percent": market_data.spread_percent,
        "spread_bps": market_data.spread_bps,
        "orderbook_depth_usd": market_data.orderbook_depth_usd,
        "orderbook_snapshot": market_data.orderbook_snapshot,
        "market_data_status": market_data.market_data_status,
        "market_data_source": market_data.market_data_source,
        "market_data_warnings": list(market_data.warnings),
    }


def _entry_spread_limit_bps(risk_settings: RiskManagementSettings) -> float | None:
    if risk_settings.max_spread_bps_for_entry > 0:
        return risk_settings.max_spread_bps_for_entry
    if risk_settings.max_spread_bps > 0:
        return risk_settings.max_spread_bps
    return None


def _strategy_allows_low_liquidity(signal: RadarSignal, *, user_id: str) -> bool | None:
    try:
        configs = strategy_config_service.list_configs(user_id=user_id)
    except Exception:
        return None
    signal_exchange = signal.exchange.strip().lower()
    signal_symbol = signal.symbol.strip().upper()
    for config in configs:
        if config.strategy_code != signal.strategy:
            continue
        if config.timeframes and signal.timeframe not in config.timeframes:
            continue
        if config.pairs:
            pairs = {
                (pair.exchange.strip().lower(), pair.symbol.strip().upper())
                for pair in config.pairs
            }
            if (signal_exchange, signal_symbol) not in pairs:
                continue
        elif config.exchanges and signal_exchange not in {exchange.strip().lower() for exchange in config.exchanges}:
            continue
        return bool((config.params or {}).get("allow_low_liquidity", False))
    return False


def _ensure_signal_execution_candidate(signal: RadarSignal) -> None:
    if is_execution_candidate_status(signal.status):
        return
    raise ValueError("Signal entry is not execution-ready; arm pending entry to wait for the entry zone.")


def _fee_context_kwargs(fee_rate: RiskFeeRateSnapshot) -> dict[str, Any]:
    return {
        "fee_rate_source": fee_rate.source,
        "maker_fee_rate": fee_rate.maker_fee_rate,
        "taker_fee_rate": fee_rate.taker_fee_rate,
        "fee_rate_warnings": list(fee_rate.warnings),
    }


def _virtual_profile_instrument_type(request: ManualConfirmRequest) -> str:
    if request.execution_profile is not None and request.execution_profile.instrument_type is not None:
        return request.execution_profile.instrument_type
    if request.risk_override is not None and request.risk_override.leverage is not None:
        return "futures" if request.risk_override.leverage > 1 else "spot"
    return "futures" if request.leverage > 1 else "spot"


def _strategy_risk_settings(signal: RadarSignal, *, user_id: str) -> tuple[dict[str, Any], str]:
    try:
        configs = strategy_config_service.list_configs(user_id=user_id)
    except Exception as exc:
        return {}, f"unavailable:{exc.__class__.__name__}"
    signal_exchange = signal.exchange.strip().lower()
    signal_symbol = signal.symbol.strip().upper()
    for config in configs:
        if config.strategy_code != signal.strategy:
            continue
        if config.timeframes and signal.timeframe not in config.timeframes:
            continue
        if config.pairs:
            pairs = {
                (pair.exchange.strip().lower(), pair.symbol.strip().upper())
                for pair in config.pairs
            }
            if (signal_exchange, signal_symbol) not in pairs:
                continue
        elif config.exchanges and signal_exchange not in {exchange.strip().lower() for exchange in config.exchanges}:
            continue
        return config.risk_settings.to_legacy_dict(), "strategy_config"
    return {}, "not_configured"


def _market_snapshot_reference_price(
    snapshot: VirtualMarketSnapshot | None,
    side: str,
) -> float | None:
    if snapshot is None:
        return None
    best_bid = snapshot.best_bid
    best_ask = snapshot.best_ask
    if best_bid is None and snapshot.bids:
        best_bid = max(level.price for level in snapshot.bids)
    if best_ask is None and snapshot.asks:
        best_ask = min(level.price for level in snapshot.asks)
    if side == "long":
        return best_ask or best_bid
    return best_bid or best_ask


def _trade_plan_time_stop_metadata(signal: RadarSignal) -> dict[str, Any] | None:
    trade_plan = signal.trade_plan
    if trade_plan is None:
        return None
    metadata: dict[str, Any] = {}
    sources = [trade_plan.metadata, trade_plan.risk_rules.metadata]
    if trade_plan.invalidation is not None:
        sources.append(trade_plan.invalidation.metadata)
    for source in sources:
        if not source:
            continue
        for key in ("time_stop", "time_stop_at", "expires_at", "at", "max_holding_seconds"):
            if source.get(key) is not None:
                metadata[key] = source[key]
    return metadata or None


def _trade_origin(
    *,
    signal: RadarSignal,
    request: ManualConfirmRequest,
    lifecycle_trace: Any,
    virtual_trade_id: str,
) -> TradeOrigin:
    metadata = _request_metadata(request)
    raw_origin = metadata.get("origin") if isinstance(metadata.get("origin"), dict) else {}
    pending_entry_intent_id = (
        _metadata_string(metadata.get("pending_entry_intent_id"))
        or _metadata_string(raw_origin.get("pending_entry_intent_id"))
        or _metadata_string(lifecycle_trace.pending_entry_intent_id)
    )
    accepted_trade_plan_hash = (
        _metadata_string(metadata.get("accepted_trade_plan_hash"))
        or _metadata_string(raw_origin.get("accepted_trade_plan_hash"))
    )
    trigger_source = (
        _metadata_string(metadata.get("trigger_source"))
        or _metadata_string(raw_origin.get("trigger_source"))
        or ("pending_entry" if pending_entry_intent_id is not None else "manual")
    )
    return TradeOrigin(
        signal_id=str(signal.id),
        pending_entry_intent_id=pending_entry_intent_id,
        strategy=signal.strategy,
        mode="virtual",
        accepted_trade_plan_hash=accepted_trade_plan_hash,
        trigger_source=trigger_source,
        virtual_trade_id=virtual_trade_id,
        position_id=virtual_trade_id,
    )


def _append_created_from_pending_entry_event(
    trade: VirtualTrade,
    request: ManualConfirmRequest,
    now: datetime,
) -> VirtualTrade:
    if trade.pending_entry_intent_id is None or trade.trigger_source != "pending_entry":
        return trade

    metadata = _request_metadata(request)
    trigger = metadata.get("pending_entry_trigger")
    trigger_metadata = trigger if isinstance(trigger, dict) else {}
    trigger_price_text = _metadata_string(
        trigger_metadata.get("trigger_price") or trigger_metadata.get("touch_price")
    )
    trigger_reason = _metadata_string(trigger_metadata.get("trigger_reason")) or "entry_zone_touched"
    trace = trade.lifecycle_trace.model_copy(
        update={
            "signal_id": trade.signal_id,
            "pending_entry_intent_id": trade.pending_entry_intent_id,
            "virtual_trade_id": trade.id,
        }
    )
    event_metadata = {
        "accepted_trade_plan_hash": trade.accepted_trade_plan_hash,
        "trigger_price": trigger_price_text,
        "trigger_price_source": _metadata_string(trigger_metadata.get("touch_price_source")),
        "trigger_reason": trigger_reason,
        "warnings": (
            list(trigger_metadata.get("warnings"))
            if isinstance(trigger_metadata.get("warnings"), list)
            else []
        ),
    }
    event = VirtualTradeLifecycleEvent(
        signal_id=trade.signal_id,
        pending_entry_intent_id=trade.pending_entry_intent_id,
        risk_decision_id=trace.risk_decision_id,
        virtual_trade_id=trade.id,
        real_order_id=trace.real_order_id,
        event_type="created_from_pending_entry",
        price=_positive_float(trigger_price_text),
        created_at=now,
        lifecycle_trace=trace,
        metadata={key: value for key, value in event_metadata.items() if value is not None},
    )
    return trade.model_copy(
        update={
            "lifecycle_events": [*trade.lifecycle_events, event],
            "lifecycle_trace": trace,
        }
    )


def _request_metadata(request: ManualConfirmRequest) -> dict[str, Any]:
    return request.metadata if isinstance(request.metadata, dict) else {}


def _metadata_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _risk_decision_with_rr_warning(decision: RiskDecision, rr_warning_note: str | None) -> RiskDecision:
    if rr_warning_note is None:
        return decision

    risk_check = decision.risk_check
    risk_check_status = "warning" if risk_check.status == "passed" else risk_check.status
    decision_status = "warning" if decision.status == "passed" else decision.status
    updated_risk_check = risk_check.model_copy(
        update={
            "status": risk_check_status,
            "warnings": _dedupe_strings([*risk_check.warnings, rr_warning_note]),
            "risk_reward_warning": risk_check.risk_reward_warning or not risk_check.risk_reward_blocked,
            "risk_reward_warning_reason": risk_check.risk_reward_warning_reason or rr_warning_note,
        }
    )
    return decision.model_copy(
        update={
            "status": decision_status,
            "warnings": _dedupe_strings([*decision.warnings, rr_warning_note]),
            "notes": _dedupe_strings([*decision.notes, rr_warning_note]),
            "risk_check": updated_risk_check,
        }
    )


def _rr_warning_note(reason: str | None) -> str | None:
    if reason is None:
        return None
    value = reason.strip()
    if not value:
        return None
    summary = "Risk/reward warning: selected R:R is below configured reporting threshold."
    lower = value.lower()
    if "blocked" in lower or "blocker" in lower:
        return summary
    if lower.startswith("risk/reward warning:"):
        detail = value.split(":", 1)[1].strip()
        return f"{summary} {detail}" if detail and detail != summary else summary
    return f"{summary} {value}"


def _virtual_execution_quality_notes(execution: VirtualExecutionReport) -> list[str]:
    status = execution.quality_gate.status
    if status not in {"warning", "blocked"}:
        return []
    return [
        (
            f"Virtual execution quality warning: quality_gate {status} is "
            "a simulation realism warning; entry permission remains RiskGate."
        )
    ]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
