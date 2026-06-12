from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from app.schemas.market import MarketData
from app.schemas.signal import RadarSignal, SignalExecutionGateReason, SignalExecutionGateSnapshot, StrategySignal
from app.schemas.trade import ManualConfirmRequest, VirtualTrade
from app.schemas.user import RiskManagementSettings
from app.services.portfolio_risk import (
    PortfolioRiskContext,
    PortfolioRiskDecision,
    PortfolioRiskLimits,
    portfolio_risk_service,
)
from app.services.signal_execution_gate import SignalExecutionGateService, signal_execution_gate_service
from app.services.strategy_performance_service import score_bucket_for
from app.services.strategy_testing.runner import strategy_test_user_uuid
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestSignalEvent,
    StrategyTestTrade,
)
from app.services.strategy_testing.stores import ClickHouseStrategyTestStore, PostgresStrategyTestRunStore


class ForwardRunStore(Protocol):
    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        ...

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        ...

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        ...

    def mark_cancelled(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        ...

    def update_runtime_state(
        self,
        run_id: UUID,
        runtime_state: dict[str, Any],
        *,
        heartbeat: bool = True,
    ) -> StrategyTestRunDetailResponse:
        ...


class ForwardTradeStore(Protocol):
    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        ...

    def write_signal_events(self, signal_events: Sequence[StrategyTestSignalEvent]) -> None:
        ...

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        ...


class ForwardSignalWriter(Protocol):
    def upsert_strategy_signal(
        self,
        signal: StrategySignal,
        exchange: str | None = None,
        explanation: list[str] | None = None,
    ) -> tuple[RadarSignal, bool]:
        ...


class ForwardVirtualTrading(Protocol):
    def open_virtual_trade(self, signal: RadarSignal, request: ManualConfirmRequest) -> VirtualTrade:
        ...


class ForwardScanner(Protocol):
    def process_tick(self, tick: MarketData) -> Any:
        ...


@dataclass
class ForwardRuntimeResult:
    ticks_processed: int = 0
    signals_processed: int = 0
    signals_skipped: int = 0
    opened_trades: int = 0
    pending_entries_armed: int = 0
    trades_written: int = 0
    signal_events_written: int = 0
    metrics_written: int = 0
    runtime_state_updates: int = 0
    cancelled_runs: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "ForwardRuntimeResult") -> None:
        self.ticks_processed += other.ticks_processed
        self.signals_processed += other.signals_processed
        self.signals_skipped += other.signals_skipped
        self.opened_trades += other.opened_trades
        self.pending_entries_armed += other.pending_entries_armed
        self.trades_written += other.trades_written
        self.signal_events_written += other.signal_events_written
        self.metrics_written += other.metrics_written
        self.runtime_state_updates += other.runtime_state_updates
        self.cancelled_runs += other.cancelled_runs
        self.errors.extend(other.errors)


class ForwardStrategyTestRuntime:
    def __init__(
        self,
        *,
        run_store: ForwardRunStore | None = None,
        trade_store: ForwardTradeStore | None = None,
        signal_writer: ForwardSignalWriter | None = None,
        virtual_trading: ForwardVirtualTrading | None = None,
        execution_gate: SignalExecutionGateService | None = None,
        scanner: ForwardScanner | None = None,
    ) -> None:
        self._run_store = run_store or PostgresStrategyTestRunStore()
        self._trade_store = trade_store or ClickHouseStrategyTestStore()
        self._signal_writer = signal_writer
        self._virtual_trading = virtual_trading or ForwardIsolatedVirtualTrading()
        self._execution_gate = execution_gate or signal_execution_gate_service
        self._scanner = scanner

    def start_run(
        self,
        run_id: UUID,
        request: StrategyTestRunRequest,
    ) -> StrategyTestRunDetailResponse:
        detail = self._run_store.mark_running(run_id)
        return self._run_store.update_runtime_state(
            run_id,
            {
                "status": "listening",
                "test_type": request.test_type,
                "processed_ticks": _counter(detail.run.runtime_state, "processed_ticks"),
                "processed_signals": _counter(detail.run.runtime_state, "processed_signals"),
                "opened_trades": _counter(detail.run.runtime_state, "opened_trades"),
                "pending_entries_armed": _counter(detail.run.runtime_state, "pending_entries_armed"),
                "trades_written": _counter(detail.run.runtime_state, "trades_written"),
                "signal_events_written": _counter(detail.run.runtime_state, "signal_events_written"),
                "metrics_written": _counter(detail.run.runtime_state, "metrics_written"),
                "forward_account": _initial_forward_account(request),
                "forward_positions": list(detail.run.runtime_state.get("forward_positions") or []),
                "last_error": None,
            },
        )

    def heartbeat_active_runs(self) -> ForwardRuntimeResult:
        result = ForwardRuntimeResult()
        result.cancelled_runs += self._cancel_stopping_runs()
        for run in self._running_forward_runs():
            self._run_store.update_runtime_state(
                run.run_id,
                {
                    "status": "listening",
                    "last_heartbeat_reason": "forward_runtime_worker",
                    "last_processed_at": _now_iso(),
                },
            )
            result.runtime_state_updates += 1
        return result

    async def process_market_tick(self, tick: MarketData) -> ForwardRuntimeResult:
        result = ForwardRuntimeResult(ticks_processed=1)
        result.cancelled_runs += self._cancel_stopping_runs()
        for run in self._running_forward_runs():
            if not _run_matches_market(run, tick.exchange, tick.symbol):
                continue
            self._increment_runtime_state(
                run,
                {
                    "processed_ticks": 1,
                    "last_exchange": tick.exchange.lower(),
                    "last_symbol": tick.symbol.upper(),
                    "last_price": tick.price,
                    "last_tick_timestamp": tick.timestamp,
                    **_mark_to_market_forward_account(run, tick),
                },
            )
            result.runtime_state_updates += 1

        if self._scanner is None:
            return result
        signals = self._scanner.process_tick(tick)
        if inspect.isawaitable(signals):
            signals = await signals
        for signal in list(signals or []):
            result.merge(await self.process_strategy_signal(signal))
        return result

    async def process_strategy_signal(self, signal: StrategySignal) -> ForwardRuntimeResult:
        result = ForwardRuntimeResult()
        result.cancelled_runs += self._cancel_stopping_runs()
        runs = [run for run in self._running_forward_runs() if _run_matches_signal(run, signal)]
        if not runs:
            result.signals_skipped = 1
            return result

        for run in runs:
            try:
                radar_signal = self._radar_signal_for_forward_run(run, signal)
                gate = radar_signal.execution_gate or self._execution_gate.evaluate(radar_signal)
                result.signals_processed += 1
                if gate.can_enter_now:
                    gate_request = _manual_confirm_request(run)
                    portfolio_decision = _forward_portfolio_decision(run, radar_signal, gate_request)
                    if not portfolio_decision.can_enter:
                        gate = _gate_blocked_by_portfolio(gate, portfolio_decision)
                        radar_signal = radar_signal.model_copy(update={"execution_gate": gate})
                        event = _strategy_test_signal_event_from_forward_signal(
                            run=run,
                            signal=radar_signal,
                            gate=gate,
                            funnel_stage="blocked",
                            outcome="blocked",
                        )
                        result.signal_events_written += self._write_signal_event(event)
                        self._increment_runtime_state(
                            run,
                            {
                                "processed_signals": 1,
                                "signal_events_written": 1,
                                "last_signal_id": radar_signal.id,
                                "last_gate_status": gate.status,
                                "last_feed_kind": gate.feed_kind,
                                "last_portfolio_risk_action": portfolio_decision.action,
                                "last_portfolio_risk_reason_code": portfolio_decision.reason_code,
                            },
                        )
                        result.runtime_state_updates += 1
                        continue
                    if portfolio_decision.action == "reduce_size":
                        gate_request = _request_with_portfolio_size(gate_request, portfolio_decision)
                        gate = _gate_with_portfolio_warning(gate, portfolio_decision)
                        radar_signal = radar_signal.model_copy(update={"execution_gate": gate})
                    opened = self._open_virtual_trade(run, radar_signal, request=gate_request)
                    event = _strategy_test_signal_event_from_forward_signal(
                        run=run,
                        signal=radar_signal,
                        gate=gate,
                        trade=opened,
                    )
                    result.opened_trades += 1
                    result.trades_written += self._write_trade(run, radar_signal, opened)
                    result.signal_events_written += self._write_signal_event(event)
                    result.metrics_written += self._write_metric(run, radar_signal, opened)
                    self._increment_runtime_state(
                        run,
                        {
                            "processed_signals": 1,
                            "opened_trades": 1,
                            "trades_written": 1,
                            "signal_events_written": 1,
                            "metrics_written": 1,
                            "last_signal_id": radar_signal.id,
                            "last_gate_status": gate.status,
                            "last_feed_kind": gate.feed_kind,
                            "last_trade_id": opened.id,
                            **_apply_forward_trade_open(run, opened),
                        },
                    )
                elif gate.can_arm_pending:
                    event = _strategy_test_signal_event_from_forward_signal(
                        run=run,
                        signal=radar_signal,
                        gate=gate,
                        funnel_stage="pending",
                        outcome="pending",
                    )
                    result.pending_entries_armed += 1
                    result.signal_events_written += self._write_signal_event(event)
                    self._increment_runtime_state(
                        run,
                        {
                            "processed_signals": 1,
                            "pending_entries_armed": 1,
                            "signal_events_written": 1,
                            "last_signal_id": radar_signal.id,
                            "last_gate_status": gate.status,
                            "last_feed_kind": gate.feed_kind,
                        },
                    )
                else:
                    event = _strategy_test_signal_event_from_forward_signal(
                        run=run,
                        signal=radar_signal,
                        gate=gate,
                        funnel_stage="blocked" if gate.status == "blocked" else "no_entry",
                        outcome="blocked" if gate.status == "blocked" else "no_entry",
                    )
                    result.signal_events_written += self._write_signal_event(event)
                    self._increment_runtime_state(
                        run,
                        {
                            "processed_signals": 1,
                            "signal_events_written": 1,
                            "last_signal_id": radar_signal.id,
                            "last_gate_status": gate.status,
                            "last_feed_kind": gate.feed_kind,
                        },
                    )
                result.runtime_state_updates += 1
            except Exception as exc:
                message = str(exc)
                result.errors.append(message)
                self._run_store.update_runtime_state(
                    run.run_id,
                    {
                        "status": "degraded",
                        "last_error": message,
                        "last_processed_at": _now_iso(),
                    },
                )
                result.runtime_state_updates += 1
        return result

    def _radar_signal_for_forward_run(
        self,
        run: StrategyTestRunResponse,
        signal: StrategySignal,
    ) -> RadarSignal:
        if self._signal_writer is not None:
            radar_signal, _ = self._signal_writer.upsert_strategy_signal(
                signal,
                exchange=signal.exchange,
                explanation=list(signal.explanation),
            )
            return radar_signal
        return _forward_radar_signal_from_strategy_signal(run, signal)

    def _running_forward_runs(self) -> list[StrategyTestRunResponse]:
        return _forward_runs(self._run_store.list_runs(user_id=None, limit=500, status="running"))

    def _cancel_stopping_runs(self) -> int:
        cancelled = 0
        for run in _forward_runs(self._run_store.list_runs(user_id=None, limit=500, status="stopping")):
            self._run_store.update_runtime_state(
                run.run_id,
                {
                    "status": "cancelled",
                    "cancelled_reason": "forward_runtime_stopping",
                    "last_processed_at": _now_iso(),
                },
            )
            self._run_store.mark_cancelled(run.run_id)
            cancelled += 1
        return cancelled

    def _open_virtual_trade(
        self,
        run: StrategyTestRunResponse,
        signal: RadarSignal,
        *,
        request: ManualConfirmRequest | None = None,
    ) -> VirtualTrade:
        return self._virtual_trading.open_virtual_trade(
            signal,
            request or _manual_confirm_request(run),
        )

    def _write_trade(
        self,
        run: StrategyTestRunResponse,
        signal: RadarSignal,
        trade: VirtualTrade,
    ) -> int:
        row = _strategy_test_trade_from_virtual_trade(run=run, signal=signal, trade=trade)
        self._trade_store.write_trades([row])
        return 1

    def _write_signal_event(self, event: StrategyTestSignalEvent) -> int:
        self._trade_store.write_signal_events([event])
        return 1

    def _write_metric(
        self,
        run: StrategyTestRunResponse,
        signal: RadarSignal,
        trade: VirtualTrade,
    ) -> int:
        self._trade_store.write_metrics(
            [_strategy_test_metric_from_virtual_trade(run=run, signal=signal, trade=trade)]
        )
        return 1

    def _increment_runtime_state(
        self,
        run: StrategyTestRunResponse,
        increments: dict[str, Any],
    ) -> StrategyTestRunDetailResponse:
        state = dict(run.runtime_state)
        patch: dict[str, Any] = {
            "status": "processing",
            "last_processed_at": _now_iso(),
        }
        for key, value in increments.items():
            if key in {
                "processed_ticks",
                "processed_signals",
                "opened_trades",
                "pending_entries_armed",
                "trades_written",
                "signal_events_written",
                "metrics_written",
            }:
                patch[key] = _counter(state, key) + int(value or 0)
            else:
                patch[key] = value
        return self._run_store.update_runtime_state(run.run_id, patch)


class ForwardIsolatedVirtualTrading:
    def open_virtual_trade(self, signal: RadarSignal, request: ManualConfirmRequest) -> VirtualTrade:
        entry_price = _entry_price(signal)
        size_usd = _virtual_size_usd(request)
        quantity = size_usd / entry_price if entry_price > 0 else 0.0
        opened_at = signal.created_at.astimezone(timezone.utc)
        return VirtualTrade(
            id=_forward_trade_id(signal.id),
            user_id=request.user_id,
            signal_id=signal.id,
            exchange=signal.exchange,
            symbol=signal.symbol,
            strategy=signal.strategy,
            timeframe=signal.timeframe,
            side=signal.direction,
            entry_price=entry_price,
            current_price=entry_price,
            size_usd=size_usd,
            quantity=quantity,
            initial_quantity=quantity,
            remaining_quantity=quantity,
            initial_size_usd=size_usd,
            remaining_size_usd=size_usd,
            leverage=request.leverage,
            risk_percent=float(request.risk_percent or 1.0),
            risk_amount=size_usd * float(request.risk_percent or 1.0) / 100,
            risk_reward=float(signal.selected_rr or signal.risk_reward or 0.0),
            stop_loss=float(signal.stop_loss or entry_price),
            take_profit=[price for price in [signal.take_profit_1, signal.take_profit_2] if price is not None],
            fees=size_usd * request.fee_rate,
            slippage_bps=request.slippage_bps,
            requested_size_usd=size_usd,
            filled_size_usd=size_usd,
            opened_at=opened_at,
            updated_at=opened_at,
        )


def _forward_radar_signal_from_strategy_signal(
    run: StrategyTestRunResponse,
    signal: StrategySignal,
) -> RadarSignal:
    created_at = _signal_timestamp_to_utc(signal.timestamp)
    return RadarSignal(
        id=_forward_signal_id(run, signal),
        symbol=signal.symbol,
        exchange=signal.exchange,
        strategy=signal.strategy,
        direction=signal.direction.lower(),
        confidence=signal.confidence,
        risk_reward=signal.risk_reward,
        first_target_rr=signal.first_target_rr,
        final_target_rr=signal.final_target_rr,
        selected_rr=signal.selected_rr,
        selected_rr_target=signal.selected_rr_target,
        min_rr_ratio=signal.min_rr_ratio,
        urgency=signal.urgency,
        status=signal.status,
        score=signal.score,
        timeframe=signal.timeframe,
        candle_state=signal.candle_state,
        entry_min=signal.entry_min,
        entry_max=signal.entry_max,
        stop_loss=signal.stop_loss,
        take_profit_1=signal.take_profit_1,
        take_profit_2=signal.take_profit_2,
        explanation=list(signal.explanation),
        risks=list(signal.risks),
        score_breakdown=signal.score_breakdown,
        status_reason=signal.status_reason,
        quality=signal.quality,
        regime=signal.regime,
        setup=signal.setup,
        confirmation=signal.confirmation,
        trigger=signal.trigger,
        invalidation=signal.invalidation,
        exit_plan=signal.exit_plan,
        trade_plan=signal.trade_plan,
        edge=signal.edge,
        no_trade_filter=signal.no_trade_filter,
        decision=signal.decision,
        execution_gate=signal.execution_gate,
        created_at=created_at,
        updated_at=created_at,
    )


def _strategy_test_signal_event_from_forward_signal(
    *,
    run: StrategyTestRunResponse,
    signal: RadarSignal,
    gate: SignalExecutionGateSnapshot,
    trade: VirtualTrade | None = None,
    funnel_stage: str | None = None,
    outcome: str | None = None,
) -> StrategyTestSignalEvent:
    event_time = signal.created_at.astimezone(timezone.utc)
    filled = trade is not None
    blocked_reason_code = _first_gate_reason_code(gate)
    stage = funnel_stage or ("filled" if filled else "signal")
    event_outcome = outcome or ("open" if filled else None)
    return StrategyTestSignalEvent(
        run_id=run.run_id,
        user_id=strategy_test_user_uuid(_matrix_user_id(run)),
        mode=_matrix_mode(run),
        test_type="forward_virtual",
        strategy_code=signal.strategy,
        strategy_version=str(signal.trade_plan.metadata.get("strategy_version", "")) if signal.trade_plan else "",
        exchange=signal.exchange,
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        direction=signal.direction,
        signal_id=signal.id,
        synthetic_signal_id=signal.id,
        signal_key=_forward_signal_key(run, signal),
        event_time=event_time,
        candle_time=event_time,
        signal_score=float(signal.score) if signal.score is not None else None,
        market_regime=_market_regime(signal),
        score_bucket=_score_bucket(signal.score),
        status=signal.status,
        gate_status=gate.status,
        feed_kind=gate.feed_kind,
        trigger_passed=bool(gate.can_enter_now or gate.can_arm_pending or getattr(signal.trigger, "passed", False)),
        trigger_reason_code=blocked_reason_code if gate.status != "passed" else None,
        execution_candidate=bool(gate.can_enter_now or gate.can_arm_pending or gate.feed_kind == "execution_signal"),
        entry_touched=filled,
        filled=filled,
        closed=bool(trade and trade.closed_at is not None),
        outcome=event_outcome,
        funnel_stage=stage,
        risk_rejected=_gate_has_reason_source(gate, {"risk", "rr", "no_trade"}),
        execution_rejected=gate.status == "blocked" and gate.feed_kind == "blocked",
        no_entry=stage in {"blocked", "no_entry"},
        rejection_reason_code=blocked_reason_code if gate.status == "blocked" else None,
        blocked_reason_code=blocked_reason_code if gate.status == "blocked" else None,
        selected_rr=signal.selected_rr or signal.risk_reward,
        entry_min=_optional_decimal(signal.entry_min),
        entry_max=_optional_decimal(signal.entry_max),
        stop_loss=_optional_decimal(signal.stop_loss),
        features_snapshot=signal.model_dump(mode="json", exclude={"card_view", "details_view"}),
        trade_plan=signal.trade_plan.model_dump(mode="json") if signal.trade_plan else {},
        metadata={
            "test_type": "forward_virtual",
            "trade_id": trade.id if trade else None,
            "runtime": "forward_strategy_test",
        },
        tags=_run_tags(run),
        created_at=_now_utc(),
    )


def _initial_forward_account(request: StrategyTestRunRequest) -> dict[str, Any]:
    initial_capital = _decimal(request.initial_capital, Decimal("1000"))
    return _serialize_forward_account(
        {
            "initial_capital": initial_capital,
            "balance": initial_capital,
            "equity": initial_capital,
            "realized_pnl": Decimal("0"),
            "unrealized_pnl": Decimal("0"),
            "fees": Decimal("0"),
            "slippage": Decimal("0"),
            "open_positions": 0,
            "closed_positions": 0,
        }
    )


def _apply_forward_trade_open(
    run: StrategyTestRunResponse,
    trade: VirtualTrade,
) -> dict[str, Any]:
    account = _forward_account_from_runtime(run)
    fees = _decimal(trade.fees, Decimal("0"))
    slippage = _decimal(trade.slippage_bps, Decimal("0"))
    account["balance"] -= fees
    account["fees"] += fees
    account["slippage"] += slippage
    account["open_positions"] += 1
    account["equity"] = account["balance"] + account["unrealized_pnl"]

    positions = _forward_positions(run)
    positions.append(
        {
            "trade_id": trade.id,
            "signal_id": trade.signal_id,
            "exchange": trade.exchange,
            "symbol": trade.symbol,
            "strategy": trade.strategy,
            "timeframe": trade.timeframe,
            "side": trade.side,
            "entry_price": str(_decimal(trade.entry_price, Decimal("0"))),
            "current_price": str(_decimal(trade.current_price, Decimal("0"))),
            "size_usd": str(_decimal(trade.size_usd, Decimal("0"))),
            "quantity": str(_decimal(trade.quantity, Decimal("0"))),
            "risk_percent": str(_decimal(trade.risk_percent, Decimal("0"))),
            "risk_amount": str(_decimal(trade.risk_amount, Decimal("0"))),
            "stop_loss": str(_decimal(trade.stop_loss, Decimal("0"))),
            "take_profit": [str(_decimal(price, Decimal("0"))) for price in trade.take_profit],
            "unrealized_pnl": "0",
            "fees": str(fees),
            "status": "open",
            "opened_at": trade.opened_at.astimezone(timezone.utc).isoformat(),
        }
    )
    return {
        "forward_account": _serialize_forward_account(account),
        "forward_positions": positions,
    }


def _mark_to_market_forward_account(
    run: StrategyTestRunResponse,
    tick: MarketData,
) -> dict[str, Any]:
    positions = _forward_positions(run)
    if not positions:
        return {}

    tick_exchange = tick.exchange.strip().lower()
    tick_symbol = tick.symbol.strip().upper()
    price = _decimal(tick.price, Decimal("0"))
    total_unrealized = Decimal("0")
    realized_delta = Decimal("0")
    closed_count = 0
    closed_at = _signal_timestamp_to_utc(tick.timestamp).isoformat()
    updated_positions: list[dict[str, Any]] = []
    for position in positions:
        current = dict(position)
        if (
            str(current.get("exchange", "")).strip().lower() == tick_exchange
            and str(current.get("symbol", "")).strip().upper() == tick_symbol
            and str(current.get("status") or "open") == "open"
        ):
            entry_price = _decimal(current.get("entry_price"), Decimal("0"))
            quantity = _decimal(current.get("quantity"), Decimal("0"))
            side = str(current.get("side") or "long").lower()
            pnl = (price - entry_price) * quantity if side == "long" else (entry_price - price) * quantity
            current["current_price"] = str(price)
            close_reason = _forward_close_reason(current, price, side)
            if close_reason is not None:
                current["status"] = "closed"
                current["close_reason"] = close_reason
                current["exit_price"] = str(price)
                current["closed_at"] = closed_at
                current["realized_pnl"] = _decimal_string(pnl)
                current["unrealized_pnl"] = "0"
                realized_delta += pnl
                closed_count += 1
            else:
                current["unrealized_pnl"] = _decimal_string(pnl)
        if str(current.get("status") or "open") == "open":
            total_unrealized += _decimal(current.get("unrealized_pnl"), Decimal("0"))
        updated_positions.append(current)

    account = _forward_account_from_runtime(run)
    account["realized_pnl"] += realized_delta
    account["unrealized_pnl"] = total_unrealized
    account["open_positions"] = max(0, account["open_positions"] - closed_count)
    account["closed_positions"] += closed_count
    account["equity"] = account["balance"] + account["realized_pnl"] + total_unrealized
    return {
        "forward_account": _serialize_forward_account(account),
        "forward_positions": updated_positions,
    }


def _forward_runs(details: Sequence[StrategyTestRunDetailResponse]) -> list[StrategyTestRunResponse]:
    return [detail.run for detail in details if detail.run.test_type == "forward_virtual"]


def _run_matches_signal(run: StrategyTestRunResponse, signal: StrategySignal) -> bool:
    matrix = run.requested_matrix
    if str(signal.strategy) not in {str(item) for item in matrix.get("strategies", [])}:
        return False
    if str(signal.timeframe) not in {str(item) for item in matrix.get("timeframes", [])}:
        return False
    return _run_matches_market(run, signal.exchange, signal.symbol)


def _run_matches_market(run: StrategyTestRunResponse, exchange: str, symbol: str) -> bool:
    exchange_key = exchange.strip().lower()
    symbol_key = symbol.strip().upper()
    pairs = run.requested_matrix.get("pairs", [])
    for pair in pairs if isinstance(pairs, list) else []:
        if not isinstance(pair, dict):
            continue
        if str(pair.get("exchange", "")).strip().lower() == exchange_key and str(pair.get("symbol", "")).strip().upper() == symbol_key:
            return True
    return False


def _manual_confirm_request(
    run: StrategyTestRunResponse,
    *,
    auto_enter_on_confirmation: bool = False,
) -> ManualConfirmRequest:
    matrix = run.requested_matrix
    risk_settings = _forward_risk_settings(run)
    return ManualConfirmRequest(
        mode="virtual",
        user_id=_matrix_user_id(run),
        auto_enter_on_confirmation=auto_enter_on_confirmation,
        account_balance=float(_decimal(matrix.get("initial_capital"), Decimal("1000"))),
        risk_percent=risk_settings.risk_per_trade_percent,
        fee_rate=float(_decimal(matrix.get("fee_rate"), Decimal("0"))),
        slippage_bps=float(_decimal(matrix.get("slippage_bps"), Decimal("0"))),
        max_open_positions=_forward_max_concurrent_positions(run),
        metadata={
            "strategy_test_run_id": str(run.run_id),
            "test_type": "forward_virtual",
        },
    )


def _forward_portfolio_decision(
    run: StrategyTestRunResponse,
    signal: RadarSignal,
    request: ManualConfirmRequest,
) -> PortfolioRiskDecision:
    account = _forward_account_from_runtime(run)
    risk_settings = _forward_risk_settings(run)
    open_positions = _open_forward_positions(run)
    equity = float(account["equity"])
    proposed_risk_amount = _virtual_size_usd(request) * float(request.risk_percent or 1.0) / 100
    return portfolio_risk_service.evaluate(
        PortfolioRiskContext(
            account_equity=equity,
            proposed_risk_amount=proposed_risk_amount,
            open_risk_amount=_forward_positions_risk(open_positions),
            symbol_open_risk_amount=_forward_positions_risk(open_positions, symbol=signal.symbol),
            strategy_open_risk_amount=_forward_positions_risk(open_positions, strategy=signal.strategy),
            daily_loss_amount=max(0.0, -float(account["realized_pnl"])),
            account_drawdown_percent=_forward_account_drawdown_percent(account),
            open_position_count=len(open_positions),
            strategy_losses_today=_forward_strategy_losses_today(run, signal.strategy),
        ),
        PortfolioRiskLimits(
            max_open_risk_percent=risk_settings.max_open_risk_percent,
            max_symbol_risk_percent=risk_settings.max_symbol_risk_percent,
            max_strategy_exposure_percent=risk_settings.max_strategy_exposure_percent,
            max_correlated_risk_percent=0.0,
            max_daily_loss_percent=risk_settings.max_daily_loss_percent,
            max_account_drawdown_percent=risk_settings.max_account_drawdown_percent,
            max_concurrent_positions=request.max_open_positions,
            max_strategy_losses_per_day=risk_settings.max_strategy_losses_per_day,
        ),
    )


def _request_with_portfolio_size(
    request: ManualConfirmRequest,
    decision: PortfolioRiskDecision,
) -> ManualConfirmRequest:
    metadata = {
        **request.metadata,
        "portfolio_risk": _portfolio_decision_metadata(decision),
    }
    return request.model_copy(
        update={
            "size_usd": max(0.0, _virtual_size_usd(request) * decision.size_multiplier),
            "metadata": metadata,
        }
    )


def _gate_blocked_by_portfolio(
    gate: SignalExecutionGateSnapshot,
    decision: PortfolioRiskDecision,
) -> SignalExecutionGateSnapshot:
    reason = _portfolio_gate_reason(decision, severity="blocker")
    return gate.model_copy(
        update={
            "status": "blocked",
            "feed_kind": "blocked",
            "can_notify": False,
            "can_enter_now": False,
            "can_arm_pending": False,
            "can_show_in_execution_feed": False,
            "reasons": [*gate.reasons, reason],
            "metadata": {
                **gate.metadata,
                "portfolio_risk": _portfolio_decision_metadata(decision),
            },
        }
    )


def _gate_with_portfolio_warning(
    gate: SignalExecutionGateSnapshot,
    decision: PortfolioRiskDecision,
) -> SignalExecutionGateSnapshot:
    reason = _portfolio_gate_reason(decision, severity="warning")
    return gate.model_copy(
        update={
            "warnings": [*gate.warnings, reason],
            "metadata": {
                **gate.metadata,
                "portfolio_risk": _portfolio_decision_metadata(decision),
            },
        }
    )


def _portfolio_gate_reason(
    decision: PortfolioRiskDecision,
    *,
    severity: Literal["blocker", "warning"],
) -> SignalExecutionGateReason:
    return SignalExecutionGateReason(
        code=decision.reason_code,
        severity=severity,
        source="portfolio_risk",
        message=decision.message,
        metadata=_portfolio_decision_metadata(decision),
    )


def _portfolio_decision_metadata(decision: PortfolioRiskDecision) -> dict[str, Any]:
    return {
        "action": decision.action,
        "reason_code": decision.reason_code,
        "reason_codes": list(decision.reason_codes),
        "proposed_risk_amount": decision.proposed_risk_amount,
        "approved_risk_amount": decision.approved_risk_amount,
        "size_multiplier": decision.size_multiplier,
        "metrics": dict(decision.metrics),
    }


def _strategy_test_trade_from_virtual_trade(
    *,
    run: StrategyTestRunResponse,
    signal: RadarSignal,
    trade: VirtualTrade,
) -> StrategyTestTrade:
    entry_time = trade.opened_at.astimezone(timezone.utc)
    exit_time = trade.closed_at.astimezone(timezone.utc) if trade.closed_at else None
    pnl = _decimal(trade.pnl if trade.pnl is not None else trade.realized_pnl, Decimal("0"))
    fees = _decimal(trade.fees, Decimal("0")) + _decimal(trade.exit_fees, Decimal("0"))
    return StrategyTestTrade(
        run_id=run.run_id,
        trade_id=trade.id,
        user_id=strategy_test_user_uuid(_matrix_user_id(run)),
        mode=_matrix_mode(run),
        strategy_code=signal.strategy,
        strategy_version=str(signal.trade_plan.metadata.get("strategy_version", "")) if signal.trade_plan else "",
        exchange=signal.exchange,
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        direction=signal.direction,
        signal_score=float(signal.score),
        market_regime=_market_regime(signal),
        score_bucket=_score_bucket(signal.score),
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=_decimal(trade.entry_price, Decimal("0")),
        exit_price=_optional_decimal(trade.exit_price),
        stop_loss=_optional_decimal(trade.stop_loss),
        targets=[{"price": price} for price in trade.take_profit],
        selected_rr=signal.selected_rr or signal.risk_reward,
        realized_r=None,
        pnl=pnl,
        pnl_pct=float(trade.pnl_percent or 0.0),
        fees=fees,
        slippage=_decimal(trade.slippage_bps, Decimal("0")),
        close_reason=trade.close_reason or ("open" if exit_time is None else "closed"),
        outcome=trade.result or trade.status,
        risk_rejected=False,
        execution_rejected=False,
        warnings=[],
        features_snapshot=signal.model_dump(mode="json", exclude={"card_view", "details_view"}),
        trade_plan=signal.trade_plan.model_dump(mode="json") if signal.trade_plan else {},
        tags=_run_tags(run),
        created_at=entry_time,
    )


def _strategy_test_metric_from_virtual_trade(
    *,
    run: StrategyTestRunResponse,
    signal: RadarSignal,
    trade: VirtualTrade,
) -> StrategyTestMetricRow:
    return StrategyTestMetricRow(
        run_id=run.run_id,
        user_id=strategy_test_user_uuid(_matrix_user_id(run)),
        mode=_matrix_mode(run),
        strategy_code=signal.strategy,
        exchange=signal.exchange,
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        market_regime=_market_regime(signal),
        score_bucket=_score_bucket(signal.score),
        direction=signal.direction,
        metric_code="forward_opened_trades",
        metric_value=1.0,
        sample_size=1,
        metadata={
            "signal_id": signal.id,
            "trade_id": trade.id,
            "test_type": "forward_virtual",
        },
        created_at=trade.opened_at.astimezone(timezone.utc),
    )


def _matrix_user_id(run: StrategyTestRunResponse) -> str:
    return str(run.requested_matrix.get("user_id") or "demo_user")


def _matrix_mode(run: StrategyTestRunResponse) -> str:
    value = str(run.requested_matrix.get("mode") or "research_virtual")
    if value in {"discovery", "research_virtual", "production_like"}:
        return value
    return "research_virtual"


def _run_tags(run: StrategyTestRunResponse) -> list[str]:
    tags = run.requested_matrix.get("tags")
    result = [str(tag) for tag in tags] if isinstance(tags, list) else []
    for tag in ("forward_virtual", "strategy_test"):
        if tag not in result:
            result.append(tag)
    return result


def _market_regime(signal: RadarSignal) -> str:
    if signal.regime is not None:
        return signal.regime.primary_label
    return "unknown"


def _score_bucket(score: int | float | None) -> str:
    return score_bucket_for(score)


def _forward_signal_id(run: StrategyTestRunResponse, signal: StrategySignal) -> str:
    suffix = uuid5(
        NAMESPACE_URL,
        "|".join(
            [
                str(run.run_id),
                signal.exchange.strip().lower(),
                signal.symbol.strip().upper(),
                signal.strategy,
                signal.timeframe,
                signal.direction,
                str(signal.timestamp),
            ]
        ),
    ).hex
    return f"forward_sig_{suffix}"


def _forward_signal_key(run: StrategyTestRunResponse, signal: RadarSignal) -> str:
    return "|".join(
        [
            str(run.run_id),
            signal.exchange.strip().lower(),
            signal.symbol.strip().upper(),
            signal.strategy,
            signal.timeframe,
            signal.direction,
            signal.created_at.astimezone(timezone.utc).isoformat(),
        ]
    )


def _forward_trade_id(signal_id: str) -> str:
    if signal_id.startswith("forward_sig_"):
        return f"forward_trade_{signal_id.removeprefix('forward_sig_')}"
    return f"forward_trade_{uuid5(NAMESPACE_URL, signal_id).hex}"


def _forward_close_reason(position: dict[str, Any], price: Decimal, side: str) -> str | None:
    stop_loss = _decimal(position.get("stop_loss"), Decimal("0"))
    take_profit = [
        _decimal(target, Decimal("0"))
        for target in (position.get("take_profit") if isinstance(position.get("take_profit"), list) else [])
    ]
    take_profit = [target for target in take_profit if target > 0]
    if side == "short":
        if stop_loss > 0 and price >= stop_loss:
            return "stop_loss"
        if any(price <= target for target in take_profit):
            return "take_profit"
        return None
    if stop_loss > 0 and price <= stop_loss:
        return "stop_loss"
    if any(price >= target for target in take_profit):
        return "take_profit"
    return None


def _entry_price(signal: RadarSignal) -> float:
    for value in (signal.entry_min, signal.entry_max, signal.take_profit_1, signal.stop_loss):
        price = _decimal(value, Decimal("0"))
        if price > 0:
            return float(price)
    return 1.0


def _virtual_size_usd(request: ManualConfirmRequest) -> float:
    if request.size_usd is not None:
        return float(request.size_usd)
    account_balance = _decimal(request.account_balance, Decimal("100"))
    return float(max(Decimal("1"), min(account_balance, Decimal("100"))))


def _signal_timestamp_to_utc(value: int | float) -> datetime:
    timestamp = float(value)
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _forward_account_from_runtime(run: StrategyTestRunResponse) -> dict[str, Any]:
    account = run.runtime_state.get("forward_account")
    if not isinstance(account, dict):
        initial = _decimal(run.requested_matrix.get("initial_capital"), Decimal("1000"))
        account = _serialize_forward_account(
            {
                "initial_capital": initial,
                "balance": initial,
                "equity": initial,
                "realized_pnl": Decimal("0"),
                "unrealized_pnl": Decimal("0"),
                "fees": Decimal("0"),
                "slippage": Decimal("0"),
                "open_positions": 0,
                "closed_positions": 0,
            }
        )
    return {
        "initial_capital": _decimal(account.get("initial_capital"), Decimal("1000")),
        "balance": _decimal(account.get("balance"), Decimal("1000")),
        "equity": _decimal(account.get("equity"), Decimal("1000")),
        "realized_pnl": _decimal(account.get("realized_pnl"), Decimal("0")),
        "unrealized_pnl": _decimal(account.get("unrealized_pnl"), Decimal("0")),
        "fees": _decimal(account.get("fees"), Decimal("0")),
        "slippage": _decimal(account.get("slippage"), Decimal("0")),
        "open_positions": _counter(account, "open_positions"),
        "closed_positions": _counter(account, "closed_positions"),
    }


def _serialize_forward_account(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "initial_capital": _decimal_string(_decimal(account.get("initial_capital"), Decimal("1000"))),
        "balance": _decimal_string(_decimal(account.get("balance"), Decimal("1000"))),
        "equity": _decimal_string(_decimal(account.get("equity"), Decimal("1000"))),
        "realized_pnl": _decimal_string(_decimal(account.get("realized_pnl"), Decimal("0"))),
        "unrealized_pnl": _decimal_string(_decimal(account.get("unrealized_pnl"), Decimal("0"))),
        "fees": _decimal_string(_decimal(account.get("fees"), Decimal("0"))),
        "slippage": _decimal_string(_decimal(account.get("slippage"), Decimal("0"))),
        "open_positions": int(account.get("open_positions") or 0),
        "closed_positions": int(account.get("closed_positions") or 0),
    }


def _forward_positions(run: StrategyTestRunResponse) -> list[dict[str, Any]]:
    raw_positions = run.runtime_state.get("forward_positions")
    if not isinstance(raw_positions, list):
        return []
    return [dict(position) for position in raw_positions if isinstance(position, dict)]


def _open_forward_positions(run: StrategyTestRunResponse) -> list[dict[str, Any]]:
    return [
        position
        for position in _forward_positions(run)
        if str(position.get("status") or "open").lower() == "open"
    ]


def _forward_positions_risk(
    positions: Sequence[dict[str, Any]],
    *,
    symbol: str | None = None,
    strategy: str | None = None,
) -> float:
    symbol_key = symbol.strip().upper() if symbol is not None else None
    strategy_key = strategy.strip() if strategy is not None else None
    return float(
        sum(
            _forward_position_risk(position)
            for position in positions
            if (symbol_key is None or str(position.get("symbol") or "").strip().upper() == symbol_key)
            and (strategy_key is None or str(position.get("strategy") or "").strip() == strategy_key)
        )
    )


def _forward_position_risk(position: dict[str, Any]) -> Decimal:
    risk_amount = _decimal(position.get("risk_amount"), Decimal("0"))
    if risk_amount > 0:
        return risk_amount
    size_usd = _decimal(position.get("size_usd"), Decimal("0"))
    risk_percent = _decimal(position.get("risk_percent"), Decimal("0"))
    if size_usd > 0 and risk_percent > 0:
        return size_usd * risk_percent / Decimal("100")
    return Decimal("0")


def _forward_strategy_losses_today(run: StrategyTestRunResponse, strategy: str) -> int:
    strategy_key = strategy.strip()
    losses = 0
    for position in _forward_positions(run):
        if str(position.get("strategy") or "").strip() != strategy_key:
            continue
        if str(position.get("status") or "open").lower() == "open":
            continue
        if _decimal(position.get("realized_pnl"), Decimal("0")) < 0:
            losses += 1
    return losses


def _forward_account_drawdown_percent(account: dict[str, Any]) -> float:
    initial = _decimal(account.get("initial_capital"), Decimal("0"))
    equity = _decimal(account.get("equity"), Decimal("0"))
    if initial <= 0 or equity >= initial:
        return 0.0
    return float((initial - equity) / initial * Decimal("100"))


def _forward_risk_settings(run: StrategyTestRunResponse) -> RiskManagementSettings:
    params = _run_params(run)
    raw_settings = params.get("risk_settings")
    if isinstance(raw_settings, dict):
        return RiskManagementSettings(**raw_settings)
    return RiskManagementSettings()


def _forward_max_concurrent_positions(run: StrategyTestRunResponse) -> int:
    params = _run_params(run)
    for key in ("max_concurrent_positions", "max_open_positions"):
        value = params.get(key)
        if value is None:
            continue
        try:
            return max(1, min(100, int(value)))
        except (TypeError, ValueError):
            continue
    return 3


def _run_params(run: StrategyTestRunResponse) -> dict[str, Any]:
    params = run.requested_matrix.get("params")
    return dict(params) if isinstance(params, dict) else {}


def _first_gate_reason_code(gate: SignalExecutionGateSnapshot) -> str | None:
    for reason in [*gate.reasons, *gate.warnings]:
        if reason.code:
            return reason.code
    return None


def _gate_has_reason_source(gate: SignalExecutionGateSnapshot, sources: set[str]) -> bool:
    return any(reason.source in sources for reason in [*gate.reasons, *gate.warnings])


def _counter(state: dict[str, Any], key: str) -> int:
    try:
        return int(state.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _decimal(value: Any, default: Decimal) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _decimal_string(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, Decimal("0"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)
