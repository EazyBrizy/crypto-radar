from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
from typing import Any, Iterable

from app.schemas.risk import VirtualExecutionProfile, VirtualFillPolicy
from app.schemas.signal import RadarSignal
from app.schemas.trade import (
    ExecutionQualityGate,
    ImpactRisk,
    LiquidityMetrics,
    ManualConfirmRequest,
    OrderBookLevel,
    VirtualFillResult,
    VirtualImpactCandle,
    VirtualImpactPathPoint,
    VirtualExecutionReport,
    VirtualMarketSnapshot,
    VirtualSimulatedPositionPath,
    VirtualSimulationMode,
)
from app.services.virtual_simulation_model import (
    capability_codes_for_report,
    planned_capability_codes_for_report,
    simulation_tier_for_report,
)
from app.services.virtual_execution_profile import fill_policy_for_profile, normalize_virtual_execution_profile


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
        market_data_status: str = "unknown",
        market_data_source: str | None = None,
        market_data_warnings: Iterable[str] = (),
        market_spread_bps: float | None = None,
        orderbook_depth_usd: float | None = None,
        execution_profile: Any | None = None,
        entry_spread_limit_bps: float | None = None,
        allow_low_liquidity: bool | None = None,
        enforce_conservative_rules: bool = True,
        virtual_execution_profile: VirtualExecutionProfile = "realistic",
    ) -> VirtualExecutionReport:
        snapshot = request.market_snapshot
        execution_profile_name = normalize_virtual_execution_profile(virtual_execution_profile)
        fill_policy = fill_policy_for_profile(execution_profile_name)
        metrics = self._liquidity_metrics(
            snapshot=snapshot,
            signal=signal,
            reference_price=reference_price,
            requested_size_usd=requested_size_usd,
            market_spread_bps=market_spread_bps,
            orderbook_depth_usd=orderbook_depth_usd,
        )
        mode = self._choose_mode(
            request=request,
            signal=signal,
            snapshot=snapshot,
            metrics=metrics,
            requested_size_usd=requested_size_usd,
        )
        raw_inputs_snapshot = _raw_inputs_snapshot(
            signal=signal,
            request=request,
            snapshot=snapshot,
            metrics=metrics,
            reference_price=reference_price,
            requested_size_usd=requested_size_usd,
            market_data_status=market_data_status,
            market_data_source=market_data_source,
            market_data_warnings=market_data_warnings,
            market_spread_bps=market_spread_bps,
            orderbook_depth_usd=orderbook_depth_usd,
            execution_profile=execution_profile,
            entry_spread_limit_bps=entry_spread_limit_bps,
            allow_low_liquidity=allow_low_liquidity,
            enforce_conservative_rules=enforce_conservative_rules and execution_profile_name == "realistic",
            virtual_execution_profile=execution_profile_name,
            fill_policy=fill_policy,
        )
        if execution_profile_name == "deterministic_test":
            report = self._simulate_deterministic(
                request=request,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                buy_side=signal.direction == "long",
            )
            report = _with_execution_profile(
                report,
                execution_profile=execution_profile_name,
                fill_policy=fill_policy,
            )
            return _finalize_report(report, raw_inputs_snapshot=raw_inputs_snapshot)

        strict_conservative_rules = enforce_conservative_rules and execution_profile_name == "realistic"
        policy_warnings = _profile_warnings(
            profile=execution_profile_name,
            market_data_status=market_data_status,
            market_data_warnings=market_data_warnings,
            snapshot=snapshot,
            signal=signal,
            allow_low_liquidity=allow_low_liquidity,
        )
        if strict_conservative_rules:
            preflight = self._preflight_conservative_block(
                mode=mode,
                request=request,
                signal=signal,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                market_data_status=market_data_status,
                entry_spread_limit_bps=entry_spread_limit_bps,
                allow_low_liquidity=allow_low_liquidity,
            )
            if preflight is not None:
                preflight = _with_execution_profile(
                    preflight,
                    execution_profile=execution_profile_name,
                    fill_policy=fill_policy,
                )
                return _finalize_report(preflight, raw_inputs_snapshot=raw_inputs_snapshot)
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
        report = self._apply_quality_gate(report)
        if execution_profile_name == "relaxed_paper":
            report = self._apply_relaxed_paper_policy(
                report,
                request=request,
                snapshot=snapshot,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                buy_side=signal.direction == "long",
                policy_warnings=policy_warnings,
            )
        if strict_conservative_rules:
            report = self._apply_conservative_fill_policy(
                report,
                request=request,
                snapshot=snapshot,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                buy_side=signal.direction == "long",
            )
        report = _with_execution_profile(
            report,
            execution_profile=execution_profile_name,
            fill_policy=fill_policy,
        )
        return _finalize_report(report, raw_inputs_snapshot=raw_inputs_snapshot)

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
        return _with_simulation_capabilities(VirtualExecutionReport(
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
        ))

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

        simulated_path = _simulated_position_path(
            reference_price=reference_price,
            average_price=walk.average_price,
            book_price_after=walk.book_price_after,
            market_impact_percent=walk.market_impact_percent,
            buy_side=buy_side,
            metrics=metrics,
        )
        return _with_simulation_capabilities(VirtualExecutionReport(
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
            simulated_path=simulated_path,
            notes=notes,
        ))

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

        simulated_path = _simulated_position_path(
            reference_price=reference_price,
            average_price=average_price,
            book_price_after=None,
            market_impact_percent=market_impact_percent,
            buy_side=buy_side,
            metrics=metrics,
        )
        return _with_simulation_capabilities(VirtualExecutionReport(
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
            simulated_path=simulated_path,
            notes=notes,
        ))

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
        report = _with_simulation_capabilities(VirtualExecutionReport(
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
        ))
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
        notes.append("Execution Quality Gate flagged severe simulated execution risk.")
        return report.model_copy(
            update={
                "quality_gate": gate,
                "notes": notes,
            }
        )

    def _preflight_conservative_block(
        self,
        *,
        mode: VirtualSimulationMode,
        request: ManualConfirmRequest,
        signal: RadarSignal,
        metrics: LiquidityMetrics,
        reference_price: float,
        requested_size_usd: float,
        market_data_status: str,
        entry_spread_limit_bps: float | None,
        allow_low_liquidity: bool | None,
    ) -> VirtualExecutionReport | None:
        normalized_market_status = _normalized_market_data_status(market_data_status)
        if normalized_market_status in {"missing", "stale"}:
            return self._rejected_report(
                mode=mode,
                request=request,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                best_bid=_best_prices(request.market_snapshot)[0],
                best_ask=_best_prices(request.market_snapshot)[1],
                reason=f"market_data_{normalized_market_status}",
            )

        spread_limit = _positive_float(entry_spread_limit_bps)
        spread_bps = metrics.spread_percent * 100
        if spread_limit is not None and spread_bps > spread_limit:
            return self._rejected_report(
                mode=mode,
                request=request,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                best_bid=_best_prices(request.market_snapshot)[0],
                best_ask=_best_prices(request.market_snapshot)[1],
                reason="spread_above_entry_limit",
            )

        if _liquidity_tier(signal) == "low_liquidity" and allow_low_liquidity is False:
            return self._rejected_report(
                mode=mode,
                request=request,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=requested_size_usd,
                best_bid=_best_prices(request.market_snapshot)[0],
                best_ask=_best_prices(request.market_snapshot)[1],
                reason="low_liquidity_not_allowed",
            )
        return None

    def _simulate_deterministic(
        self,
        *,
        request: ManualConfirmRequest,
        metrics: LiquidityMetrics,
        reference_price: float,
        requested_size_usd: float,
        buy_side: bool,
    ) -> VirtualExecutionReport:
        del buy_side
        best_bid, best_ask = _best_prices(request.market_snapshot)
        return _with_simulation_capabilities(VirtualExecutionReport(
            mode="passive",
            status="filled",
            requested_size_usd=requested_size_usd,
            filled_size_usd=requested_size_usd,
            unfilled_size_usd=0.0,
            fill_ratio=1.0,
            reference_price=reference_price,
            average_price=reference_price,
            estimated_fill_price=reference_price,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.0,
            market_impact_percent=0.0,
            best_bid_before=best_bid,
            best_ask_before=best_ask,
            liquidity=metrics,
            quality_gate=ExecutionQualityGate(status="passed"),
            notes=[
                "deterministic_test_fill",
                "Deterministic test fill: full notional at reference price; no market network data used.",
            ],
        ))

    def _apply_relaxed_paper_policy(
        self,
        report: VirtualExecutionReport,
        *,
        request: ManualConfirmRequest,
        snapshot: VirtualMarketSnapshot | None,
        metrics: LiquidityMetrics,
        reference_price: float,
        requested_size_usd: float,
        buy_side: bool,
        policy_warnings: Iterable[str],
    ) -> VirtualExecutionReport:
        warnings = _dedupe_strings([
            *report.warnings,
            *policy_warnings,
        ])
        notes = _dedupe_strings([
            *report.notes,
            *warnings,
        ])
        report = report.model_copy(update={"warnings": warnings, "notes": notes})

        hard_blockers = _relaxed_hard_blockers(report)
        if report.status == "rejected_virtual_execution":
            if hard_blockers:
                return _rejected_with_blockers(report, hard_blockers, warnings=warnings)
            if _can_relaxed_fallback(report):
                return self._relaxed_fallback_fill(
                    original=report,
                    request=request,
                    snapshot=snapshot,
                    metrics=metrics,
                    reference_price=reference_price,
                    requested_size_usd=requested_size_usd,
                    buy_side=buy_side,
                    warnings=warnings,
                )
            return report

        if report.quality_gate.status != "blocked":
            return _with_relaxed_warnings(report, warnings)

        soft_blockers = [
            blocker
            for blocker in report.quality_gate.blockers
            if blocker in _RELAXED_SOFT_BLOCKERS
        ]
        hard_blockers = [
            blocker
            for blocker in report.quality_gate.blockers
            if blocker not in _RELAXED_SOFT_BLOCKERS
        ]
        if hard_blockers:
            return _rejected_with_blockers(report, hard_blockers, warnings=warnings)

        relaxed_warnings = _dedupe_strings([
            *warnings,
            *report.quality_gate.warnings,
            *report.quality_gate.high_impact_reasons,
            *soft_blockers,
            "relaxed_paper_liquidity_warning",
        ])
        gate = report.quality_gate.model_copy(
            update={
                "status": "warning",
                "warnings": relaxed_warnings,
                "blockers": [],
                "suggested_max_size_usd": None,
                "message": "Relaxed paper profile allowed the virtual fill with liquidity warnings.",
            }
        )
        return report.model_copy(
            update={
                "quality_gate": gate,
                "warnings": relaxed_warnings,
                "blockers": [],
                "notes": _dedupe_strings([*report.notes, *relaxed_warnings]),
            }
        )

    def _relaxed_fallback_fill(
        self,
        *,
        original: VirtualExecutionReport,
        request: ManualConfirmRequest,
        snapshot: VirtualMarketSnapshot | None,
        metrics: LiquidityMetrics,
        reference_price: float,
        requested_size_usd: float,
        buy_side: bool,
        warnings: Iterable[str],
    ) -> VirtualExecutionReport:
        best_bid, best_ask = _best_prices(snapshot)
        spread_slippage_bps = min(metrics.spread_percent * 50, request.max_virtual_slippage_bps)
        entry_slippage_bps = min(
            max(request.slippage_bps, spread_slippage_bps),
            request.max_virtual_slippage_bps,
        )
        average_price = _apply_price_slippage(reference_price, buy_side, entry_slippage_bps)
        relaxed_warnings = _dedupe_strings([
            *warnings,
            original.rejected_reason,
            "relaxed_paper_market_fallback_fill",
        ])
        gate = ExecutionQualityGate(
            status="warning" if relaxed_warnings else "passed",
            warnings=relaxed_warnings,
            blockers=[],
            message=(
                "Relaxed paper profile used backend fallback price and kept the market-data issue as a warning."
                if relaxed_warnings
                else None
            ),
        )
        return _with_simulation_capabilities(VirtualExecutionReport(
            mode=original.mode,
            status="filled",
            requested_size_usd=requested_size_usd,
            filled_size_usd=requested_size_usd,
            unfilled_size_usd=0.0,
            fill_ratio=1.0,
            reference_price=reference_price,
            average_price=average_price,
            estimated_fill_price=average_price,
            entry_slippage_bps=entry_slippage_bps,
            exit_slippage_bps=entry_slippage_bps,
            market_impact_percent=0.0,
            best_bid_before=best_bid,
            best_ask_before=best_ask,
            liquidity=metrics,
            quality_gate=gate,
            warnings=relaxed_warnings,
            notes=_dedupe_strings([
                *original.notes,
                *relaxed_warnings,
                "Relaxed paper fallback: full virtual notional filled at backend reference price.",
            ]),
        ))

    def _apply_conservative_fill_policy(
        self,
        report: VirtualExecutionReport,
        *,
        request: ManualConfirmRequest,
        snapshot: VirtualMarketSnapshot | None,
        metrics: LiquidityMetrics,
        reference_price: float,
        requested_size_usd: float,
        buy_side: bool,
    ) -> VirtualExecutionReport:
        if report.status == "rejected_virtual_execution" or report.quality_gate.status != "blocked":
            return report
        blockers = set(report.quality_gate.blockers)
        if not blockers or blockers - _SIZE_OR_IMPACT_BLOCKERS:
            return _rejected_from_blocked_report(report)

        safe_size_usd = _suggested_max_size(report)
        if safe_size_usd is None or safe_size_usd <= 0:
            return _rejected_from_blocked_report(report)
        safe_size_usd = min(safe_size_usd, requested_size_usd)
        fill_ratio = safe_size_usd / requested_size_usd if requested_size_usd > 0 else 0.0
        if not request.allow_partial_fill or fill_ratio < request.min_fill_ratio:
            return _rejected_from_blocked_report(report)

        if report.mode == "passive":
            capped = self._simulate_passive(
                request=request,
                snapshot=snapshot,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=safe_size_usd,
                buy_side=buy_side,
            )
        else:
            capped = self._simulate_impact_aware(
                request=request,
                snapshot=snapshot,
                metrics=metrics,
                reference_price=reference_price,
                requested_size_usd=safe_size_usd,
                buy_side=buy_side,
            )
        capped = self._apply_quality_gate(capped)
        if capped.average_price is None or capped.filled_size_usd <= 0:
            return _rejected_from_blocked_report(report)

        filled_size_usd = min(capped.filled_size_usd, safe_size_usd)
        fill_ratio = min(filled_size_usd / requested_size_usd, 1.0) if requested_size_usd > 0 else 0.0
        notes = _dedupe_strings([
            *capped.notes,
            "Requested notional exceeds conservative safe size; virtual fill was capped.",
            *report.quality_gate.blockers,
        ])
        capped = capped.model_copy(
            update={
                "status": "partially_filled",
                "requested_size_usd": requested_size_usd,
                "filled_size_usd": filled_size_usd,
                "unfilled_size_usd": max(requested_size_usd - filled_size_usd, 0.0),
                "fill_ratio": fill_ratio,
                "notes": notes,
            }
        )
        return capped

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
        market_spread_bps: float | None = None,
        orderbook_depth_usd: float | None = None,
    ) -> LiquidityMetrics:
        best_bid, best_ask = _best_prices(snapshot)
        spread_percent = 0.0
        explicit_spread_bps = _positive_float(market_spread_bps)
        if explicit_spread_bps is not None:
            spread_percent = explicit_spread_bps / 100
        elif best_bid and best_ask and best_ask >= best_bid:
            mid = (best_bid + best_ask) / 2
            spread_percent = (best_ask - best_bid) / mid * 100 if mid > 0 else 0.0

        depth_0_1 = _depth_within_percent(snapshot, reference_price, 0.1)
        depth_0_5 = _depth_within_percent(snapshot, reference_price, 0.5)
        depth_1 = _depth_within_percent(snapshot, reference_price, 1.0)
        explicit_depth = _positive_float(orderbook_depth_usd)
        if explicit_depth is not None:
            if depth_0_5 <= 0:
                depth_0_5 = explicit_depth
            if depth_1 <= 0:
                depth_1 = explicit_depth
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


_SIZE_OR_IMPACT_BLOCKERS = {
    "position_above_50_percent_depth_1",
    "position_above_30_percent_volume_5m",
    "expected_slippage_above_1_5_percent",
}

_RELAXED_SOFT_BLOCKERS = {
    "position_above_50_percent_depth_1",
    "position_above_30_percent_volume_5m",
}

_RELAXED_FALLBACK_REASONS = {
    "insufficient_liquidity",
    "market_data_missing",
    "market_data_stale",
    "low_liquidity_not_allowed",
}


def _execution_levels(snapshot: VirtualMarketSnapshot | None, buy_side: bool) -> list[OrderBookLevel]:
    if snapshot is None:
        return []
    levels = snapshot.asks if buy_side else snapshot.bids
    return sorted(levels, key=lambda level: level.price, reverse=not buy_side)


def _finalize_report(
    report: VirtualExecutionReport,
    *,
    raw_inputs_snapshot: dict[str, Any],
) -> VirtualExecutionReport:
    fill_result = _fill_result(report, raw_inputs_snapshot=raw_inputs_snapshot)
    warnings = _execution_warnings(report)
    blockers = _execution_blockers(report)
    reason_codes = _execution_reason_codes(
        report,
        warnings=warnings,
        blockers=blockers,
        fill_reason=fill_result.reason,
    )
    reason_code = fill_result.reason
    if reason_code is None:
        reason_code = reason_codes[0] if reason_codes else _status_reason_code(report)
    return report.model_copy(
        update={
            "fill_result": fill_result,
            "raw_inputs_snapshot": raw_inputs_snapshot,
            "estimated_fill_price": report.average_price,
            "warnings": warnings,
            "blockers": blockers,
            "reason_code": reason_code,
            "reason_codes": reason_codes,
        }
    )


def _fill_result(
    report: VirtualExecutionReport,
    *,
    raw_inputs_snapshot: dict[str, Any],
) -> VirtualFillResult:
    reason = _fill_reason(report)
    return VirtualFillResult(
        status=_fill_status(report),
        requested_notional=report.requested_size_usd,
        filled_notional=report.filled_size_usd,
        avg_fill_price=report.average_price,
        estimated_slippage_bps=report.entry_slippage_bps,
        spread_bps=report.liquidity.spread_percent * 100,
        market_impact_bps=report.market_impact_percent * 100,
        reason=reason,
        warnings=_fill_warnings(report),
        raw_inputs_snapshot=raw_inputs_snapshot,
    )


def _fill_status(report: VirtualExecutionReport) -> str:
    if report.status == "rejected_virtual_execution":
        return "blocked" if report.quality_gate.status == "blocked" else "rejected"
    if report.status == "partially_filled":
        return "partial_filled"
    if report.quality_gate.status == "blocked":
        return "blocked"
    return "filled"


def _fill_reason(report: VirtualExecutionReport) -> str | None:
    if report.rejected_reason is not None:
        return report.rejected_reason
    if any("safe size" in note for note in report.notes):
        return "requested_notional_above_safe_size"
    if report.quality_gate.blockers:
        return ";".join(report.quality_gate.blockers)
    return None


def _fill_warnings(report: VirtualExecutionReport) -> list[str]:
    return _dedupe_strings([
        *report.warnings,
        *report.quality_gate.warnings,
        *report.quality_gate.high_impact_reasons,
        *report.notes,
    ])


def _execution_warnings(report: VirtualExecutionReport) -> list[str]:
    return _dedupe_strings([
        *report.warnings,
        *report.quality_gate.warnings,
        *report.quality_gate.high_impact_reasons,
        *report.notes,
    ])


def _execution_blockers(report: VirtualExecutionReport) -> list[str]:
    blockers = list(report.blockers)
    blockers.extend(report.quality_gate.blockers)
    if report.status == "rejected_virtual_execution":
        blockers.append(report.rejected_reason)
    return _dedupe_strings(blockers)


def _execution_reason_codes(
    report: VirtualExecutionReport,
    *,
    warnings: Iterable[str],
    blockers: Iterable[str],
    fill_reason: str | None,
) -> list[str]:
    codes = [
        fill_reason,
        *blockers,
        *report.quality_gate.blockers,
        *report.quality_gate.warnings,
        *report.quality_gate.high_impact_reasons,
        *warnings,
    ]
    if report.execution_profile == "deterministic_test":
        codes.append("deterministic_test_fill")
    return _dedupe_strings([_reason_code(value) for value in codes])


def _status_reason_code(report: VirtualExecutionReport) -> str:
    if report.status == "partially_filled":
        return "partial_filled"
    if report.status == "rejected_virtual_execution":
        return "rejected_virtual_execution"
    return "filled"


def _raw_inputs_snapshot(
    *,
    signal: RadarSignal,
    request: ManualConfirmRequest,
    snapshot: VirtualMarketSnapshot | None,
    metrics: LiquidityMetrics,
    reference_price: float,
    requested_size_usd: float,
    market_data_status: str,
    market_data_source: str | None,
    market_data_warnings: Iterable[str],
    market_spread_bps: float | None,
    orderbook_depth_usd: float | None,
    execution_profile: Any | None,
    entry_spread_limit_bps: float | None,
    allow_low_liquidity: bool | None,
    enforce_conservative_rules: bool,
    virtual_execution_profile: VirtualExecutionProfile,
    fill_policy: VirtualFillPolicy,
) -> dict[str, Any]:
    best_bid, best_ask = _best_prices(snapshot)
    return {
        "side": signal.direction,
        "symbol": signal.symbol,
        "exchange": signal.exchange,
        "entry_plan": _entry_plan_snapshot(signal),
        "requested_notional": requested_size_usd,
        "market_price": reference_price,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "orderbook_depth": {
            "depth_0_1_percent_usd": metrics.orderbook_depth_0_1_percent_usd,
            "depth_0_5_percent_usd": metrics.orderbook_depth_0_5_percent_usd,
            "depth_1_percent_usd": metrics.orderbook_depth_1_percent_usd,
            "visible_entry_side_depth_usd": orderbook_depth_usd,
            "bid_levels": len(snapshot.bids) if snapshot is not None else 0,
            "ask_levels": len(snapshot.asks) if snapshot is not None else 0,
        },
        "spread_bps": metrics.spread_percent * 100,
        "market_spread_bps": market_spread_bps,
        "execution_profile": _jsonable_model(execution_profile),
        "virtual_execution_profile": virtual_execution_profile,
        "fill_policy": fill_policy,
        "request_execution_profile": _jsonable_model(request.execution_profile),
        "low_liquidity_tier": _liquidity_tier(signal),
        "allow_low_liquidity": allow_low_liquidity,
        "slippage_settings": {
            "manual_slippage_bps": request.slippage_bps,
            "max_virtual_slippage_bps": request.max_virtual_slippage_bps,
            "allow_partial_fill": request.allow_partial_fill,
            "min_fill_ratio": request.min_fill_ratio,
        },
        "entry_spread_limit_bps": entry_spread_limit_bps,
        "market_data_status": _normalized_market_data_status(market_data_status),
        "market_data_source": market_data_source,
        "market_data_warnings": list(market_data_warnings),
        "simulation_mode": request.simulation_mode,
        "enforce_conservative_rules": enforce_conservative_rules,
    }


def _with_execution_profile(
    report: VirtualExecutionReport,
    *,
    execution_profile: VirtualExecutionProfile,
    fill_policy: VirtualFillPolicy,
) -> VirtualExecutionReport:
    return report.model_copy(
        update={
            "execution_profile": execution_profile,
            "fill_policy": fill_policy,
        }
    )


def _profile_warnings(
    *,
    profile: VirtualExecutionProfile,
    market_data_status: str,
    market_data_warnings: Iterable[str],
    snapshot: VirtualMarketSnapshot | None,
    signal: RadarSignal,
    allow_low_liquidity: bool | None,
) -> list[str]:
    warnings = list(market_data_warnings)
    if profile != "relaxed_paper":
        return _dedupe_strings(warnings)

    normalized_status = _normalized_market_data_status(market_data_status)
    if normalized_status == "stale":
        warnings.append("market_data_stale_relaxed_fallback")
    elif normalized_status == "missing":
        warnings.append("market_data_missing_relaxed_fallback")

    buy_side = signal.direction == "long"
    if snapshot is None or not _execution_levels(snapshot, buy_side):
        warnings.append("orderbook_missing_relaxed_fallback")

    if _liquidity_tier(signal) == "low_liquidity" and allow_low_liquidity is False:
        warnings.append("low_liquidity_tier_relaxed_warning")

    return _dedupe_strings(warnings)


def _with_relaxed_warnings(
    report: VirtualExecutionReport,
    warnings: Iterable[str],
) -> VirtualExecutionReport:
    relaxed_warnings = _dedupe_strings([
        *report.warnings,
        *warnings,
        *report.quality_gate.warnings,
    ])
    if not relaxed_warnings:
        return report
    gate_status = "warning" if report.quality_gate.status == "passed" else report.quality_gate.status
    gate = report.quality_gate.model_copy(
        update={
            "status": gate_status,
            "warnings": relaxed_warnings,
        }
    )
    return report.model_copy(
        update={
            "quality_gate": gate,
            "warnings": relaxed_warnings,
            "notes": _dedupe_strings([*report.notes, *relaxed_warnings]),
        }
    )


def _can_relaxed_fallback(report: VirtualExecutionReport) -> bool:
    return report.rejected_reason in _RELAXED_FALLBACK_REASONS


def _relaxed_hard_blockers(report: VirtualExecutionReport) -> list[str]:
    blockers: list[str] = []
    if report.liquidity.spread_percent > 1.0:
        blockers.append("spread_above_1_percent_market_order_blocked")
    if report.entry_slippage_bps > 150:
        blockers.append("expected_slippage_above_1_5_percent")
    blockers.extend(
        blocker
        for blocker in report.quality_gate.blockers
        if blocker not in _RELAXED_SOFT_BLOCKERS
        and blocker not in _RELAXED_FALLBACK_REASONS
    )
    return _dedupe_strings(blockers)


def _rejected_with_blockers(
    report: VirtualExecutionReport,
    blockers: Iterable[str],
    *,
    warnings: Iterable[str],
) -> VirtualExecutionReport:
    hard_blockers = _dedupe_strings(blockers)
    gate = report.quality_gate.model_copy(
        update={
            "status": "blocked",
            "warnings": _dedupe_strings([*warnings, *report.quality_gate.warnings]),
            "blockers": hard_blockers,
            "message": _gate_message(report, hard_blockers, report.quality_gate.suggested_max_size_usd),
        }
    )
    rejected = report.model_copy(
        update={
            "quality_gate": gate,
            "warnings": gate.warnings,
            "blockers": hard_blockers,
            "notes": _dedupe_strings([*report.notes, *gate.warnings]),
        }
    )
    return _rejected_from_blocked_report(rejected)


def _entry_plan_snapshot(signal: RadarSignal) -> dict[str, Any]:
    trade_plan = getattr(signal, "trade_plan", None)
    if trade_plan is not None:
        return _jsonable_model(trade_plan)
    return {
        "entry_min": signal.entry_min,
        "entry_max": signal.entry_max,
        "stop_loss": signal.stop_loss,
        "take_profit_1": signal.take_profit_1,
        "take_profit_2": signal.take_profit_2,
    }


def _jsonable_model(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return value


def _reason_code(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if " " in text or "." in text or ":" in text:
        return None
    return text.lower()


def _liquidity_tier(signal: RadarSignal) -> str:
    quality = getattr(signal, "quality", None)
    tier = getattr(quality, "tier", None)
    return str(tier or "unknown")


def _normalized_market_data_status(value: str | None) -> str:
    normalized = str(value or "unknown").strip().lower()
    if normalized in {"fresh", "partial", "missing", "stale"}:
        return normalized
    return "unknown"


def _positive_float(value: float | int | Decimal | str | None) -> float | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if number <= 0:
        return None
    return float(number)


def _rejected_from_blocked_report(report: VirtualExecutionReport) -> VirtualExecutionReport:
    blockers = list(report.quality_gate.blockers)
    reason = blockers[0] if blockers else "execution_quality_blocked"
    notes = _dedupe_strings([
        *report.notes,
        "Virtual execution blocked by conservative fill policy.",
    ])
    return report.model_copy(
        update={
            "status": "rejected_virtual_execution",
            "filled_size_usd": 0.0,
            "unfilled_size_usd": report.requested_size_usd,
            "fill_ratio": 0.0,
            "average_price": None,
            "rejected_reason": reason,
            "notes": notes,
        }
    )


def _with_simulation_capabilities(report: VirtualExecutionReport) -> VirtualExecutionReport:
    has_simulated_path = report.simulated_path is not None
    return report.model_copy(
        update={
            "simulation_tier": simulation_tier_for_report(has_simulated_path=has_simulated_path),
            "active_capabilities": capability_codes_for_report(
                impact_aware=report.mode == "impact_aware",
                has_simulated_path=has_simulated_path,
            ),
            "planned_capabilities": planned_capability_codes_for_report(),
        }
    )


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


def _simulated_position_path(
    *,
    reference_price: float,
    average_price: float | None,
    book_price_after: float | None,
    market_impact_percent: float,
    buy_side: bool,
    metrics: LiquidityMetrics,
) -> VirtualSimulatedPositionPath | None:
    if average_price is None or reference_price <= 0:
        return None

    post_trade_price = _post_trade_price(
        reference_price=reference_price,
        average_price=average_price,
        book_price_after=book_price_after,
        market_impact_percent=market_impact_percent,
        buy_side=buy_side,
    )
    initial_impact_delta = post_trade_price - reference_price
    if abs(initial_impact_delta) <= reference_price * 0.000001:
        return None

    decay_lambda = _impact_decay_lambda(metrics)
    offsets = [0.0, 10.0, 30.0, 60.0]
    points = [
        _path_point(
            offset_seconds=offset,
            real_price=reference_price,
            initial_impact_delta=initial_impact_delta,
            decay_lambda=decay_lambda,
        )
        for offset in offsets
    ]
    candle_prices = [average_price, *[point.effective_price for point in points]]
    simulated_candle = VirtualImpactCandle(
        start_offset_seconds=0.0,
        end_offset_seconds=60.0,
        open=average_price,
        high=max(candle_prices),
        low=min(candle_prices),
        close=points[-1].effective_price,
    )
    return VirtualSimulatedPositionPath(
        reference_price=reference_price,
        entry_price=average_price,
        post_trade_price=post_trade_price,
        initial_impact_delta=initial_impact_delta,
        decay_lambda=decay_lambda,
        decay_horizon_seconds=60.0,
        points=points,
        simulated_candle=simulated_candle,
    )


def _post_trade_price(
    *,
    reference_price: float,
    average_price: float,
    book_price_after: float | None,
    market_impact_percent: float,
    buy_side: bool,
) -> float:
    impact_delta = reference_price * market_impact_percent / 100
    estimated_impact_price = reference_price + impact_delta if buy_side else reference_price - impact_delta
    candidates = [reference_price, average_price, estimated_impact_price]
    if book_price_after is not None:
        candidates.append(book_price_after)
    return max(candidates) if buy_side else min(candidates)


def _path_point(
    *,
    offset_seconds: float,
    real_price: float,
    initial_impact_delta: float,
    decay_lambda: float,
) -> VirtualImpactPathPoint:
    decay_multiplier = math.exp(-decay_lambda * offset_seconds)
    impact_delta = initial_impact_delta * decay_multiplier
    return VirtualImpactPathPoint(
        offset_seconds=offset_seconds,
        real_price=real_price,
        impact_delta=impact_delta,
        effective_price=max(real_price + impact_delta, 0.00000001),
        impact_remaining_percent=decay_multiplier * 100,
    )


def _impact_decay_lambda(metrics: LiquidityMetrics) -> float:
    if metrics.impact_risk == "high":
        return 0.018
    if metrics.impact_risk == "medium":
        return 0.04
    return 0.09


def _dedupe_strings(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
