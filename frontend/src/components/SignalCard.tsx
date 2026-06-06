import { memo, type CSSProperties } from "react";
import { Activity, ArrowDownRight, ArrowUpRight, Clock3 } from "lucide-react";

import { Badge } from "./Badge";
import { statusBadgeLabel, statusBadgeTone } from "@/domain/signal-status";
import { useSignalPrice } from "@/stores/price-store";
import { useSignalStore } from "@/stores/signal-store";
import type { RadarSignal, SignalBadgeView, SignalTargetView } from "../types";
import { formatPrice, signalTtlLabel } from "../utils";

interface SignalCardProps {
  signal: RadarSignal;
  selected: boolean;
  onSelect: (signal: RadarSignal) => void;
}

export const SignalCard = memo(function SignalCard({ signal, selected, onSelect }: SignalCardProps) {
  const view = signal.card_view ?? null;
  const isLong = signal.direction === "long";
  const price = useSignalPrice(signal.symbol);

  if (!view) {
    return (
      <button className={`signal-card ${selected ? "selected" : ""}`} onClick={() => onSelect(signal)} type="button">
        <div className="signal-card-head">
          <div>
            <div className="pair-row">
              <strong>{signal.symbol}</strong>
              <Badge>{signal.exchange}</Badge>
              <Badge tone="red">API contract error</Badge>
            </div>
            <span className="muted">SignalCardView is missing</span>
          </div>
        </div>
      </button>
    );
  }

  const targets = viewTargets(view.targets);
  const isBlockedDiagnostic = signal.execution_gate?.feed_kind === "blocked";
  const isLowScore = signal.score < 70;
  const reason = executionBlockedReason(signal) ?? view.reason;
  const statusLabel = isBlockedDiagnostic && isLowScore ? "Blocked idea" : statusBadgeLabel(signal);
  const statusTone = isBlockedDiagnostic ? "red" : statusBadgeTone(signal);
  const badges = dedupeBadges([
    ...(isBlockedDiagnostic ? [{ code: "not_for_execution", label: "Not for execution", tone: "red" } as SignalBadgeView] : []),
    ...(isLowScore ? [{ code: "low_score", label: "low score", tone: "yellow" } as SignalBadgeView] : []),
    ...view.badges,
    ...executionGateBadges(signal)
  ]);

  return (
    <button className={`signal-card ${selected ? "selected" : ""}`} onClick={() => onSelect(signal)} type="button">
      <div className="signal-card-head">
        <div>
          <div className="pair-row">
            <strong>{signal.symbol}</strong>
            <Badge>{signal.exchange}</Badge>
            <Badge tone={statusTone}>{statusLabel}</Badge>
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
          <strong>Idea score {signal.score}</strong>
          <span className="muted">{view.risk_meta}</span>
          <span className="signal-ttl">
            <Clock3 size={13} />
            {signalTtlLabel(signal)}
          </span>
        </div>
      </div>

      <div className="signal-badge-row">
        {badges.map((badge) => (
          <Badge key={`${badge.code}:${badge.label}`} tone={badge.tone}>{badge.label}</Badge>
        ))}
      </div>

      {isBlockedDiagnostic ? null : (
        <div className="setup-grid">
          <span>Entry<strong>{view.entry_label} | {view.entry_value}</strong></span>
          <span>SL<strong>{formatPrice(view.stop_loss)}</strong></span>
          <span>TP1<strong>{formatTargetPrice(targets[0])}</strong></span>
          <span>TP2<strong>{formatTargetPrice(targets[1])}</strong></span>
          <span>TP3<strong>{formatTargetPrice(targets[2])}</strong></span>
          <span>Selected RR<strong>{formatRMultiple(view.selected_rr)}</strong></span>
          <span>
            {price ? "Price" : "TF"}
            <strong>{price ? `${formatPrice(price.price)} | ${new Date(price.updatedAt).toLocaleTimeString()}` : signal.timeframe}</strong>
          </span>
        </div>
      )}

      <div className="card-reason">
        <Activity size={15} />
        <span>{reason}</span>
      </div>
    </button>
  );
});

SignalCard.displayName = "SignalCard";

function viewTargets(targets: SignalTargetView[]) {
  const byLabel = new Map(targets.map((target) => [target.label.toUpperCase(), target]));
  return ["TP1", "TP2", "TP3"].map((label, index) => byLabel.get(label) ?? targets[index] ?? null);
}

function formatTargetPrice(target: SignalTargetView | null): string {
  if (!target) return "-";
  const rr = target.r_multiple == null ? "" : ` ${target.r_multiple.toFixed(2)}R`;
  return `${formatPrice(target.price)}${rr}`;
}

function formatRMultiple(value: number | null): string {
  return value == null ? "-" : `${value.toFixed(2)}R`;
}

function executionBlockedReason(signal: RadarSignal): string | null {
  const gate = signal.execution_gate;
  if (!gate || gate.can_enter_now === true) return null;
  const blocker = gate.reasons.find((reason) => reason.severity === "blocker") ?? gate.reasons[0];
  return blocker ? `Execution blocked: ${blocker.message}` : "Execution blocked";
}

function executionGateBadges(signal: RadarSignal): SignalBadgeView[] {
  const badges: SignalBadgeView[] = [];
  const reasons = signal.execution_gate?.reasons ?? [];
  const hasReason = (code: string) => reasons.some((reason) => reason.code === code);
  if (signal.candle_state === "open" || hasReason("forming_candle")) {
    badges.push({ code: "forming_candle_preview", label: "Forming candle preview", tone: "yellow" });
  }
  if (hasReason("trigger_not_confirmed")) {
    badges.push({ code: "trigger_not_confirmed", label: "Trigger not confirmed", tone: "red" });
  }
  const dedup = recordValue(signal.execution_gate?.metadata.dedup);
  if (dedup?.reason_code === "dedup_suppressed_by_better_signal") {
    badges.push({ code: "dedup_suppressed", label: "Dedup suppressed", tone: "neutral" });
  }
  return badges;
}

function dedupeBadges(badges: SignalBadgeView[]): SignalBadgeView[] {
  const seen = new Set<string>();
  return badges.filter((badge) => {
    const key = badge.code || badge.label;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
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
