from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Protocol, Sequence
from uuid import UUID

from app.schemas.candle import OHLCVCandle
from app.schemas.signal import StrategySignal
from app.services.candle_service import candle_service
from app.services.feature_engine import FeatureEngine
from app.strategies.engine import StrategyEngine
from app.services.strategy_testing.schemas import (
    StrategyTestRunRequest,
    StrategyTestSignal,
    StrategyTestTrade,
)


@dataclass(frozen=True)
class ForwardTestSignalBatch:
    candle: OHLCVCandle
    signals: list[StrategySignal] = field(default_factory=list)


@dataclass(frozen=True)
class StrategyForwardTestResult:
    summary: dict[str, Any]
    runtime_state: dict[str, Any]
    signals: list[StrategyTestSignal] = field(default_factory=list)
    trades: list[StrategyTestTrade] = field(default_factory=list)


class ForwardTestSignalProvider(Protocol):
    def load_batches(
        self,
        *,
        request: StrategyTestRunRequest,
        runtime_state: dict[str, Any],
    ) -> list[ForwardTestSignalBatch]:
        ...


class ClosedCandleForwardSignalProvider:
    """Safe default provider: advances on closed candles without publishing radar signals."""

    def __init__(
        self,
        *,
        feature_engine: FeatureEngine | None = None,
        strategy_engine: StrategyEngine | None = None,
    ) -> None:
        self._feature_engine = feature_engine or FeatureEngine()
        self._strategy_engine = strategy_engine or StrategyEngine()

    def load_batches(
        self,
        *,
        request: StrategyTestRunRequest,
        runtime_state: dict[str, Any],
    ) -> list[ForwardTestSignalBatch]:
        _ = runtime_state
        batches: list[ForwardTestSignalBatch] = []
        for pair in request.pairs:
            for timeframe in request.timeframes:
                candles = candle_service.list_candles(
                    exchange=pair.exchange,
                    symbol=pair.symbol,
                    timeframe=timeframe,
                    include_open=False,
                    limit=250,
                )
                for candle in candles:
                    window = [item for item in candles if item.open_time <= candle.open_time]
                    features = self._feature_engine.process_candles(window)
                    signals = []
                    if features is not None:
                        signals = _run_async_sync(
                            self._strategy_engine.generate_signals(
                                features,
                                strategy_configs=_strategy_configs_for_request(request),
                                rr_guard_context=request.mode,
                            )
                        )
                    batches.append(ForwardTestSignalBatch(candle=candle, signals=signals))
        return batches


class StrategyForwardTestRunner:
    def __init__(
        self,
        *,
        radar_signal_writer: Any | None = None,
        signal_provider: ForwardTestSignalProvider | None = None,
    ) -> None:
        self._radar_signal_writer = radar_signal_writer
        self._signal_provider = signal_provider or ClosedCandleForwardSignalProvider()

    def run_once(
        self,
        *,
        run_id: UUID,
        user_uuid: UUID,
        request: StrategyTestRunRequest,
        runtime_state: dict[str, Any] | None = None,
    ) -> StrategyForwardTestResult:
        state = _initial_runtime_state(request, runtime_state or {})
        result_signals: list[StrategyTestSignal] = []
        result_trades: list[StrategyTestTrade] = []
        signal_rows_by_id: dict[str, StrategyTestSignal] = {}

        for batch in self._signal_provider.load_batches(request=request, runtime_state=state):
            candle_key = _candle_key(batch.candle)
            if candle_key in state["seen_candle_keys"]:
                continue
            state["seen_candle_keys"].append(candle_key)
            state["last_tick_at"] = _datetime_from_ms(batch.candle.close_time).isoformat()

            closed = _advance_positions(
                state=state,
                run_id=run_id,
                user_uuid=user_uuid,
                request=request,
                candle=batch.candle,
                signal_rows_by_id=signal_rows_by_id,
            )
            result_trades.extend(closed)

            for signal in batch.signals:
                signal_id = _forward_signal_id(signal)
                if _dedup_key(signal) in state["signal_dedup_keys"]:
                    continue
                state["signal_dedup_keys"].append(_dedup_key(signal))
                state["signals_seen"] += 1
                state["last_signal_at"] = _datetime_from_ms(batch.candle.close_time).isoformat()
                row = _signal_row(
                    run_id=run_id,
                    user_uuid=user_uuid,
                    request=request,
                    signal=signal,
                    signal_id=signal_id,
                    candle=batch.candle,
                )
                signal_rows_by_id[signal_id] = row

                if _is_execution_candidate(signal):
                    state["execution_candidates"] += 1
                else:
                    state["blocked_signals"] += 1
                    row.outcome = "blocked"
                    row.outcome_reason = "execution_gate_blocked"
                    result_signals.append(row)
                    continue

                if request.mode == "discovery":
                    row.outcome = "recorded"
                    row.outcome_reason = "discovery_mode"
                    result_signals.append(row)
                    continue

                if _entry_touched(signal, batch.candle) and _can_enter_now(signal):
                    _open_position(state, request=request, signal=signal, signal_id=signal_id, candle=batch.candle)
                    row.outcome = "filled"
                    row.outcome_reason = "virtual_entry_filled"
                    row.entry_touched = True
                    row.filled = True
                    row.bars_to_entry = 0
                    state["filled_trades"] += 1
                elif _can_arm_pending(signal):
                    if _pending_expires_immediately(request):
                        row.outcome = "no_entry"
                        row.outcome_reason = "expired_before_touch"
                        row.no_entry = True
                        state["no_entry"] += 1
                    else:
                        _add_pending_entry(state, request=request, signal=signal, signal_id=signal_id, candle=batch.candle)
                        row.outcome = "pending"
                        row.outcome_reason = "waiting_for_entry_touch"
                else:
                    row.outcome = "execution_rejected"
                    row.outcome_reason = "execution_gate_blocked"
                    row.execution_rejected = True
                    state["execution_rejections"] += 1
                result_signals.append(row)

            _expire_pending_entries(state, request=request, candle=batch.candle, signal_rows_by_id=signal_rows_by_id)

        summary = _summary_from_state(state, request=request)
        return StrategyForwardTestResult(
            summary=summary,
            runtime_state=state,
            signals=result_signals,
            trades=result_trades,
        )


def _initial_runtime_state(request: StrategyTestRunRequest, runtime_state: dict[str, Any]) -> dict[str, Any]:
    state = dict(runtime_state)
    defaults: dict[str, Any] = {
        "seen_candle_keys": [],
        "signal_dedup_keys": [],
        "pending_entries": [],
        "open_positions": [],
        "closed_trade_ids": [],
        "signals_seen": 0,
        "execution_candidates": 0,
        "blocked_signals": 0,
        "filled_trades": 0,
        "no_entry": 0,
        "risk_rejections": 0,
        "execution_rejections": 0,
        "realized_pnl": 0.0,
        "current_equity": float(request.initial_capital),
        "last_tick_at": None,
        "last_signal_at": None,
    }
    for key, value in defaults.items():
        state.setdefault(key, value)
    return state


def _advance_positions(
    *,
    state: dict[str, Any],
    run_id: UUID,
    user_uuid: UUID,
    request: StrategyTestRunRequest,
    candle: OHLCVCandle,
    signal_rows_by_id: dict[str, StrategyTestSignal],
) -> list[StrategyTestTrade]:
    remaining: list[dict[str, Any]] = []
    closed: list[StrategyTestTrade] = []
    for position in state["open_positions"]:
        close_reason = _position_close_reason(position, candle)
        if close_reason is None:
            remaining.append(position)
            continue
        trade = _trade_row(
            run_id=run_id,
            user_uuid=user_uuid,
            request=request,
            position=position,
            candle=candle,
            close_reason=close_reason,
        )
        closed.append(trade)
        state["closed_trade_ids"].append(trade.trade_id)
        state["realized_pnl"] = float(Decimal(str(state["realized_pnl"])) + trade.pnl)
        state["current_equity"] = float(Decimal(str(request.initial_capital)) + Decimal(str(state["realized_pnl"])))
        row = signal_rows_by_id.get(position["signal_id"])
        if row is not None:
            row.outcome = close_reason
            row.outcome_reason = close_reason
            row.bars_to_outcome = max(1, int(position.get("bars_in_trade", 0)) + 1)
    state["open_positions"] = remaining
    return closed


def _open_position(
    state: dict[str, Any],
    *,
    request: StrategyTestRunRequest,
    signal: StrategySignal,
    signal_id: str,
    candle: OHLCVCandle,
) -> None:
    entry_price = Decimal(str(candle.close))
    state["open_positions"].append(
        {
            "signal_id": signal_id,
            "trade_id": f"fwd_trade_{signal_id}",
            "strategy_code": signal.strategy,
            "strategy_version": _strategy_version(request, signal.strategy),
            "exchange": signal.exchange,
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "direction": signal.direction.lower(),
            "signal_score": signal.score,
            "entry_time": _datetime_from_ms(candle.close_time).isoformat(),
            "entry_price": str(entry_price),
            "stop_loss": str(signal.stop_loss) if signal.stop_loss is not None else None,
            "target_1": str(signal.take_profit_1) if signal.take_profit_1 is not None else None,
            "selected_rr": signal.selected_rr,
            "bars_in_trade": 0,
        }
    )


def _add_pending_entry(
    state: dict[str, Any],
    *,
    request: StrategyTestRunRequest,
    signal: StrategySignal,
    signal_id: str,
    candle: OHLCVCandle,
) -> None:
    max_pending_minutes = _int_param(request.params, "max_pending_minutes", 60)
    expires_at = _datetime_from_ms(candle.close_time) + timedelta(minutes=max_pending_minutes)
    state["pending_entries"].append(
        {
            "signal_id": signal_id,
            "dedup_key": _dedup_key(signal),
            "entry_min": signal.entry_min,
            "entry_max": signal.entry_max,
            "expires_at": expires_at.isoformat(),
        }
    )


def _expire_pending_entries(
    state: dict[str, Any],
    *,
    request: StrategyTestRunRequest,
    candle: OHLCVCandle,
    signal_rows_by_id: dict[str, StrategyTestSignal],
) -> None:
    _ = request
    now = _datetime_from_ms(candle.close_time)
    pending: list[dict[str, Any]] = []
    for entry in state["pending_entries"]:
        expires_at = _datetime_from_iso(entry.get("expires_at"))
        if expires_at is not None and expires_at <= now:
            row = signal_rows_by_id.get(str(entry.get("signal_id")))
            if row is not None:
                row.outcome = "no_entry"
                row.outcome_reason = "expired_before_touch"
                row.no_entry = True
            state["no_entry"] += 1
            continue
        pending.append(entry)
    state["pending_entries"] = pending


def _signal_row(
    *,
    run_id: UUID,
    user_uuid: UUID,
    request: StrategyTestRunRequest,
    signal: StrategySignal,
    signal_id: str,
    candle: OHLCVCandle,
) -> StrategyTestSignal:
    gate = signal.execution_gate
    return StrategyTestSignal(
        run_id=run_id,
        user_id=user_uuid,
        mode=request.mode,
        scenario_id=f"{signal.strategy}:{signal.exchange}:{signal.symbol}:{signal.timeframe}",
        strategy_code=signal.strategy,
        strategy_version=_strategy_version(request, signal.strategy),
        exchange=signal.exchange,
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        direction=signal.direction.lower(),
        signal_id=signal_id,
        signal_time=_datetime_from_ms(candle.close_time),
        signal_score=float(signal.score) if signal.score is not None else None,
        feed_kind=str(gate.feed_kind) if gate is not None else "unknown",
        gate_status=str(gate.status) if gate is not None else "unknown",
        status=str(signal.status),
        trigger_passed=bool(signal.trigger and signal.trigger.passed),
        edge_status=str(signal.edge.status) if signal.edge is not None else "unknown",
        selected_rr=signal.selected_rr,
        entry_min=_optional_decimal(signal.entry_min),
        entry_max=_optional_decimal(signal.entry_max),
        stop_loss=_optional_decimal(signal.stop_loss),
        target_1=_optional_decimal(signal.take_profit_1),
        outcome="generated",
        outcome_reason="generated",
        metadata={"test_type": request.test_type},
        created_at=datetime.now(timezone.utc),
    )


def _trade_row(
    *,
    run_id: UUID,
    user_uuid: UUID,
    request: StrategyTestRunRequest,
    position: dict[str, Any],
    candle: OHLCVCandle,
    close_reason: str,
) -> StrategyTestTrade:
    entry_price = Decimal(str(position["entry_price"]))
    exit_price = Decimal(str(candle.close if close_reason != "stop_loss" else position.get("stop_loss") or candle.close))
    direction_sign = Decimal("1") if position["direction"] == "long" else Decimal("-1")
    notional = Decimal(str(request.initial_capital)) * Decimal("0.1")
    quantity = notional / entry_price if entry_price else Decimal("0")
    gross_pnl = (exit_price - entry_price) * quantity * direction_sign
    fees = notional * Decimal(str(request.fee_rate)) * Decimal("2")
    pnl = gross_pnl - fees
    return StrategyTestTrade(
        run_id=run_id,
        trade_id=str(position["trade_id"]),
        user_id=user_uuid,
        mode=request.mode,
        strategy_code=str(position["strategy_code"]),
        strategy_version=str(position["strategy_version"]),
        exchange=str(position["exchange"]),
        symbol=str(position["symbol"]),
        timeframe=str(position["timeframe"]),
        direction=str(position["direction"]),
        signal_score=float(position["signal_score"]) if position.get("signal_score") is not None else None,
        market_regime="unknown",
        score_bucket=_score_bucket(position.get("signal_score")),
        entry_time=_datetime_from_iso(position["entry_time"]) or _datetime_from_ms(candle.open_time),
        exit_time=_datetime_from_ms(candle.close_time),
        entry_price=entry_price,
        exit_price=exit_price,
        stop_loss=_optional_decimal(position.get("stop_loss")),
        targets=[{"label": "tp1", "price": position["target_1"]}] if position.get("target_1") else [],
        selected_rr=float(position["selected_rr"]) if position.get("selected_rr") is not None else None,
        realized_r=-1.0 if close_reason == "stop_loss" else None,
        pnl=pnl,
        pnl_pct=float((pnl / Decimal(str(request.initial_capital))) * Decimal("100")),
        fees=fees,
        slippage=Decimal("0"),
        bars_to_entry=0,
        bars_in_trade=max(1, int(position.get("bars_in_trade", 0)) + 1),
        close_reason=close_reason,
        outcome=close_reason,
        features_snapshot={"test_type": request.test_type},
        trade_plan={},
        tags=_unique_tags([*request.tags, "forward_test"]),
        created_at=datetime.now(timezone.utc),
    )


def _summary_from_state(state: dict[str, Any], *, request: StrategyTestRunRequest) -> dict[str, Any]:
    unrealized = Decimal("0")
    for position in state["open_positions"]:
        unrealized += Decimal("0")
    return {
        "test_type": request.test_type,
        "signals_seen": int(state["signals_seen"]),
        "execution_candidates": int(state["execution_candidates"]),
        "blocked_signals": int(state["blocked_signals"]),
        "pending_entries": len(state["pending_entries"]),
        "entry_touched": int(state["filled_trades"]),
        "filled_trades": int(state["filled_trades"]),
        "open_positions": len(state["open_positions"]),
        "closed_trades": len(state["closed_trade_ids"]),
        "no_entry": int(state["no_entry"]),
        "risk_rejections": int(state["risk_rejections"]),
        "execution_rejections": int(state["execution_rejections"]),
        "current_equity": float(state["current_equity"]),
        "realized_pnl": float(state["realized_pnl"]),
        "unrealized_pnl": float(unrealized),
        "last_tick_at": state.get("last_tick_at"),
        "last_signal_at": state.get("last_signal_at"),
    }


def _position_close_reason(position: dict[str, Any], candle: OHLCVCandle) -> str | None:
    stop_loss = _optional_decimal(position.get("stop_loss"))
    if stop_loss is not None:
        if position.get("direction") == "long" and Decimal(str(candle.low)) <= stop_loss:
            return "stop_loss"
        if position.get("direction") == "short" and Decimal(str(candle.high)) >= stop_loss:
            return "stop_loss"
    return None


def _entry_touched(signal: StrategySignal, candle: OHLCVCandle) -> bool:
    entry_min = _optional_decimal(signal.entry_min)
    entry_max = _optional_decimal(signal.entry_max)
    if entry_min is None or entry_max is None:
        return True
    close = Decimal(str(candle.close))
    return entry_min <= close <= entry_max


def _is_execution_candidate(signal: StrategySignal) -> bool:
    gate = signal.execution_gate
    if signal.status != "actionable" or gate is None:
        return False
    return gate.feed_kind == "execution_signal" and gate.can_show_in_execution_feed


def _can_enter_now(signal: StrategySignal) -> bool:
    gate = signal.execution_gate
    return bool(gate and gate.can_enter_now)


def _can_arm_pending(signal: StrategySignal) -> bool:
    gate = signal.execution_gate
    return bool(gate and gate.can_arm_pending)


def _pending_expires_immediately(request: StrategyTestRunRequest) -> bool:
    return _int_param(request.params, "max_pending_minutes", 60) <= 0


def _forward_signal_id(signal: StrategySignal) -> str:
    if signal.execution_gate and signal.execution_gate.metadata.get("signal_id"):
        return str(signal.execution_gate.metadata["signal_id"])
    if signal.explanation:
        return str(signal.explanation[0])
    return f"fwd_sig_{signal.exchange}_{signal.symbol}_{signal.timeframe}_{signal.direction}_{signal.timestamp}"


def _dedup_key(signal: StrategySignal) -> str:
    return ":".join([
        signal.exchange,
        signal.symbol,
        signal.timeframe,
        signal.direction,
        str(signal.timestamp),
        _forward_signal_id(signal),
    ])


def _candle_key(candle: OHLCVCandle) -> str:
    return f"{candle.exchange}:{candle.symbol}:{candle.timeframe}:{candle.open_time}"


def _strategy_version(request: StrategyTestRunRequest, strategy: str) -> str:
    versions = request.params.get("strategy_versions")
    if isinstance(versions, dict) and versions.get(strategy):
        return str(versions[strategy])
    return str(request.params.get("strategy_version") or "v1")


def _datetime_from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _datetime_from_iso(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _int_param(params: dict[str, Any], key: str, default: int) -> int:
    value = params.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _score_bucket(value: Any) -> str:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return "unknown"
    lower = max(0, min(100, score)) // 10 * 10
    return f"{lower}-{min(100, lower + 9)}"


def _unique_tags(values: Sequence[str]) -> list[str]:
    tags: list[str] = []
    for value in values:
        if value not in tags:
            tags.append(value)
    return tags


def _strategy_configs_for_request(request: StrategyTestRunRequest) -> dict[str, Any]:
    return {
        strategy: SimpleNamespace(params={}, risk_settings={})
        for strategy in request.strategies
    }


def _run_async_sync(awaitable: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("forward_runner_async_context: call StrategyForwardTestRunner from a worker thread")
