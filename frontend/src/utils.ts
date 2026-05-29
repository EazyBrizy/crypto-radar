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
    (signal.status === "new" || signal.status === "active" || signal.status === "entry_touched") &&
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
