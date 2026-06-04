import { memo, type CSSProperties } from "react";
import { Activity, ArrowDownRight, ArrowUpRight, Clock3 } from "lucide-react";

import { Badge } from "./Badge";
import {
  isMarketOpportunity,
  marketOpportunityLabel,
  marketOpportunityTone,
  riskGateTone,
  statusBadgeLabel,
  statusBadgeTone
} from "@/domain/signal-status";
import { useSignalPrice } from "@/stores/price-store";
import { useSignalStore } from "@/stores/signal-store";
import type { DecisionReason, PendingEntryIntentStatus, RadarSignal, SignalEdgeStatus } from "../types";
import {
  formatPrice,
  isRiskRewardBlocked,
  isFormingCandleSignal,
  isOpenCandleActionableAllowed,
  riskRewardWarningReason,
  isSignalExpired,
  riskLabel,
  signalAge,
  signalTtlLabel,
  signalTradePlanSummary,
  signalUpdatedAge
} from "../utils";

interface SignalCardProps {
  signal: RadarSignal;
  selected: boolean;
  onSelect: (signal: RadarSignal) => void;
}

export const SignalCard = memo(function SignalCard({ signal, selected, onSelect }: SignalCardProps) {
  const isLong = signal.direction === "long";
  const price = useSignalPrice(signal.symbol);
  const expired = isSignalExpired(signal);
  const riskMeta = `Risk: ${riskLabel(signal)} | Opened ${signalAge(signal)} | Updated ${signalUpdatedAge(signal)}`;
  const plan = signalTradePlanSummary(signal);
  const targets = planTargets(plan.targets);
  const rrBlocked = isRiskRewardBlocked(signal);
  const rrWarning = riskRewardWarningReason(signal);
  const noTrade = signal.no_trade_filter ?? null;
  const edge = edgeBadge(signal.edge?.status ?? "unknown", signal.edge?.sample_size, signal.edge?.min_sample_size);
  const formingCandle = isFormingCandleSignal(signal);
  const openCandleAllowed = isOpenCandleActionableAllowed(signal);
  const decisionBadge = decisionBadgeInfo(signal.decision);

  return (
    <button className={`signal-card ${selected ? "selected" : ""}`} onClick={() => onSelect(signal)} type="button">
      <div className="signal-card-head">
        <div>
          <div className="pair-row">
            <strong>{signal.symbol}</strong>
            <Badge>{signal.exchange}</Badge>
            <Badge tone={statusBadgeTone(signal, formingCandle && !openCandleAllowed)}>
              {statusBadgeLabel(signal, formingCandle && !openCandleAllowed)}
            </Badge>
          </div>
          <span className="muted">{signal.strategy.replaceAll("_", " ")}</span>
        </div>
        <Badge tone={isLong ? "green" : "red"}>
          {isLong ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
          {signal.direction.toUpperCase()}
        </Badge>
      </div>

      <div className="signal-score-row">
        <div className="score-ring" style={{ "--score": `${signal.score}%` } as CSSProperties}>
          <span>{signal.score}</span>
        </div>
        <div className="signal-score-meta">
          <strong>{Math.round(signal.confidence * 100)}% Confidence</strong>
          <span className="muted">{riskMeta}</span>
          <span className={`signal-ttl ${expired ? "expired" : ""}`}>
            <Clock3 size={13} />
            {signalTtlLabel(signal)}
          </span>
        </div>
      </div>

      <div className="signal-badge-row">
        {isMarketOpportunity(signal.status) ? <Badge tone="blue">Market opportunity</Badge> : null}
        <Badge tone={marketOpportunityTone(signal)}>{marketOpportunityLabel(signal)}</Badge>
        {signal.risk_gate_status ? <Badge tone={riskGateTone(signal.risk_gate_status)}>RiskGate {signal.risk_gate_status}</Badge> : null}
        {signal.risk_gate_status === "failed" || signal.can_enter === false ? <Badge tone="red">Risk blocked</Badge> : null}
        {signal.auto_entry ? <Badge tone={pendingEntryTone(signal.auto_entry.status)}>{pendingEntryLabel(signal.auto_entry.status)}</Badge> : null}
        {decisionBadge ? <Badge tone={decisionBadge.tone}>{decisionBadge.label}</Badge> : null}
        {formingCandle ? <Badge tone={openCandleAllowed ? "blue" : "yellow"}>{openCandleAllowed ? "forming allowed" : "forming candle"}</Badge> : null}
        <Badge tone={edge.tone}>{edge.label}</Badge>
        {rrBlocked ? <Badge tone="red">RR blocked</Badge> : null}
        {!rrBlocked && rrWarning ? <Badge tone="yellow">RR warning</Badge> : null}
        {plan.fallbackUsed ? <Badge tone="yellow">Fallback plan</Badge> : null}
        {!plan.fallbackUsed && plan.tradePlanComplete === false ? <Badge tone="yellow">Plan incomplete</Badge> : null}
        {noTrade ? <Badge tone={noTrade.blocked ? "red" : noTrade.warnings.length ? "yellow" : "green"}>{noTrade.blocked ? "No-trade" : noTrade.warnings.length ? "No-trade warn" : "No-trade clear"}</Badge> : null}
      </div>

      <div className="setup-grid">
        <span>Entry<strong>{plan.entryType} | {plan.entryZone}</strong></span>
        <span>SL<strong>{formatPrice(plan.stopLoss)}</strong></span>
        <span>TP1<strong>{formatTargetPrice(targets[0])}</strong></span>
        <span>TP2<strong>{formatTargetPrice(targets[1])}</strong></span>
        <span>TP3<strong>{formatTargetPrice(targets[2])}</strong></span>
        <span>Selected RR<strong>{plan.selectedRr == null ? "-" : `${plan.selectedRr.toFixed(2)}R`}</strong></span>
        <span>
          {price ? "Price" : "TF"}
          <strong>{price ? `${formatPrice(price.price)} | ${new Date(price.updatedAt).toLocaleTimeString()}` : signal.timeframe}</strong>
        </span>
      </div>

      <div className="card-reason">
        <Activity size={15} />
        <span>{signal.display_reason ?? signal.explanation[0] ?? "Waiting for context confirmation"}</span>
      </div>
    </button>
  );
});

SignalCard.displayName = "SignalCard";

function planTargets(targets: ReturnType<typeof signalTradePlanSummary>["targets"]) {
  const byLabel = new Map(targets.map((target) => [target.label.toUpperCase(), target]));
  const slots = ["TP1", "TP2", "TP3"].map((label, index) => byLabel.get(label) ?? targets[index] ?? null);
  return slots;
}

function formatTargetPrice(target: ReturnType<typeof planTargets>[number]): string {
  if (!target) return "-";
  const rr = target.rMultiple == null ? "" : ` ${target.rMultiple.toFixed(2)}R`;
  return `${formatPrice(target.price)}${rr}`;
}

function edgeBadge(
  status: SignalEdgeStatus,
  sampleSize = 0,
  minSampleSize = 0
): { label: string; tone: "green" | "red" | "yellow" | "blue" | "purple" | "neutral" } {
  if (status === "positive") return { label: `Edge + ${sampleSize} sample`, tone: "green" };
  if (status === "negative") return { label: `Edge - ${sampleSize} sample`, tone: "red" };
  if (status === "insufficient_sample") return { label: `Edge low ${sampleSize}/${minSampleSize}`, tone: "yellow" };
  return { label: "Edge unknown", tone: "neutral" };
}

function decisionBadgeInfo(
  decision: RadarSignal["decision"]
): { label: string; tone: "green" | "red" | "yellow" | "blue" | "purple" | "neutral" } | null {
  if (!decision) return null;
  const reason = decision.blockers[0] ?? decision.warnings[0] ?? null;
  if (!reason) return null;
  return {
    label: `${decisionSourceLabel(reason)} ${reason.severity}`,
    tone: reason.severity === "blocker" ? "red" : reason.severity === "warning" ? "yellow" : "blue"
  };
}

function decisionSourceLabel(reason: DecisionReason): string {
  return reason.source.replaceAll("_", " ");
}

function pendingEntryTone(
  status: PendingEntryIntentStatus
): "green" | "red" | "yellow" | "blue" | "purple" | "neutral" {
  if (status === "pending") return "blue";
  if (status === "requires_reconfirmation") return "yellow";
  if (status === "failed" || status === "cancelled" || status === "expired") return "red";
  if (status === "triggered" || status === "filling" || status === "filled") return "green";
  return "neutral";
}

function pendingEntryLabel(status: PendingEntryIntentStatus): string {
  if (status === "pending") return "Waiting entry";
  if (status === "requires_reconfirmation") return "Requires reconfirmation";
  return status.replaceAll("_", " ");
}

export const SignalCardById = memo(function SignalCardById({
  signalId,
  selected,
  onSelect
}: {
  signalId: string;
  selected: boolean;
  onSelect: (signal: RadarSignal) => void;
}) {
  const signal = useSignalStore((state) => state.signalsById[signalId] ?? null);
  if (!signal) return null;
  return <SignalCard signal={signal} selected={selected} onSelect={onSelect} />;
});

SignalCardById.displayName = "SignalCardById";
