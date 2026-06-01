import type { RadarSignal, TradeJournalEntry, VirtualTradeTargetState } from "./types";

export function formatPrice(value: number | null | undefined): string {
  if (value == null) return "-";
  if (Math.abs(value) >= 1000) return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return value.toLocaleString("en-US", { maximumFractionDigits: 6 });
}

export function formatPercent(value: number | null | undefined): string {
  if (value == null) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function entryZone(signal: RadarSignal): string {
  return `${formatPrice(signal.entry_min)}-${formatPrice(signal.entry_max)}`;
}

export interface SignalPlanTargetSummary {
  label: string;
  price: number | null;
  rMultiple: number | null;
  closePercent: number | string | null;
  action: string | null;
  source: string | null;
}

export interface SignalTradePlanSummary {
  hasTradePlan: boolean;
  entryType: string;
  entryZone: string;
  entryPrice: number | null;
  stopLoss: number | null;
  targets: SignalPlanTargetSummary[];
  selectedRr: number | null;
  selectedRrTarget: string | null;
  minRr: number | null;
}

export function signalTradePlanSummary(signal: RadarSignal): SignalTradePlanSummary {
  const plan = signal.trade_plan ?? null;
  const entry = plan?.entry ?? null;
  const riskRules = plan?.risk_rules ?? null;
  const targets = plan?.targets?.length
    ? plan.targets.map((target) => ({
        label: target.label,
        price: target.price,
        rMultiple: target.r_multiple,
        closePercent: target.close_percent,
        action: target.action,
        source: target.source
      }))
    : legacySignalTargets(signal);

  return {
    hasTradePlan: Boolean(plan),
    entryType: plan ? formatPlanLabel(planEntryType(signal)) : "Legacy entry",
    entryZone: formatPlanEntryZone(signal),
    entryPrice: entry?.price ?? midpoint(signal.entry_min, signal.entry_max),
    stopLoss: plan?.stop_loss ?? signal.stop_loss,
    targets,
    selectedRr: riskRules?.selected_rr ?? signal.selected_rr ?? signal.risk_reward,
    selectedRrTarget: riskRules?.selected_rr_target ?? signal.selected_rr_target,
    minRr: riskRules?.min_rr_ratio ?? signal.min_rr_ratio
  };
}

export function isRiskRewardBlocked(signal: RadarSignal): boolean {
  const check = signal.confirmation?.checks.find((item) => item.name === "risk_reward_guard");
  const metadataBlocked = check?.metadata.risk_reward_blocked === true;
  const selectedRr = signal.trade_plan?.risk_rules.selected_rr ?? signal.selected_rr;
  const minRr = signal.trade_plan?.risk_rules.min_rr_ratio ?? signal.min_rr_ratio;
  if (selectedRr != null && minRr != null && minRr > 0 && selectedRr < minRr) return true;
  return metadataBlocked || check?.status === "failed";
}

export function riskRewardBlockReason(signal: RadarSignal): string | null {
  const check = signal.confirmation?.checks.find((item) => item.name === "risk_reward_guard");
  const metadataReason = check?.metadata.risk_reward_block_reason;
  if (typeof metadataReason === "string" && metadataReason) return metadataReason;
  if (check?.status === "failed" && check.reason) return check.reason;
  if (!isRiskRewardBlocked(signal)) return null;
  const selectedRr = signal.trade_plan?.risk_rules.selected_rr ?? signal.selected_rr;
  const minRr = signal.trade_plan?.risk_rules.min_rr_ratio ?? signal.min_rr_ratio;
  return selectedRr != null && minRr != null
    ? `Selected RR ${selectedRr.toFixed(2)}R is below minimum ${minRr.toFixed(2)}R.`
    : "Risk/reward guard blocked this signal.";
}

export function tradeTargetStates(trade: TradeJournalEntry): VirtualTradeTargetState[] {
  if (trade.target_states?.length) return trade.target_states;
  const finalTarget = trade.take_profit.length ? trade.take_profit[trade.take_profit.length - 1] : null;
  if (finalTarget == null) return [];
  return [
    {
      label: "Final",
      price: finalTarget,
      close_percent: 100,
      action: "full_close",
      hit: trade.status === "closed" && trade.close_reason === "take_profit",
      hit_at: trade.close_reason === "take_profit" ? trade.closed_at : null,
      closed_quantity: trade.status === "closed" ? trade.quantity : 0,
      closed_size_usd: trade.status === "closed" ? trade.size_usd : 0,
      realized_pnl: trade.status === "closed" ? trade.pnl ?? 0 : 0,
      exit_fee: 0
    }
  ];
}

export function tradeRemainingQuantity(trade: TradeJournalEntry): number {
  if (trade.remaining_quantity != null) return trade.remaining_quantity;
  return trade.status === "closed" ? 0 : trade.quantity;
}

export function tradeCurrentStop(trade: TradeJournalEntry): number {
  return trade.current_stop_loss ?? trade.stop_loss;
}

export function tradeRealizedPnl(trade: TradeJournalEntry): number {
  if (trade.realized_pnl != null) return trade.realized_pnl;
  return trade.status === "closed" ? trade.pnl ?? 0 : 0;
}

export function tradeUnrealizedPnl(trade: TradeJournalEntry): number {
  if (trade.unrealized_pnl != null) return trade.unrealized_pnl;
  return trade.status === "open" ? trade.pnl ?? 0 : 0;
}

export function signalAge(signal: RadarSignal): string {
  return ageFromTimestamp(signal.created_at);
}

export function signalUpdatedAge(signal: RadarSignal): string {
  return ageFromTimestamp(signal.updated_at || signal.created_at);
}

function ageFromTimestamp(value: string): string {
  const timestamp = Date.parse(value);
  const diffMinutes = Number.isFinite(timestamp)
    ? Math.max(0, Math.floor((Date.now() - timestamp) / 60_000))
    : 0;
  if (diffMinutes < 1) return "just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  return `${Math.floor(diffMinutes / 60)}h ago`;
}

export function isSignalExpired(signal: RadarSignal, nowMs = Date.now()): boolean {
  if (signal.status === "expired") return true;
  if (!signal.expires_at) return false;
  const expiresAtMs = Date.parse(signal.expires_at);
  return Number.isFinite(expiresAtMs) && expiresAtMs <= nowMs;
}

export function isOpenFeedSignal(signal: RadarSignal, nowMs = Date.now()): boolean {
  return (
    (
      signal.status === "new" ||
      signal.status === "active" ||
      signal.status === "watchlist" ||
      signal.status === "ready" ||
      signal.status === "actionable" ||
      signal.status === "wait_for_pullback" ||
      signal.status === "entry_touched"
    ) &&
    !isSignalExpired(signal, nowMs)
  );
}

export function signalTtlLabel(signal: RadarSignal, nowMs = Date.now()): string {
  if (!signal.expires_at) return "TTL n/a";
  const expiresAtMs = Date.parse(signal.expires_at);
  if (!Number.isFinite(expiresAtMs)) return "TTL n/a";
  const remainingMinutes = Math.ceil((expiresAtMs - nowMs) / 60_000);
  if (remainingMinutes <= 0) return "TTL expired";
  if (remainingMinutes < 60) return `TTL ${remainingMinutes}m`;
  const hours = Math.floor(remainingMinutes / 60);
  const minutes = remainingMinutes % 60;
  return minutes ? `TTL ${hours}h ${minutes}m` : `TTL ${hours}h`;
}

export function riskLabel(signal: RadarSignal): "Low" | "Medium" | "High" | "Speculative" {
  if (signal.urgency === "low" && signal.score >= 70) return "Low";
  if (signal.urgency === "high" && signal.score < 75) return "High";
  if (signal.score < 65) return "Speculative";
  return "Medium";
}

export function tradePnlClass(trade: TradeJournalEntry): string {
  if ((trade.pnl ?? 0) > 0) return "positive";
  if ((trade.pnl ?? 0) < 0) return "negative";
  return "muted";
}

function legacySignalTargets(signal: RadarSignal): SignalPlanTargetSummary[] {
  return [
    { label: "TP1", price: signal.take_profit_1, rMultiple: signal.first_target_rr, closePercent: null, action: null, source: "legacy_fields" },
    { label: "TP2", price: signal.take_profit_2, rMultiple: signal.final_target_rr, closePercent: null, action: null, source: "legacy_fields" }
  ].filter((target) => target.price != null);
}

function formatPlanEntryZone(signal: RadarSignal): string {
  const entry = signal.trade_plan?.entry;
  const min = entry?.min_price ?? signal.entry_min;
  const max = entry?.max_price ?? signal.entry_max;
  const price = entry?.price ?? midpoint(signal.entry_min, signal.entry_max);
  if (min != null || max != null) return `${formatPrice(min)}-${formatPrice(max)}`;
  return formatPrice(price);
}

function planEntryType(signal: RadarSignal): string {
  const entry = signal.trade_plan?.entry;
  const metadata = entry?.metadata ?? {};
  const entryType = metadata.entry_type ?? metadata.entry_model ?? entry?.source;
  return typeof entryType === "string" && entryType ? entryType : "trade_plan";
}

function formatPlanLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function midpoint(left: number | null | undefined, right: number | null | undefined): number | null {
  if (left != null && right != null) return (left + right) / 2;
  return left ?? right ?? null;
}
