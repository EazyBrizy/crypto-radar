from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.schemas.signal import RadarSignal
from app.schemas.trade import (
    ExecutionQualityGate,
    ImpactRisk,
    LiquidityMetrics,
    ManualConfirmRequest,
    OrderBookLevel,
    VirtualExecutionReport,
    VirtualMarketSnapshot,
    VirtualSimulationMode,
)


class VirtualExecutionRejected(ValueError):
    def __init__(self, report: VirtualExecutionReport) -> None:
        self.report = report
        super().__init__(
            report.quality_gate.message
            or report.rejected_reason
            or "Virtual execution rejected"
        )


@dataclass(frozen=True)
class _BookWalk:
    filled_size_usd: float
    quantity: float
    unfilled_size_usd: float
    average_price: float | None
    book_price_after: float | None
    market_impact_percent: float


class VirtualExecutionEngine:
    """Simulates whether a virtual market order could be executed realistically."""

    def simulate_entry(
        self,
        *,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        reference_price: float,
        requested_size_usd: float,
    ) -> VirtualExecutionReport:
        snapshot = request.market_snapshot
        metrics = self._liquidity_metrics(
            snapshot=snapshot,
            signal=signal,
            reference_price=reference_price,
            requested_size_usd=requested_size_usd,
        )
        mode = self._choose_mode(
            request=request,
            signal=signal,
            snapshot=snapshot,
            metrics=metrics,
            requested_size_usd=requested_size_usd,
        )
        if mode == "passive":
            report = self._simulate_passive(
                request=request,
                snapshot=snapshot,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                buy_side=signal.direction == "long",
            )
        else:
            report = self._simulate_impact_aware(
                request=request,
                snapshot=snapshot,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                buy_side=signal.direction == "long",
            )
        return self._apply_quality_gate(report)

    def _simulate_passive(
        self,
        *,
        request: ManualConfirmRequest,
        snapshot: VirtualMarketSnapshot | None,
        metrics: LiquidityMetrics,
        reference_price: float,
        requested_size_usd: float,
        buy_side: bool,
    ) -> VirtualExecutionReport:
        spread_slippage_bps = metrics.spread_percent * 50
        entry_slippage_bps = max(request.slippage_bps, spread_slippage_bps)
        average_price = _apply_price_slippage(reference_price, buy_side, entry_slippage_bps)
        best_bid, best_ask = _best_prices(snapshot)
        return VirtualExecutionReport(
            mode="passive",
            status="filled",
            requested_size_usd=requested_size_usd,
            filled_size_usd=requested_size_usd,
            unfilled_size_usd=0.0,
            fill_ratio=1.0,
            reference_price=reference_price,
            average_price=average_price,
            entry_slippage_bps=entry_slippage_bps,
            exit_slippage_bps=entry_slippage_bps,
            market_impact_percent=0.0,
            best_bid_before=best_bid,
            best_ask_before=best_ask,
            liquidity=metrics,
            notes=["Passive simulation: own order impact is assumed negligible."],
        )

    def _simulate_impact_aware(
        self,
        *,
        request: ManualConfirmRequest,
        snapshot: VirtualMarketSnapshot | None,
        metrics: LiquidityMetrics,
        reference_price: float,
        requested_size_usd: float,
        buy_side: bool,
    ) -> VirtualExecutionReport:
        best_bid, best_ask = _best_prices(snapshot)
        levels = _execution_levels(snapshot, buy_side)
        if levels:
            return self._simulate_against_orderbook(
                request=request,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                buy_side=buy_side,
                best_bid=best_bid,
                best_ask=best_ask,
                levels=levels,
            )
        return self._simulate_from_metrics(
            request=request,
            metrics=metrics,
            reference_price=reference_price,
            requested_size_usd=requested_size_usd,
            buy_side=buy_side,
            best_bid=best_bid,
            best_ask=best_ask,
        )

    def _simulate_against_orderbook(
        self,
        *,
        request: ManualConfirmRequest,
        metrics: LiquidityMetrics,
        reference_price: float,
        requested_size_usd: float,
        buy_side: bool,
        best_bid: float | None,
        best_ask: float | None,
        levels: list[OrderBookLevel],
    ) -> VirtualExecutionReport:
        walk = _walk_book(
            levels=levels,
            buy_side=buy_side,
            reference_price=reference_price,
            requested_size_usd=requested_size_usd,
            max_slippage_bps=request.max_virtual_slippage_bps,
        )
        if walk.filled_size_usd <= 0 or walk.average_price is None:
            return self._rejected_report(
                mode="impact_aware",
                request=request,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                best_bid=best_bid,
                best_ask=best_ask,
                reason="insufficient_liquidity",
            )

        fill_ratio = min(walk.filled_size_usd / requested_size_usd, 1.0) if requested_size_usd else 0.0
        if walk.unfilled_size_usd > 0 and (not request.allow_partial_fill or fill_ratio < request.min_fill_ratio):
            return self._rejected_report(
                mode="impact_aware",
                request=request,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                best_bid=best_bid,
                best_ask=best_ask,
                reason="insufficient_liquidity",
            )

        entry_slippage_bps = _slippage_bps(reference_price, walk.average_price, buy_side)
        exit_slippage_bps = _exit_slippage_bps(
            entry_slippage_bps=entry_slippage_bps,
            market_impact_percent=walk.market_impact_percent,
            metrics=metrics,
            max_virtual_slippage_bps=request.max_virtual_slippage_bps,
        )
        status = "filled" if walk.unfilled_size_usd <= 0.000001 else "partially_filled"
        notes = ["Impact-aware simulation: market order was walked through order book depth."]
        if status == "partially_filled":
            notes.append("Only available liquidity inside the allowed slippage band was filled.")

        return VirtualExecutionReport(
            mode="impact_aware",
            status=status,
            requested_size_usd=requested_size_usd,
            filled_size_usd=walk.filled_size_usd,
            unfilled_size_usd=max(walk.unfilled_size_usd, 0.0),
            fill_ratio=fill_ratio,
            reference_price=reference_price,
            average_price=walk.average_price,
            entry_slippage_bps=entry_slippage_bps,
            exit_slippage_bps=exit_slippage_bps,
            market_impact_percent=walk.market_impact_percent,
            best_bid_before=best_bid,
            best_ask_before=best_ask,
            book_price_after=walk.book_price_after,
            liquidity=metrics,
            notes=notes,
        )

    def _simulate_from_metrics(
        self,
        *,
        request: ManualConfirmRequest,
        metrics: LiquidityMetrics,
        reference_price: float,
        requested_size_usd: float,
        buy_side: bool,
        best_bid: float | None,
        best_ask: float | None,
    ) -> VirtualExecutionReport:
        usable_depth = metrics.orderbook_depth_0_5_percent_usd or metrics.orderbook_depth_1_percent_usd
        filled_size_usd = requested_size_usd
        if usable_depth > 0 and requested_size_usd > usable_depth:
            filled_size_usd = usable_depth
        fill_ratio = min(filled_size_usd / requested_size_usd, 1.0) if requested_size_usd else 0.0
        unfilled_size_usd = max(requested_size_usd - filled_size_usd, 0.0)
        if unfilled_size_usd > 0 and (not request.allow_partial_fill or fill_ratio < request.min_fill_ratio):
            return self._rejected_report(
                mode="impact_aware",
                request=request,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                best_bid=best_bid,
                best_ask=best_ask,
                reason="insufficient_liquidity",
            )

        pressure_base = usable_depth or max(metrics.volume_5m_usd * 0.1, requested_size_usd, 1.0)
        pressure = requested_size_usd / pressure_base
        impact_component_bps = min(request.max_virtual_slippage_bps, pressure * 35)
        spread_component_bps = metrics.spread_percent * 50
        entry_slippage_bps = max(request.slippage_bps, spread_component_bps + impact_component_bps)
        entry_slippage_bps = min(entry_slippage_bps, request.max_virtual_slippage_bps)
        market_impact_percent = min(request.max_virtual_slippage_bps / 100, pressure * 0.35 + metrics.spread_percent / 2)
        average_price = _apply_price_slippage(reference_price, buy_side, entry_slippage_bps)
        exit_slippage_bps = _exit_slippage_bps(
            entry_slippage_bps=entry_slippage_bps,
            market_impact_percent=market_impact_percent,
            metrics=metrics,
            max_virtual_slippage_bps=request.max_virtual_slippage_bps,
        )
        status = "filled" if unfilled_size_usd <= 0.000001 else "partially_filled"
        notes = ["Impact-aware simulation estimated from liquidity metrics because no book levels were supplied."]
        if status == "partially_filled":
            notes.append("Depth metrics indicate only a partial virtual fill is available.")

        return VirtualExecutionReport(
            mode="impact_aware",
            status=status,
            requested_size_usd=requested_size_usd,
            filled_size_usd=filled_size_usd,
            unfilled_size_usd=unfilled_size_usd,
            fill_ratio=fill_ratio,
            reference_price=reference_price,
            average_price=average_price,
            entry_slippage_bps=entry_slippage_bps,
            exit_slippage_bps=exit_slippage_bps,
            market_impact_percent=market_impact_percent,
            best_bid_before=best_bid,
            best_ask_before=best_ask,
            liquidity=metrics,
            notes=notes,
        )

    def _rejected_report(
        self,
        *,
        mode: VirtualSimulationMode,
        request: ManualConfirmRequest,
        metrics: LiquidityMetrics,
        reference_price: float,
        requested_size_usd: float,
        best_bid: float | None,
        best_ask: float | None,
        reason: str,
    ) -> VirtualExecutionReport:
        report = VirtualExecutionReport(
            mode=mode,
            status="rejected_virtual_execution",
            requested_size_usd=requested_size_usd,
            filled_size_usd=0.0,
            unfilled_size_usd=requested_size_usd,
            fill_ratio=0.0,
            reference_price=reference_price,
            average_price=None,
            entry_slippage_bps=request.slippage_bps,
            exit_slippage_bps=request.slippage_bps,
            market_impact_percent=0.0,
            best_bid_before=best_bid,
            best_ask_before=best_ask,
            liquidity=metrics,
            rejected_reason=reason,
            notes=["Virtual execution rejected before position creation."],
        )
        return report.model_copy(
            update={
                "quality_gate": ExecutionQualityGate(
                    status="blocked",
                    blockers=[reason],
                    suggested_max_size_usd=_suggested_max_size(report),
                    message=_blocked_message(report, reason),
                )
            }
        )

    @staticmethod
    def _apply_quality_gate(report: VirtualExecutionReport) -> VirtualExecutionReport:
        if report.status == "rejected_virtual_execution":
            return report

        gate = _quality_gate(report)
        if gate.status != "blocked":
            return report.model_copy(update={"quality_gate": gate})

        notes = list(report.notes)
        notes.append("Execution Quality Gate blocked this virtual trade.")
        return report.model_copy(
            update={
                "status": "rejected_virtual_execution",
                "filled_size_usd": 0.0,
                "unfilled_size_usd": report.requested_size_usd,
                "fill_ratio": 0.0,
                "quality_gate": gate,
                "rejected_reason": "execution_quality_gate",
                "notes": notes,
            }
        )

    def _choose_mode(
        self,
        *,
        request: ManualConfirmRequest,
        signal: RadarSignal,
        snapshot: VirtualMarketSnapshot | None,
        metrics: LiquidityMetrics,
        requested_size_usd: float,
    ) -> VirtualSimulationMode:
        if request.simulation_mode in {"passive", "impact_aware"}:
            return request.simulation_mode

        has_market_context = snapshot is not None and (
            bool(snapshot.bids)
            or bool(snapshot.asks)
            or snapshot.volume_5m_usd is not None
            or snapshot.best_bid is not None
            or snapshot.best_ask is not None
        )
        breakdown = signal.score_breakdown
        has_signal_liquidity_context = breakdown.total > 0
        if not has_market_context and not has_signal_liquidity_context:
            return "passive"

        if metrics.impact_risk in {"medium", "high"}:
            return "impact_aware"
        if has_signal_liquidity_context and (
            breakdown.liquidity_score < 40 or breakdown.orderbook_score < 40
        ):
            return "impact_aware"
        if metrics.orderbook_depth_0_5_percent_usd and requested_size_usd > metrics.orderbook_depth_0_5_percent_usd * 0.5:
            return "impact_aware"
        return "passive"

    def _liquidity_metrics(
        self,
        *,
        snapshot: VirtualMarketSnapshot | None,
        signal: RadarSignal,
        reference_price: float,
        requested_size_usd: float,
    ) -> LiquidityMetrics:
        best_bid, best_ask = _best_prices(snapshot)
        spread_percent = 0.0
        if best_bid and best_ask and best_ask >= best_bid:
            mid = (best_bid + best_ask) / 2
            spread_percent = (best_ask - best_bid) / mid * 100 if mid > 0 else 0.0

        depth_0_1 = _depth_within_percent(snapshot, reference_price, 0.1)
        depth_0_5 = _depth_within_percent(snapshot, reference_price, 0.5)
        depth_1 = _depth_within_percent(snapshot, reference_price, 1.0)
        volume_1m = float(snapshot.volume_1m_usd or 0.0) if snapshot else 0.0
        volume_5m = float(snapshot.volume_5m_usd or 0.0) if snapshot else 0.0
        volume_15m = float(snapshot.volume_15m_usd or 0.0) if snapshot else 0.0
        average_trade_size = _average_trade_size(snapshot)
        volatility_1m = float(snapshot.volatility_1m_percent or 0.0) if snapshot else 0.0
        liquidity_score = _liquidity_score(
            signal=signal,
            spread_percent=spread_percent,
            depth_1_percent_usd=depth_1,
            volume_5m_usd=volume_5m,
            average_trade_size_usd=average_trade_size,
            requested_size_usd=requested_size_usd,
            has_snapshot=snapshot is not None,
        )
        impact_score = _impact_score(
            liquidity_score=liquidity_score,
            spread_percent=spread_percent,
            depth_0_5_percent_usd=depth_0_5,
            volume_5m_usd=volume_5m,
            requested_size_usd=requested_size_usd,
        )
        return LiquidityMetrics(
            spread_percent=spread_percent,
            orderbook_depth_0_1_percent_usd=depth_0_1,
            orderbook_depth_0_5_percent_usd=depth_0_5,
            orderbook_depth_1_percent_usd=depth_1,
            volume_1m_usd=volume_1m,
            volume_5m_usd=volume_5m,
            volume_15m_usd=volume_15m,
            average_trade_size_usd=average_trade_size,
            volatility_1m_percent=volatility_1m,
            liquidity_score=liquidity_score,
            impact_score=impact_score,
            impact_risk=_impact_risk(impact_score),
        )


def _execution_levels(snapshot: VirtualMarketSnapshot | None, buy_side: bool) -> list[OrderBookLevel]:
    if snapshot is None:
        return []
    levels = snapshot.asks if buy_side else snapshot.bids
    return sorted(levels, key=lambda level: level.price, reverse=not buy_side)


def _quality_gate(report: VirtualExecutionReport) -> ExecutionQualityGate:
    warnings: list[str] = []
    high_impact_reasons: list[str] = []
    blockers: list[str] = []
    metrics = report.liquidity
    requested_size_usd = report.requested_size_usd

    if metrics.spread_percent > 1.0:
        blockers.append("spread_above_1_percent_market_order_blocked")
    elif metrics.spread_percent > 0.3:
        warnings.append("spread_above_0_3_percent")

    if metrics.orderbook_depth_0_5_percent_usd > 0:
        depth_0_5_ratio = requested_size_usd / metrics.orderbook_depth_0_5_percent_usd
        if depth_0_5_ratio > 0.2:
            high_impact_reasons.append("position_above_20_percent_depth_0_5")

    if metrics.orderbook_depth_1_percent_usd > 0:
        depth_1_ratio = requested_size_usd / metrics.orderbook_depth_1_percent_usd
        if depth_1_ratio > 0.5:
            blockers.append("position_above_50_percent_depth_1")

    if metrics.volume_5m_usd > 0:
        volume_5m_ratio = requested_size_usd / metrics.volume_5m_usd
        if volume_5m_ratio > 0.3:
            blockers.append("position_above_30_percent_volume_5m")
        elif volume_5m_ratio > 0.1:
            high_impact_reasons.append("position_above_10_percent_volume_5m")

    if report.entry_slippage_bps > 150:
        blockers.append("expected_slippage_above_1_5_percent")
    elif report.entry_slippage_bps > 50:
        warnings.append("expected_slippage_above_0_5_percent")

    status = "passed"
    if blockers:
        status = "blocked"
    elif warnings or high_impact_reasons:
        status = "warning"

    suggested_max_size_usd = _suggested_max_size(report) if status == "blocked" else None
    return ExecutionQualityGate(
        status=status,
        warnings=warnings,
        high_impact_reasons=high_impact_reasons,
        blockers=blockers,
        suggested_max_size_usd=suggested_max_size_usd,
        message=_gate_message(report, blockers, suggested_max_size_usd) if status != "passed" else None,
    )


def _suggested_max_size(report: VirtualExecutionReport) -> float | None:
    metrics = report.liquidity
    candidates: list[float] = []
    if metrics.orderbook_depth_1_percent_usd > 0:
        candidates.append(metrics.orderbook_depth_1_percent_usd * 0.5)
    if metrics.volume_5m_usd > 0:
        candidates.append(metrics.volume_5m_usd * 0.1)
    if report.entry_slippage_bps > 150 and report.requested_size_usd > 0:
        candidates.append(report.requested_size_usd * 150 / report.entry_slippage_bps)
    if not candidates:
        return None
    return round(max(min(candidates) * 0.9, 0.0), 2)


def _gate_message(
    report: VirtualExecutionReport,
    blockers: list[str],
    suggested_max_size_usd: float | None,
) -> str:
    if blockers:
        if suggested_max_size_usd is not None:
            return (
                "Эта сделка выглядит красиво на графике, но ее нельзя было бы нормально исполнить. "
                f"Ваш объем ${report.requested_size_usd:,.2f} слишком большой для текущей ликвидности. "
                f"Максимальный реалистичный размер позиции: ${suggested_max_size_usd:,.2f}."
            )
        return (
            "Эта сделка выглядит красиво на графике, но ее нельзя было бы нормально исполнить "
            "при текущем spread, slippage или глубине рынка."
        )
    return (
        "Сделка может быть исполнена виртуально, но качество исполнения требует внимания: "
        "есть предупреждения по ликвидности, impact или slippage."
    )


def _blocked_message(report: VirtualExecutionReport, reason: str) -> str:
    suggested_max_size_usd = _suggested_max_size(report)
    return _gate_message(report, [reason], suggested_max_size_usd)


def _walk_book(
    *,
    levels: list[OrderBookLevel],
    buy_side: bool,
    reference_price: float,
    requested_size_usd: float,
    max_slippage_bps: float,
) -> _BookWalk:
    remaining = requested_size_usd
    quantity = 0.0
    filled_size_usd = 0.0
    last_level_index: int | None = None
    last_level_fully_consumed = False
    max_price = _apply_price_slippage(reference_price, buy_side, max_slippage_bps)

    for index, level in enumerate(levels):
        if buy_side and level.price > max_price:
            break
        if not buy_side and level.price < max_price:
            break
        available_size = _level_notional(level)
        if available_size <= 0:
            continue
        fill_size = min(remaining, available_size)
        quantity += fill_size / level.price
        filled_size_usd += fill_size
        remaining -= fill_size
        last_level_index = index
        last_level_fully_consumed = fill_size >= available_size - 0.000001
        if remaining <= 0.000001:
            remaining = 0.0
            break

    average_price = filled_size_usd / quantity if quantity > 0 else None
    book_price_after = None
    if last_level_index is not None:
        next_index = last_level_index + 1 if last_level_fully_consumed else last_level_index
        if next_index < len(levels):
            book_price_after = levels[next_index].price
        else:
            book_price_after = levels[last_level_index].price
    best_before = levels[0].price if levels else None
    market_impact_percent = (
        abs(book_price_after - best_before) / reference_price * 100
        if best_before and book_price_after and reference_price > 0
        else 0.0
    )
    return _BookWalk(
        filled_size_usd=filled_size_usd,
        quantity=quantity,
        unfilled_size_usd=max(remaining, 0.0),
        average_price=average_price,
        book_price_after=book_price_after,
        market_impact_percent=market_impact_percent,
    )


def _best_prices(snapshot: VirtualMarketSnapshot | None) -> tuple[float | None, float | None]:
    if snapshot is None:
        return None, None
    best_bid = snapshot.best_bid
    best_ask = snapshot.best_ask
    if best_bid is None and snapshot.bids:
        best_bid = max(level.price for level in snapshot.bids)
    if best_ask is None and snapshot.asks:
        best_ask = min(level.price for level in snapshot.asks)
    return best_bid, best_ask


def _depth_within_percent(
    snapshot: VirtualMarketSnapshot | None,
    reference_price: float,
    percent: float,
) -> float:
    if snapshot is None:
        return 0.0
    ask_limit = reference_price * (1 + percent / 100)
    bid_limit = reference_price * (1 - percent / 100)
    ask_depth = sum(_level_notional(level) for level in snapshot.asks if level.price <= ask_limit)
    bid_depth = sum(_level_notional(level) for level in snapshot.bids if level.price >= bid_limit)
    if ask_depth > 0 and bid_depth > 0:
        return min(ask_depth, bid_depth)
    return max(ask_depth, bid_depth)


def _level_notional(level: OrderBookLevel) -> float:
    if level.notional_usd is not None:
        return float(level.notional_usd)
    if level.quantity is not None:
        return float(level.quantity) * level.price
    return 0.0


def _average_trade_size(snapshot: VirtualMarketSnapshot | None) -> float:
    if snapshot is None:
        return 0.0
    if snapshot.average_trade_size_usd is not None:
        return float(snapshot.average_trade_size_usd)
    notionals = [
        float(trade.notional_usd if trade.notional_usd is not None else (trade.quantity or 0.0) * trade.price)
        for trade in snapshot.recent_trades
    ]
    notionals = [value for value in notionals if value > 0]
    return sum(notionals) / len(notionals) if notionals else 0.0


def _liquidity_score(
    *,
    signal: RadarSignal,
    spread_percent: float,
    depth_1_percent_usd: float,
    volume_5m_usd: float,
    average_trade_size_usd: float,
    requested_size_usd: float,
    has_snapshot: bool,
) -> int:
    breakdown = signal.score_breakdown
    if not has_snapshot and breakdown.total <= 0:
        return 75
    if not any([spread_percent, depth_1_percent_usd, volume_5m_usd, average_trade_size_usd]):
        return max(0, min(100, breakdown.liquidity_score if breakdown.total > 0 else 50))

    spread_score = _threshold_score(spread_percent, [(0.05, 30), (0.15, 24), (0.35, 15), (0.75, 7)], 2)
    depth_ratio = depth_1_percent_usd / requested_size_usd if requested_size_usd else 0.0
    depth_score = _ratio_score(depth_ratio, [(20, 30), (5, 24), (2, 18), (1, 12), (0.5, 6)])
    volume_ratio = volume_5m_usd / requested_size_usd if requested_size_usd else 0.0
    volume_score = _ratio_score(volume_ratio, [(30, 25), (10, 20), (3, 12), (1, 7), (0.25, 3)])
    trade_ratio = average_trade_size_usd / requested_size_usd if requested_size_usd else 0.0
    trade_score = _ratio_score(trade_ratio, [(1, 15), (0.25, 10), (0.1, 6), (0.03, 3)])
    return max(0, min(100, int(round(spread_score + depth_score + volume_score + trade_score))))


def _impact_score(
    *,
    liquidity_score: int,
    spread_percent: float,
    depth_0_5_percent_usd: float,
    volume_5m_usd: float,
    requested_size_usd: float,
) -> int:
    score = 100 - liquidity_score
    if spread_percent >= 0.35:
        score += 12
    if depth_0_5_percent_usd and requested_size_usd > depth_0_5_percent_usd * 0.5:
        score += 18
    if volume_5m_usd and requested_size_usd > volume_5m_usd * 0.2:
        score += 12
    return max(0, min(100, int(round(score))))


def _impact_risk(impact_score: int) -> ImpactRisk:
    if impact_score >= 66:
        return "high"
    if impact_score >= 33:
        return "medium"
    return "low"


def _threshold_score(value: float, thresholds: Iterable[tuple[float, int]], default: int) -> int:
    for threshold, score in thresholds:
        if value <= threshold:
            return score
    return default


def _ratio_score(value: float, thresholds: Iterable[tuple[float, int]]) -> int:
    for threshold, score in thresholds:
        if value >= threshold:
            return score
    return 0


def _apply_price_slippage(price: float, buy_side: bool, slippage_bps: float) -> float:
    multiplier = slippage_bps / 10_000
    return price * (1 + multiplier) if buy_side else price * (1 - multiplier)


def _slippage_bps(reference_price: float, average_price: float, buy_side: bool) -> float:
    if reference_price <= 0:
        return 0.0
    if buy_side:
        return max((average_price - reference_price) / reference_price * 10_000, 0.0)
    return max((reference_price - average_price) / reference_price * 10_000, 0.0)


def _exit_slippage_bps(
    *,
    entry_slippage_bps: float,
    market_impact_percent: float,
    metrics: LiquidityMetrics,
    max_virtual_slippage_bps: float,
) -> float:
    impact_bps = market_impact_percent * 125
    spread_bps = metrics.spread_percent * 50
    exit_slippage_bps = max(entry_slippage_bps, spread_bps + impact_bps)
    if metrics.impact_risk == "high":
        exit_slippage_bps *= 1.25
    elif metrics.impact_risk == "medium":
        exit_slippage_bps *= 1.1
    return min(exit_slippage_bps, max_virtual_slippage_bps * 1.5)
