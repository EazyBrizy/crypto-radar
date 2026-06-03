"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { BarChart3, CheckCircle2, Circle, ExternalLink, FileCheck2, ShieldAlert, XCircle } from "lucide-react";

import { Badge } from "./Badge";
import {
  canShowEnterButton,
  isEntryTouched,
  isExecutionReady,
  isWaitingEntry,
  marketOpportunityLabel,
  marketOpportunityTone,
  riskGateTone
} from "@/domain/signal-status";
import type { DecisionReason, ExecutionGateStatus, ImpactRisk, RadarSignal, SignalEdgeStatus, SignalLayerCheck, VirtualExecutionReport } from "../types";
import {
  entryZone,
  formingCandleReason,
  formatPrice,
  isFormingCandleSignal,
  isOpenCandleActionableAllowed,
  isRiskRewardBlocked,
  isSignalActionableForUi,
  riskLabel,
  riskRewardBlockReason,
  riskRewardWarningReason,
  signalTradePlanSummary
} from "../utils";

const LazySignalDetailsChart = dynamic(
  () => import("@/components/charts/SignalDetailsChart").then((module) => module.SignalDetailsChart),
  {
    loading: () => <div className="chart-panel chart-panel-loading">Loading chart...</div>,
    ssr: false
  }
);

interface SignalDetailsProps {
  signal: RadarSignal | null;
  onPaperTrade: (signal: RadarSignal) => void;
  onReject: (signal: RadarSignal) => void;
  busy: boolean;
  executionPreview: VirtualExecutionReport | null;
  executionPreviewError?: string | null;
  executionPreviewLoading?: boolean;
  tradingActionsDisabled?: boolean;
}

export function SignalDetails({
  signal,
  onPaperTrade,
  onReject,
  busy,
  executionPreview,
  executionPreviewError = null,
  executionPreviewLoading = false,
  tradingActionsDisabled = false
}: SignalDetailsProps) {
  const [chartOpen, setChartOpen] = useState(false);

  if (!signal) {
    return (
      <section className="details-empty">
        <FileCheck2 size={32} />
        <h2>Выбери сигнал</h2>
        <p>Здесь появится торговый план, причины, риск и действия для Manual Confirm.</p>
      </section>
    );
  }

  const isLong = signal.direction === "long";
  const riskFailed = executionPreview?.risk_check?.status === "failed";
  const strategyRiskBlocked = isRiskRewardBlocked(signal);
  const strategyRiskWarning = riskRewardWarningReason(signal);
  const formingCandle = isFormingCandleSignal(signal);
  const openCandleAllowed = isOpenCandleActionableAllowed(signal);
  const formingReason = formingCandleReason(signal);
  const statusAllowsTrade = canShowEnterButton(signal) && (!formingCandle || openCandleAllowed);
  const autoEntryPending = signal.auto_entry?.status === "pending";
  const entryActionDisabled = busy || tradingActionsDisabled || autoEntryPending || strategyRiskBlocked || !statusAllowsTrade || riskFailed;
  const rejectDisabled = busy || tradingActionsDisabled || signal.status === "confirmed" || signal.status === "invalidated" || signal.status === "expired";
  const breakdown = signal.score_breakdown;
  const tradePlan = signalTradePlanSummary(signal);
  const tradePlanComplete = tradePlan.entryPrice != null && tradePlan.stopLoss != null && tradePlan.targets.length > 0;
  const riskRewardOk = tradePlan.selectedRr != null || signal.risk_reward != null;
  const reasons = [
    ...(formingReason ? [formingReason] : []),
    ...(signal.explanation.length ? signal.explanation : ["Стратегия сформировала сигнал по текущему market context."])
  ];

  return (
    <section className="details-panel">
      <div className="details-header">
        <div>
          <span className="muted">Signal Details</span>
          <h2>{signal.symbol} {signal.direction.toUpperCase()} Signal</h2>
        </div>
        <div className="details-badges">
          <Badge tone={isLong ? "green" : "red"}>{signal.direction.toUpperCase()}</Badge>
          {formingCandle ? <Badge tone={openCandleAllowed ? "blue" : "yellow"}>{openCandleAllowed ? "forming allowed" : "forming candle"}</Badge> : null}
          <Badge tone="yellow">Risk {riskLabel(signal)}</Badge>
          <Badge tone={marketOpportunityTone(signal)}>{formingReason ? "preview" : marketOpportunityLabel(signal)}</Badge>
          {signal.risk_gate_status ? <Badge tone={riskGateTone(signal.risk_gate_status)}>RiskGate {signal.risk_gate_status}</Badge> : null}
        </div>
      </div>

      <div className="decision-block">
        <span>Recommended action</span>
        <strong>{recommendedAction(signal)}</strong>
        <p>{signal.status_reason ?? "Decision must use setup status, invalidation and risk context, not direction alone."}</p>
      </div>

      <RadarAnnotationBlock signal={signal} />
      <PullbackGuidanceBlock signal={signal} />
      <BreakoutEntryPlanBlock signal={signal} />
      <LiquiditySweepPlanBlock signal={signal} />
      <AutoEntryBlock signal={signal} />

      <div className="trade-setup">
        <div><span>Entry</span><strong>{tradePlan.entryType} | {tradePlan.entryZone}</strong></div>
        <div><span>Stop Loss</span><strong>{formatPrice(tradePlan.stopLoss)}</strong></div>
        <div><span>Take Profit</span><strong>{formatTargetsInline(tradePlan.targets)}</strong></div>
        <div><span>Selected RR</span><strong>{formatRMultiple(tradePlan.selectedRr)}</strong></div>
      </div>

      <TradePlanDetailBlock signal={signal} />
      <RiskRewardDetailBlock signal={signal} />
      <EdgeSnapshotBlock signal={signal} />
      <DecisionSnapshotBlock signal={signal} />
      <RiskBlockersDetailBlock signal={signal} execution={executionPreview} />

      <ExecutionQualityBlock
        signal={signal}
        execution={executionPreview}
        error={executionPreviewError}
        loading={executionPreviewLoading}
      />

      <StrategyLayersBlock signal={signal} execution={executionPreview} />

      <div className="detail-actions">
        <button className="secondary-action" onClick={() => setChartOpen((open) => !open)} type="button">
          <BarChart3 size={17} /> {chartOpen ? "Hide Chart" : "Show Chart"}
        </button>
      </div>

      {chartOpen ? <LazySignalDetailsChart signal={signal} /> : null}

      <div className="confidence-breakdown">
        <div className="section-title">
          <ShieldAlert size={18} />
          <h3>Confidence Score</h3>
        </div>
        <ScoreLine label="Trend" value={breakdown.trend_score} max={100} />
        <ScoreLine label="Volume" value={breakdown.volume_score} max={100} />
        <ScoreLine label="Liquidity" value={breakdown.liquidity_score} max={100} />
        <ScoreLine label="Orderbook" value={breakdown.orderbook_score} max={100} />
        <ScoreLine label="Risk/Reward" value={breakdown.risk_reward_score} max={100} />
        <ScoreLine label="Volatility" value={breakdown.volatility_score} max={100} />
        <ScoreLine label="Overheat Penalty" value={breakdown.overheat_penalty} max={100} />
        <ScoreLine label="News/Event Risk" value={breakdown.news_event_risk_penalty} max={100} />
      </div>

      <div className="explanation-block">
        <h3>Why this signal?</h3>
        <ul>
          {reasons.map((reason) => (
            <li key={reason}><CheckCircle2 size={16} /><span>{reason}</span></li>
          ))}
        </ul>
      </div>

      <div className="checklist-block">
        <h3>Confirmation Checklist</h3>
        <CheckRow done text="Сетап соответствует стратегии" />
        <CheckRow done={tradePlanComplete} text="Entry, SL and TP are calculated" />
        <CheckRow done={riskRewardOk} text="Risk/Reward is set" />
        <CheckRow done={statusAllowsTrade} text={`Strategy status: ${signal.status.replaceAll("_", " ")}`} />
      </div>

      {signal.risks.length ? (
        <div className="risk-block">
          <h3>Risks</h3>
          {signal.risks.map((risk) => <p key={risk}>{risk}</p>)}
        </div>
      ) : null}

      <div className="detail-actions">
        <button className="primary-action" onClick={() => onPaperTrade(signal)} disabled={entryActionDisabled} type="button">
          <FileCheck2 size={17} /> {statusAllowsTrade ? "Paper Trade" : autoEntryPending ? "Auto Paper Armed" : "Waiting Entry"}
        </button>
        <button className="secondary-action" type="button" disabled>
          <ExternalLink size={17} /> Open Exchange
        </button>
        <button className="danger-action" onClick={() => onReject(signal)} disabled={rejectDisabled} type="button">
          <XCircle size={17} /> Ignore Signal
        </button>
      </div>
      {tradingActionsDisabled ? (
        <p className="form-description">Trading actions disabled until realtime data is current.</p>
      ) : null}
      {riskFailed ? (
        <p className="form-description">Entry is blocked by backend risk gate.</p>
      ) : null}
      {strategyRiskBlocked ? (
        <p className="form-description">Hard R:R execution policy blocks this idea.</p>
      ) : null}
      {!strategyRiskBlocked && strategyRiskWarning ? (
        <p className="form-description">{strategyRiskWarning}</p>
      ) : null}
      {formingReason ? (
        <p className="form-description">{formingReason}</p>
      ) : null}
      {!statusAllowsTrade && !autoEntryPending && !strategyRiskBlocked ? (
        <p className="form-description">{formingReason ? "Wait for candle close before entry." : "Wait for backend RiskGate preview to mark this opportunity execution-ready."}</p>
      ) : null}
    </section>
  );
}

function recommendedAction(signal: RadarSignal): string {
  if (formingCandleReason(signal)) return "Forming candle preview, wait for close";
  if (isExecutionReady(signal.status, signal.decision, signal.can_enter)) return `Execution-ready inside ${entryZone(signal)}`;
  if (signal.risk_gate_status === "failed" || signal.can_enter === false) return "RiskGate blocks entry right now";
  if (isEntryTouched(signal.status)) return "Entry touched, waiting for RiskGate permission";
  if (isWaitingEntry(signal.status)) return "Market setup exists, wait for entry trigger";
  if (signal.status === "watchlist") return "Watch setup formation, no entry yet";
  if (signal.status === "ready") return "Setup exists, wait for confirmation";
  if (signal.status === "wait_for_pullback") return "Wait for pullback or retest";
  if (signal.status === "invalidated") return "Idea is invalidated";
  return `Monitor status ${signal.status.replaceAll("_", " ")}`;
}

function RadarAnnotationBlock({ signal }: { signal: RadarSignal }) {
  const rrReason = riskRewardBlockReason(signal) ?? riskRewardWarningReason(signal);
  if (!signal.rr_status && !signal.risk_gate_status && signal.can_enter == null && !signal.display_reason && !rrReason) return null;
  return (
    <div className="risk-reward-detail-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Radar Display</h3>
        <Badge tone={marketOpportunityTone(signal)}>{marketOpportunityLabel(signal)}</Badge>
      </div>
      {signal.display_reason ? <p>{signal.display_reason}</p> : null}
      <div className="risk-reward-detail-grid">
        <MetricLine label="RR status" value={signal.rr_status ? signal.rr_status.replaceAll("_", " ") : "-"} />
        <MetricLine label="RiskGate" value={signal.risk_gate_status ? signal.risk_gate_status.replaceAll("_", " ") : "not previewed"} />
        <MetricLine label="Can enter" value={signal.can_enter == null ? "not evaluated" : signal.can_enter ? "yes" : "no"} />
        <MetricLine label="Entry state" value={marketOpportunityLabel(signal)} />
      </div>
      {rrReason ? <p>{rrReason}</p> : null}
    </div>
  );
}

function AutoEntryBlock({ signal }: { signal: RadarSignal }) {
  const autoEntry = signal.auto_entry;
  if (!autoEntry) return null;
  return (
    <div className="auto-entry-block">
      <div className="section-title">
        <FileCheck2 size={18} />
        <h3>Auto Entry</h3>
        <Badge tone={autoEntry.status === "pending" ? "blue" : autoEntry.status === "failed" ? "red" : "green"}>
          {autoEntry.status.replaceAll("_", " ")}
        </Badge>
      </div>
      <p>{autoEntry.message ?? `Auto ${autoEntry.mode} entry is ${autoEntry.status}.`}</p>
    </div>
  );
}

function PullbackGuidanceBlock({ signal }: { signal: RadarSignal }) {
  const guidance = pullbackGuidance(signal);
  if (!guidance) return null;
  return (
    <div className="pullback-guidance-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Pullback Wait</h3>
      </div>
      <p>{guidance.reason}</p>
      <div className="pullback-guidance-grid">
        <MetricLine label="Do not chase" value={`${guidance.bodyAtr} body / ${guidance.rangeAtr} range`} />
        <MetricLine label="Wait near" value={guidance.targetLabel} />
        <MetricLine label="Pullback zone" value={guidance.entryZone} />
      </div>
    </div>
  );
}

function BreakoutEntryPlanBlock({ signal }: { signal: RadarSignal }) {
  const plan = breakoutEntryPlan(signal);
  if (!plan) return null;
  return (
    <div className="risk-reward-detail-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Breakout Entries</h3>
      </div>
      <p>{plan.actionableMode}</p>
      <div className="risk-reward-detail-grid">
        <MetricLine label="Aggressive" value={formatPrice(plan.aggressiveEntry)} />
        <MetricLine label="Retest zone" value={plan.conservativeZone} />
        <MetricLine label="Measured move" value={formatPrice(plan.measuredMoveTarget)} />
      </div>
    </div>
  );
}

function breakoutEntryPlan(signal: RadarSignal): {
  aggressiveEntry: number | null;
  conservativeZone: string;
  measuredMoveTarget: number | null;
  actionableMode: string;
} | null {
  if (signal.strategy !== "volatility_squeeze_breakout") return null;
  const metadata = signal.invalidation?.metadata ?? {};
  const aggressiveEntry = numberMetadata(metadata, "aggressive_entry") ?? signal.entry_min ?? signal.entry_max;
  const conservativeMin = numberMetadata(metadata, "conservative_entry_min");
  const conservativeMax = numberMetadata(metadata, "conservative_entry_max");
  const conservativeEntry = numberMetadata(metadata, "conservative_entry");
  const measuredMoveTarget = numberMetadata(metadata, "measured_move_target");
  if (aggressiveEntry == null && conservativeEntry == null && measuredMoveTarget == null) return null;
  const conservativeZone = conservativeMin == null && conservativeMax == null
    ? formatPrice(conservativeEntry)
    : `${formatPrice(conservativeMin)} - ${formatPrice(conservativeMax)}`;
  return {
    aggressiveEntry,
    conservativeZone,
    measuredMoveTarget,
    actionableMode: !isSignalActionableForUi(signal)
      ? "Entry is preview-only until the signal is fully actionable."
      : signal.status === "wait_for_pullback"
      ? "Actionable entry is the retest zone while the breakout candle cools off."
      : "Actionable entry follows the current strategy status; retest is the conservative alternative."
  };
}

function LiquiditySweepPlanBlock({ signal }: { signal: RadarSignal }) {
  const plan = liquiditySweepPlan(signal);
  if (!plan) return null;
  return (
    <div className="risk-reward-detail-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Liquidity Sweep</h3>
      </div>
      <p>{plan.mode}</p>
      <div className="risk-reward-detail-grid">
        <MetricLine label="Swept level" value={formatPrice(plan.sweptLevel)} />
        <MetricLine label="Wick" value={formatRatio(plan.wickRatio)} />
        <MetricLine label="Level touches" value={plan.levelTouches == null ? "-" : String(plan.levelTouches)} />
        <MetricLine label="Aggressive" value={formatPrice(plan.aggressiveEntry)} />
        <MetricLine label="Confirm zone" value={plan.confirmationZone} />
      </div>
    </div>
  );
}

function liquiditySweepPlan(signal: RadarSignal): {
  sweptLevel: number | null;
  wickRatio: number | null;
  levelTouches: number | null;
  aggressiveEntry: number | null;
  confirmationZone: string;
  mode: string;
} | null {
  if (signal.strategy !== "liquidity_sweep_reversal") return null;
  const metadata = signal.invalidation?.metadata ?? {};
  const sweptLevel = numberMetadata(metadata, "swept_level");
  const wickRatio = numberMetadata(metadata, "wick_ratio");
  const levelTouches = numberMetadata(metadata, "level_touch_count");
  const aggressiveEntry = numberMetadata(metadata, "aggressive_entry") ?? signal.entry_min ?? signal.entry_max;
  const conservativeMin = numberMetadata(metadata, "conservative_entry_min");
  const conservativeMax = numberMetadata(metadata, "conservative_entry_max");
  const conservativeTrigger = numberMetadata(metadata, "conservative_trigger");
  if (sweptLevel == null && aggressiveEntry == null && conservativeTrigger == null) return null;
  return {
    sweptLevel,
    wickRatio,
    levelTouches,
    aggressiveEntry,
    confirmationZone: conservativeMin == null && conservativeMax == null
      ? formatPrice(conservativeTrigger)
      : `${formatPrice(conservativeMin)} - ${formatPrice(conservativeMax)}`,
    mode: isSignalActionableForUi(signal)
      ? "Sweep is actionable only after reclaim, wick, volume and RR checks stay valid."
      : "Sweep is staged; wait for reclaim or a confirmation candle through micro structure."
  };
}

function pullbackGuidance(signal: RadarSignal): {
  reason: string;
  bodyAtr: string;
  rangeAtr: string;
  targetLabel: string;
  entryZone: string;
} | null {
  if (signal.status !== "wait_for_pullback") return null;
  const check = signal.confirmation?.checks.find((item) => item.name === "overextension_guard");
  const metadata = check?.metadata ?? {};
  const targetLabel = stringMetadata(metadata, "pullback_target_label") ?? "planned retest";
  const entryMin = numberMetadata(metadata, "pullback_entry_min") ?? signal.entry_min;
  const entryMax = numberMetadata(metadata, "pullback_entry_max") ?? signal.entry_max;
  return {
    reason: check?.reason ?? signal.status_reason ?? "Signal candle is extended; wait for a retest instead of market entry.",
    bodyAtr: atrMetric(metadata, "body_atr", "body_threshold"),
    rangeAtr: atrMetric(metadata, "range_atr", "range_threshold"),
    targetLabel,
    entryZone: entryMin == null && entryMax == null ? entryZone(signal) : `${formatPrice(entryMin)} - ${formatPrice(entryMax)}`
  };
}

function atrMetric(metadata: Record<string, unknown>, valueKey: string, thresholdKey: string): string {
  const value = numberMetadata(metadata, valueKey);
  const threshold = numberMetadata(metadata, thresholdKey);
  if (value == null) return "-";
  return threshold == null ? `${value.toFixed(2)} ATR` : `${value.toFixed(2)} / ${threshold.toFixed(2)} ATR`;
}

function numberMetadata(metadata: Record<string, unknown>, key: string): number | null {
  const value = metadata[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringMetadata(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key];
  return typeof value === "string" && value ? value : null;
}

function RiskRewardDetailBlock({ signal }: { signal: RadarSignal }) {
  const details = riskRewardDetails(signal);
  if (!details) return null;
  return (
    <div className="risk-reward-detail-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Risk / Reward Guard</h3>
      </div>
      <p>{details.reason}</p>
      <div className="risk-reward-detail-grid">
        <MetricLine label="Nearest RR" value={formatRMultiple(details.firstTargetRr)} />
        <MetricLine label="Final RR" value={formatRMultiple(details.finalTargetRr)} />
        <MetricLine label="Selected RR" value={formatRMultiple(details.selectedRr)} />
        <MetricLine label="Guard target" value={details.selectedTarget} />
        <MetricLine label="Min execution/reporting RR" value={formatRMultiple(details.minRr)} />
      </div>
    </div>
  );
}

function riskRewardDetails(signal: RadarSignal): {
  firstTargetRr: number | null;
  finalTargetRr: number | null;
  selectedRr: number | null;
  selectedTarget: string;
  minRr: number | null;
  reason: string;
} | null {
  const check = signal.confirmation?.checks.find((item) => item.name === "risk_reward_guard");
  const metadata = check?.metadata ?? {};
  const firstTargetRr = signal.first_target_rr ?? numberMetadata(metadata, "first_target_rr");
  const finalTargetRr = signal.final_target_rr ?? numberMetadata(metadata, "final_target_rr");
  const selectedRr = signal.selected_rr ?? numberMetadata(metadata, "selected_rr") ?? signal.risk_reward;
  const minRr = signal.min_rr_ratio ?? numberMetadata(metadata, "min_rr_ratio");
  const selectedTarget = formatRrTarget(
    signal.selected_rr_target
      ?? stringMetadata(metadata, "selected_rr_target")
      ?? stringMetadata(metadata, "selected_rr_label")
  );
  if (firstTargetRr == null && finalTargetRr == null && selectedRr == null && !check) return null;
  return {
    firstTargetRr,
    finalTargetRr,
    selectedRr,
    selectedTarget,
    minRr,
    reason: check?.reason ?? "Strategy RR classification is shown here; final entry permission still comes from the risk gate."
  };
}

function formatRMultiple(value: number | null): string {
  return value == null ? "-" : `${value.toFixed(2)}R`;
}

function formatRatio(value: number | null): string {
  return value == null ? "-" : `${Math.round(value * 100)}%`;
}

function formatRrTarget(value: string | null): string {
  if (!value) return "-";
  return value.replaceAll("_", " ");
}

function formatTradePlanCompleteness(plan: ReturnType<typeof signalTradePlanSummary>): string {
  if (plan.tradePlanComplete === true) return "complete";
  if (plan.tradePlanComplete === false && plan.missing.length) return `missing ${plan.missing.join(", ").replaceAll("_", " ")}`;
  if (plan.tradePlanComplete === false) return "incomplete";
  return "-";
}

function formatTradePlanFallback(plan: ReturnType<typeof signalTradePlanSummary>): string {
  if (!plan.fallbackUsed) return "none";
  const parts = [];
  if (plan.fallbackStopUsed) parts.push("stop");
  if (plan.fallbackTargetsUsed) parts.push("targets");
  return parts.length ? parts.join(", ") : "used";
}

function TradePlanDetailBlock({ signal }: { signal: RadarSignal }) {
  const plan = signalTradePlanSummary(signal);
  const invalidation = signal.trade_plan?.invalidation ?? null;
  const planBadgeTone = plan.fallbackUsed || plan.tradePlanComplete === false ? "yellow" : plan.hasTradePlan ? "blue" : "neutral";
  return (
    <div className="risk-reward-detail-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Trade Plan</h3>
        <Badge tone={planBadgeTone}>{plan.hasTradePlan ? "trade_plan" : "legacy fallback"}</Badge>
      </div>
      <p>{plan.hasTradePlan ? "Backend trade_plan is active for entry, stop, targets and selected RR." : "Old signal contract is displayed through legacy entry, SL and TP fields."}</p>
      <div className="risk-reward-detail-grid">
        <MetricLine label="Entry type" value={plan.entryType} />
        <MetricLine label="Entry zone" value={plan.entryZone} />
        <MetricLine label="Entry price" value={formatPrice(plan.entryPrice)} />
        <MetricLine label="Stop loss" value={formatPrice(plan.stopLoss)} />
        <MetricLine label="Completeness" value={formatTradePlanCompleteness(plan)} />
        <MetricLine label="Fallback" value={formatTradePlanFallback(plan)} />
        <MetricLine label="Selected RR" value={formatRMultiple(plan.selectedRr)} />
        <MetricLine label="RR target" value={formatRrTarget(plan.selectedRrTarget)} />
        <MetricLine label="Min execution/reporting RR" value={formatRMultiple(plan.minRr)} />
        <MetricLine label="Invalidation" value={formatPrice(invalidation?.hard_stop ?? invalidation?.price ?? signal.invalidation?.hard_stop ?? signal.invalidation?.price)} />
      </div>
      {plan.targets.length ? (
        <div className="target-state-list">
          {plan.targets.map((target, index) => (
            <span key={`${target.label}:${target.price ?? index}`}>
              <strong>{target.label}</strong> {formatPrice(target.price)}
              {target.rMultiple == null ? "" : ` | ${formatRMultiple(target.rMultiple)}`}
              {target.closePercent == null ? "" : ` | ${target.closePercent}%`}
              {target.action ? ` | ${formatLayerCheckName(target.action)}` : ""}
              {target.source ? ` | ${formatLayerCheckName(target.source)}` : ""}
            </span>
          ))}
        </div>
      ) : null}
      {invalidation?.conditions.length ? (
        <div className="invalidation-list">
          {invalidation.conditions.slice(0, 4).map((condition) => (
            <span key={condition}>{condition}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function EdgeSnapshotBlock({ signal }: { signal: RadarSignal }) {
  const edge = signal.edge ?? null;
  const badge = edgeStatusBadge(edge?.status ?? "unknown");
  return (
    <div className="risk-reward-detail-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Edge Snapshot</h3>
        <Badge tone={badge.tone}>{badge.label}</Badge>
      </div>
      <p>{edge ? "Historical/forward outcome calibration used by real-entry risk gating." : "Edge was not evaluated for this signal yet."}</p>
      <div className="risk-reward-detail-grid">
        <MetricLine label="Sample" value={edge ? `${edge.sample_size}/${edge.min_sample_size}` : "unknown"} />
        <MetricLine label="Winrate" value={formatRatioPercent(edge?.winrate ?? null)} />
        <MetricLine label="Avg win" value={formatRMultiple(edge?.avg_win_r ?? null)} />
        <MetricLine label="Avg loss" value={formatRMultiple(edge?.avg_loss_r ?? null)} />
        <MetricLine label="Expectancy" value={formatRMultiple(edge?.expectancy_r ?? null)} />
        <MetricLine label="After costs" value={formatRMultiple(edge?.expectancy_after_costs_r ?? null)} />
        <MetricLine label="Profit factor" value={edge?.profit_factor == null ? "-" : edge.profit_factor.toFixed(2)} />
        <MetricLine label="Confidence" value={edge ? `${Math.round(edge.confidence_score * 100)}%` : "-"} />
        <MetricLine label="Source" value={edge?.source ?? "none"} />
        <MetricLine label="Score bucket" value={edge?.score_bucket ?? "-"} />
      </div>
    </div>
  );
}

function DecisionSnapshotBlock({ signal }: { signal: RadarSignal }) {
  const decision = signal.decision ?? null;
  if (!decision) return null;
  const topReason = decision.blockers[0] ?? decision.warnings[0] ?? null;
  return (
    <div className="risk-reward-detail-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Decision Snapshot</h3>
        {topReason ? <Badge tone={topReason.severity === "blocker" ? "red" : "yellow"}>{formatDecisionSource(topReason.source)}</Badge> : null}
      </div>
      <div className="risk-reward-detail-grid">
        <MetricLine label="Setup valid" value={formatDecisionBool(decision.setup_valid)} />
        <MetricLine label="Trade plan valid" value={formatDecisionBool(decision.trade_plan_valid)} />
        <MetricLine label="Signal actionable" value={formatDecisionBool(decision.signal_actionable)} />
        <MetricLine label="Virtual execution" value={formatDecisionOptionalBool(decision.execution_allowed_virtual)} />
        <MetricLine label="Real execution" value={formatDecisionOptionalBool(decision.execution_allowed_real)} />
        <MetricLine label="Market context" value={decision.market_context_score.toFixed(0)} />
      </div>
      <DecisionReasonList title="Blockers" reasons={decision.blockers} />
      <DecisionReasonList title="Warnings" reasons={decision.warnings} />
    </div>
  );
}

function DecisionReasonList({ title, reasons }: { title: string; reasons: DecisionReason[] }) {
  if (!reasons.length) return null;
  return (
    <div className="layer-check-group">
      <strong>{title}</strong>
      {reasons.map((reason) => (
        <span className={`layer-check-${reason.severity === "blocker" ? "failed" : reason.severity}`} key={`${reason.source}:${reason.scope}:${reason.code}:${reason.message}`}>
          {formatDecisionSource(reason.source)} / {reason.scope}: {reason.message}
        </span>
      ))}
    </div>
  );
}

function RiskBlockersDetailBlock({
  signal,
  execution
}: {
  signal: RadarSignal;
  execution: VirtualExecutionReport | null;
}) {
  const rrBlockReason = riskRewardBlockReason(signal);
  const rrWarningReason = riskRewardWarningReason(signal);
  const noTrade = signal.no_trade_filter ?? null;
  const riskDecision = execution?.risk_decision ?? null;
  const riskCheck = execution?.risk_check ?? null;
  const decision = signal.decision ?? null;
  const blockers = dedupe([
    ...(rrBlockReason ? [rrBlockReason] : []),
    ...(signal.risk_gate_status === "failed" && signal.display_reason ? [signal.display_reason] : []),
    ...(noTrade?.blockers ?? []),
    ...(decision?.blockers.map((reason) => reason.message) ?? []),
    ...(riskDecision?.blockers ?? riskCheck?.blockers ?? [])
  ]);
  const warnings = dedupe([
    ...(!rrBlockReason && rrWarningReason ? [rrWarningReason] : []),
    ...(signal.risk_gate_status === "warning" && signal.display_reason ? [signal.display_reason] : []),
    ...(noTrade?.warnings ?? []),
    ...(decision?.warnings.map((reason) => reason.message) ?? []),
    ...(riskDecision?.warnings ?? riskCheck?.warnings ?? [])
  ]);
  if (!blockers.length && !warnings.length) return null;
  return (
    <div className="risk-block">
      <h3>Risk blockers / warnings</h3>
      {blockers.length ? (
        <ul className="risk-blocker-list">
          {blockers.map((blocker) => (
            <li key={blocker}>{blocker}</li>
          ))}
        </ul>
      ) : null}
      {warnings.map((warning) => (
        <p key={warning}>{warning}</p>
      ))}
    </div>
  );
}

function StrategyLayersBlock({ signal, execution }: { signal: RadarSignal; execution: VirtualExecutionReport | null }) {
  const plan = signalTradePlanSummary(signal);
  const riskGate = signal.risk_gate_status ?? execution?.risk_decision?.status ?? execution?.risk_check?.status ?? "-";
  const regimeChecks = signal.regime?.checks.filter((check) => check.status !== "passed").slice(0, 4) ?? [];
  const layers = [
    {
      label: "quality",
      value: signal.quality ? `${signal.quality.tier.replace("_", " ")} / ${signal.quality.score}` : "-"
    },
    {
      label: "regime",
      value: signal.regime ? `${signal.regime.direction} / ${signal.regime.alignment}` : "-"
    },
    {
      label: "setup",
      value: signal.setup ? signal.setup.stage : "-"
    },
    {
      label: "risk_reward",
      value: `${isRiskRewardBlocked(signal) ? "blocked" : riskRewardWarningReason(signal) ? "warning" : "selected"} ${formatRMultiple(plan.selectedRr)}`
    },
    {
      label: "confirmation",
      value: signal.confirmation ? (signal.confirmation.passed ? "passed" : "pending") : "-"
    },
    {
      label: "invalidation",
      value: signal.invalidation?.price == null ? "-" : formatPrice(signal.invalidation.price)
    },
    {
      label: "exit_plan",
      value: signal.exit_plan?.targets.length ? `${signal.exit_plan.targets.length} targets` : "-"
    },
    {
      label: "trade_plan",
      value: plan.hasTradePlan ? `${plan.targets.length} targets` : "legacy fallback"
    },
    {
      label: "edge",
      value: signal.edge ? `${signal.edge.status} / ${signal.edge.sample_size}` : "unknown"
    },
    {
      label: "risk_gate",
      value: riskGate
    }
  ];
  const checkGroups = [
    { label: "quality", checks: signal.quality?.checks ?? [] },
    { label: "regime", checks: signal.regime?.checks ?? [] },
    { label: "setup", checks: signal.setup?.checks ?? [] },
    { label: "confirmation", checks: signal.confirmation?.checks ?? [] },
    { label: "no_trade", checks: signal.no_trade_filter?.checks ?? [] }
  ];

  return (
    <div className="strategy-layers-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Strategy Layers</h3>
      </div>
      <div className="strategy-layer-grid">
        {layers.map((layer) => (
          <div className="strategy-layer-metric" key={layer.label}>
            <span>{layer.label}</span>
            <strong>{layer.value}</strong>
          </div>
        ))}
      </div>
      {signal.invalidation?.conditions.length ? (
        <div className="invalidation-list">
          {signal.invalidation.conditions.slice(0, 3).map((condition) => (
            <span key={condition}>{condition}</span>
          ))}
        </div>
      ) : null}
      {regimeChecks.length ? (
        <div className="layer-check-list">
          {regimeChecks.map((check) => (
            <span className={`layer-check-${check.status}`} key={`${check.name}:${check.reason ?? ""}`}>
              {formatLayerCheckName(check.name)}: {check.reason ?? check.status}
            </span>
          ))}
        </div>
      ) : null}
      <div className="layer-check-groups">
        {checkGroups.filter((group) => group.checks.length).map((group) => (
          <div className="layer-check-group" key={group.label}>
            <strong>{group.label}</strong>
            {group.checks.slice(0, 5).map((check) => (
              <span className={`layer-check-${check.status}`} key={`${group.label}:${check.name}:${check.reason ?? ""}`}>
                {formatLayerCheckName(check.name)}: {formatLayerCheckReason(check)}
              </span>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function formatLayerCheckName(value: string): string {
  return value.replaceAll("_", " ");
}

function formatLayerCheckReason(check: SignalLayerCheck): string {
  if (check.reason) return check.reason;
  if (check.score != null) return `${check.status} (${check.score})`;
  return check.status;
}

function formatTargetsInline(targets: ReturnType<typeof signalTradePlanSummary>["targets"]): string {
  if (!targets.length) return "-";
  return targets.slice(0, 3).map((target) => `${target.label} ${formatPrice(target.price)}`).join(" / ");
}

function formatRatioPercent(value: number | null): string {
  if (value == null) return "-";
  return `${Math.round(value * 100)}%`;
}

function edgeStatusBadge(status: SignalEdgeStatus): { label: string; tone: "green" | "red" | "yellow" | "blue" | "purple" | "neutral" } {
  if (status === "positive") return { label: "positive edge", tone: "green" };
  if (status === "negative") return { label: "negative edge", tone: "red" };
  if (status === "insufficient_sample") return { label: "insufficient sample", tone: "yellow" };
  return { label: "unknown edge", tone: "neutral" };
}

function formatDecisionBool(value: boolean): string {
  return value ? "yes" : "no";
}

function formatDecisionOptionalBool(value: boolean | null): string {
  if (value == null) return "not evaluated";
  return formatDecisionBool(value);
}

function formatDecisionSource(value: DecisionReason["source"]): string {
  return value.replaceAll("_", " ");
}

function dedupe(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function ExecutionQualityBlock({
  signal,
  execution,
  error,
  loading
}: {
  signal: RadarSignal;
  execution: VirtualExecutionReport | null;
  error: string | null;
  loading: boolean;
}) {
  const gateStatus = execution?.quality_gate.status ?? scoreGateStatus(signal);
  const impactRisk = execution?.liquidity.impact_risk ?? scoreImpactRisk(signal);
  const tone = gateTone(gateStatus, impactRisk);
  const executionLabel = loading && !execution ? "Checking" : executionQualityLabel(gateStatus, impactRisk);
  const marketOrder = gateStatus === "blocked" || impactRisk === "high"
    ? "Not realistic"
    : gateStatus === "warning"
      ? "Use smaller size"
      : "Allowed";
  const orderType = gateStatus === "blocked" || impactRisk === "high" ? "Limit" : "Market / Limit";
  const safeSize = execution?.quality_gate.suggested_max_size_usd
    ?? (execution && execution.quality_gate.status !== "blocked" ? execution.filled_size_usd : null);
  const simulatedPath = execution?.simulated_path ?? null;
  const positionSizing = execution?.position_sizing ?? null;
  const stopLossPlan = execution?.stop_loss_plan ?? null;
  const takeProfitPlan = execution?.take_profit_plan ?? null;
  const breakevenPlan = execution?.breakeven_plan ?? null;
  const trailingStopPlan = execution?.trailing_stop_plan ?? null;
  const futuresRiskPlan = execution?.futures_risk_plan ?? null;
  const riskAdjustmentPlan = execution?.risk_adjustment_plan ?? null;
  const riskCheck = execution?.risk_check ?? null;
  const riskDecision = execution?.risk_decision ?? null;

  return (
    <div className="execution-quality-block">
      <div className="section-title">
        <ShieldAlert size={18} />
        <h3>Reality Check</h3>
        <Badge tone={tone}>{executionLabel}</Badge>
      </div>
      <div className="reality-check-summary">
        <span>Signal: {signal.score >= 70 ? "good" : "watchlist"}</span>
        <span>Chart: {signal.score >= 80 ? "strong" : "mixed"}</span>
        <span>Execution: {executionQualityText(gateStatus, impactRisk).toLowerCase()}</span>
      </div>
      <div className="execution-quality-grid">
        <MetricLine label="Expected slippage" value={execution ? formatCompactPercent(execution.entry_slippage_bps / 100) : error ? "Preview error" : "Preview pending"} />
        <MetricLine label="Market impact" value={impactRiskLabel(impactRisk)} />
        <MetricLine label="Safe size" value={safeSize == null ? "-" : `$${safeSize.toFixed(0)}`} />
        <MetricLine label="Risk budget" value={positionSizing ? `$${positionSizing.risk_amount.toFixed(2)}` : "-"} />
        <MetricLine label="Adjusted risk" value={riskAdjustmentPlan ? `${riskAdjustmentPlan.adjusted_risk_percent.toFixed(3)}%` : "-"} />
        <MetricLine label="Risk gate" value={riskDecision ? riskDecision.status : riskCheck ? riskCheck.status : "-"} />
        <MetricLine label="Risk size" value={positionSizing ? `$${positionSizing.notional.toFixed(0)}` : "-"} />
        <MetricLine label="Margin" value={positionSizing ? `$${positionSizing.required_margin.toFixed(0)} @ ${positionSizing.leverage}x` : "-"} />
        <MetricLine label="Effective risk" value={riskCheck ? `$${riskCheck.effective_risk_amount.toFixed(2)}` : "-"} />
        <MetricLine label="Daily risk" value={formatRiskUsage(riskCheck?.daily_risk_used_percent, riskCheck?.max_daily_loss_percent)} />
        <MetricLine label="Account drawdown" value={formatRiskUsage(riskCheck?.account_drawdown_percent, riskCheck?.max_account_drawdown_percent)} />
        <MetricLine label="Open risk" value={formatRiskUsage(riskCheck?.open_risk_used_percent, riskCheck?.max_open_risk_percent)} />
        <MetricLine label="Correlated risk" value={formatRiskUsage(riskCheck?.correlated_risk_used_percent, riskCheck?.max_correlated_risk_percent)} />
        <MetricLine label="Exchange rules" value={riskCheck ? riskCheck.exchange_rule_status : "-"} />
        <MetricLine label="Market data" value={riskCheck ? riskCheck.market_data_status : "-"} />
        <MetricLine label="Bid / Ask" value={riskCheck?.best_bid && riskCheck?.best_ask ? `${formatExecutionPrice(riskCheck.best_bid)} / ${formatExecutionPrice(riskCheck.best_ask)}` : "-"} />
        <MetricLine label="Mark price" value={riskCheck?.mark_price ? formatExecutionPrice(riskCheck.mark_price) : "-"} />
        <MetricLine label="Spread" value={riskCheck?.spread_bps == null ? "-" : `${riskCheck.spread_bps.toFixed(1)} bps`} />
        <MetricLine label="Price drift" value={riskCheck?.price_deviation_bps == null ? "-" : `${riskCheck.price_deviation_bps.toFixed(1)} bps`} />
        <MetricLine label="Book depth" value={riskCheck?.orderbook_depth_usd == null ? "-" : `$${riskCheck.orderbook_depth_usd.toFixed(0)}`} />
        <MetricLine label="Fee source" value={riskCheck?.fee_rate_source ?? "-"} />
        <MetricLine label="Taker fee" value={riskCheck?.taker_fee_rate == null ? "-" : `${(riskCheck.taker_fee_rate * 100).toFixed(3)}%`} />
        <MetricLine label="Funding buffer" value={riskCheck ? `$${riskCheck.funding_buffer_amount.toFixed(2)}` : "-"} />
        <MetricLine label="Close-only" value={riskCheck?.close_only ? "yes" : "no"} />
        <MetricLine label="Protection" value={riskCheck ? riskCheck.protection_state.replace("_", " ") : "-"} />
        <MetricLine label="Planned stop" value={stopLossPlan ? formatExecutionPrice(stopLossPlan.stop_loss_price) : formatPrice(signal.stop_loss)} />
        <MetricLine label="Exit plan" value={takeProfitPlan ? takeProfitPlan.targets.map((target) => `${target.label} ${target.r_multiple}R`).join(" / ") : "-"} />
        <MetricLine label="Breakeven" value={breakevenPlan ? `${formatExecutionPrice(breakevenPlan.trigger_price)} -> ${formatExecutionPrice(breakevenPlan.breakeven_stop_price)}` : "-"} />
        <MetricLine label="Trailing" value={trailingStopPlan?.enabled ? trailingStopPlan.mode.toUpperCase() : "Off"} />
        <MetricLine label="Futures guard" value={futuresRiskPlan ? futuresRiskPlan.status : "-"} />
        <MetricLine label="Order type" value={orderType} />
        <MetricLine label="Market order" value={marketOrder} />
        <MetricLine label="Fill" value={execution ? `${Math.round(execution.fill_ratio * 100)}%` : "-"} />
        <MetricLine label="Post-impact" value={simulatedPath ? formatExecutionPrice(simulatedPath.post_trade_price) : "-"} />
        <MetricLine label="Decay 60s" value={simulatedPath ? formatExecutionPrice(simulatedPath.simulated_candle.close) : "-"} />
        <MetricLine label="Model" value={execution ? execution.simulation_tier.toUpperCase() : "MVP"} />
      </div>
      {execution?.quality_gate.message ? (
        <p className="execution-quality-message">{execution.quality_gate.message}</p>
      ) : null}
      {riskCheck?.blockers.length ? (
        <ul className="risk-blocker-list">
          {riskCheck.blockers.map((blocker) => (
            <li key={blocker}>{blocker}</li>
          ))}
        </ul>
      ) : null}
      {error && !execution ? (
        <p className="execution-quality-message">Risk preview unavailable: {error}</p>
      ) : null}
      {execution ? (
        <div className="reality-check-copy">
          <p>{realityCheckReason(execution)}</p>
          <p>{realityCheckRecommendation(execution, orderType)}</p>
        </div>
      ) : null}
    </div>
  );
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="execution-quality-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatExecutionPrice(price: number): string {
  if (Math.abs(price) >= 1000) return price.toFixed(0);
  if (Math.abs(price) >= 1) return price.toFixed(2);
  return price.toPrecision(4);
}

function formatRiskUsage(used?: number | null, limit?: number | null): string {
  if (used == null || limit == null) return "-";
  return `${formatCompactPercent(used)} / ${limit <= 0 ? "Off" : formatCompactPercent(limit)}`;
}

function executionQualityText(status: ExecutionGateStatus, impactRisk: ImpactRisk): string {
  if (status === "blocked") return "Poor";
  if (status === "warning" || impactRisk !== "low") return "Risky";
  return "Good";
}

function realityCheckReason(execution: VirtualExecutionReport): string {
  const depthOne = execution.liquidity.orderbook_depth_1_percent_usd;
  const depthRatio = depthOne > 0 ? execution.requested_size_usd / depthOne * 100 : null;
  const slippagePercent = execution.entry_slippage_bps / 100;
  const exitSlippagePercent = execution.exit_slippage_bps / 100;

  if (execution.quality_gate.status === "blocked") {
    const depthText = depthRatio == null ? "current depth" : `${formatCompactPercent(depthRatio)} of liquidity inside 1%`;
    return `Your virtual size would consume ${depthText}. The simulated entry could be worse by about ${formatCompactPercent(slippagePercent)}, and simulated stop execution could add about ${formatCompactPercent(exitSlippagePercent)} friction.`;
  }
  if (execution.quality_gate.status === "warning" || execution.liquidity.impact_risk !== "low") {
    return `The virtual fill is usable, but execution is sensitive: expected entry slippage is ${formatCompactPercent(slippagePercent)} and impact risk is ${impactRiskLabel(execution.liquidity.impact_risk)}.`;
  }
  return `The requested size fits current liquidity with expected entry slippage around ${formatCompactPercent(slippagePercent)}.`;
}

function realityCheckRecommendation(execution: VirtualExecutionReport, orderType: string): string {
  const suggestedMax = execution.quality_gate.suggested_max_size_usd;
  if (execution.quality_gate.status === "blocked") {
    return suggestedMax == null
      ? `Recommendation: use a much smaller virtual ${orderType.toLowerCase()} setup or treat this simulation as unrealistic.`
      : `Recommendation: reduce virtual size to about $${suggestedMax.toFixed(0)}, use a limit order, or treat this simulation as unrealistic.`;
  }
  if (execution.quality_gate.status === "warning" || execution.liquidity.impact_risk !== "low") {
    return `Recommendation: prefer ${orderType.toLowerCase()}, reduce size if the book thins out, and avoid chasing a market order.`;
  }
  return "Recommendation: execution looks realistic for this virtual size.";
}

function formatCompactPercent(value: number): string {
  if (!Number.isFinite(value)) return "0%";
  if (value > 0 && value < 0.01) return "<0.01%";
  if (value < 10) return `${value.toFixed(2)}%`;
  return `${value.toFixed(1)}%`;
}

function ScoreLine({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className="score-line">
      <span>{label}</span>
      <progress value={value} max={max} />
      <strong>{Math.round(value)}/{max}</strong>
    </div>
  );
}

function scoreGateStatus(signal: RadarSignal): ExecutionGateStatus {
  const liquidity = signal.score_breakdown.liquidity_score;
  const orderbook = signal.score_breakdown.orderbook_score;
  if (liquidity < 25 || orderbook < 20) return "blocked";
  if (liquidity < 45 || orderbook < 40) return "warning";
  return "passed";
}

function scoreImpactRisk(signal: RadarSignal): ImpactRisk {
  const liquidity = signal.score_breakdown.liquidity_score;
  const orderbook = signal.score_breakdown.orderbook_score;
  if (liquidity < 35 || orderbook < 30) return "high";
  if (liquidity < 60 || orderbook < 50) return "medium";
  return "low";
}

function executionQualityLabel(status: ExecutionGateStatus, impactRisk: ImpactRisk): string {
  if (status === "blocked") return "Low";
  if (status === "warning" || impactRisk !== "low") return "Medium";
  return "High";
}

function impactRiskLabel(risk: ImpactRisk): string {
  if (risk === "high") return "High";
  if (risk === "medium") return "Medium";
  return "Low";
}

function gateTone(status: ExecutionGateStatus, risk: ImpactRisk): "green" | "red" | "yellow" {
  if (status === "blocked" || risk === "high") return "red";
  if (status === "warning" || risk === "medium") return "yellow";
  return "green";
}

function CheckRow({ done = false, text }: { done?: boolean; text: string }) {
  return (
    <div className="check-row">
      {done ? <CheckCircle2 size={16} /> : <Circle size={16} />}
      <span>{text}</span>
    </div>
  );
}
