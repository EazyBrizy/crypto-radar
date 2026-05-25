import type { RadarSignal, TradeJournalEntry } from "./types";

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

export function signalAge(signal: RadarSignal): string {
  const diffMinutes = Math.max(0, Math.floor((Date.now() - new Date(signal.created_at).getTime()) / 60_000));
  if (diffMinutes < 1) return "только что";
  if (diffMinutes < 60) return `${diffMinutes} мин назад`;
  return `${Math.floor(diffMinutes / 60)} ч назад`;
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
