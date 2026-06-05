import type { RadarSignal, TradeJournalEntry, VirtualTradeTargetState } from "./types";
import { isFormingCandleSignal, isMarketOpportunity, isOpenCandleActionableAllowed } from "./domain/signal-status";
import { isActiveTradeStatus, isTerminalTradeStatus } from "./domain/trade-status";

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

export function formingCandleReason(signal: RadarSignal): string | null {
  if (!isFormingCandleSignal(signal) || isOpenCandleActionableAllowed(signal)) return null;
  const check = signal.confirmation?.checks.find((item) => item.name === "candle_state_gate");
  return check?.reason
    ?? signal.status_reason
    ?? signal.risks.find((risk) => risk.includes("forming_candle"))
    ?? "forming candle preview: open candle is watchlist-only until it closes.";
}

export function tradeTargetStates(trade: TradeJournalEntry): VirtualTradeTargetState[] {
  if (trade.target_states?.length) return trade.target_states;
  const finalTarget = trade.take_profit.length ? trade.take_profit[trade.take_profit.length - 1] : null;
  if (finalTarget == null) return [];
  const terminal = isTerminalTradeStatus(trade.status);
  const takeProfitClosed = trade.status === "closed" && trade.close_reason === "take_profit";
  return [
    {
      label: "Final",
      price: finalTarget,
      close_percent: 100,
      action: "full_close",
      hit: takeProfitClosed,
      hit_at: takeProfitClosed ? trade.closed_at : null,
      closed_quantity: terminal ? trade.quantity : 0,
      closed_size_usd: terminal ? trade.size_usd : 0,
      realized_pnl: terminal ? trade.pnl ?? 0 : 0,
      exit_fee: 0
    }
  ];
}

export function tradeRemainingQuantity(trade: TradeJournalEntry): number {
  if (trade.remaining_quantity != null) return trade.remaining_quantity;
  return isTerminalTradeStatus(trade.status) ? 0 : trade.quantity;
}

export function tradeCurrentStop(trade: TradeJournalEntry): number {
  return trade.current_stop_loss ?? trade.stop_loss;
}

export function tradeRealizedPnl(trade: TradeJournalEntry): number {
  if (trade.realized_pnl != null) return trade.realized_pnl;
  return isTerminalTradeStatus(trade.status) ? trade.pnl ?? 0 : 0;
}

export function tradeUnrealizedPnl(trade: TradeJournalEntry): number {
  if (trade.unrealized_pnl != null) return trade.unrealized_pnl;
  return isActiveTradeStatus(trade.status) ? trade.pnl ?? 0 : 0;
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
  return isMarketOpportunity(signal.status) && !isSignalExpired(signal, nowMs);
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
