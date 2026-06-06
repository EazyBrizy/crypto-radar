"use client";

import type { StrategyTestSignal } from "./types";

type StrategyTestSignalRow = Partial<StrategyTestSignal> & Record<string, unknown>;

interface StrategyTestSignalListProps {
  emptyLabel?: string;
  signals: StrategyTestSignalRow[];
}

export function StrategyTestSignalList({
  emptyLabel = "No signal rows",
  signals
}: StrategyTestSignalListProps) {
  if (!signals.length) {
    return <div className="empty-state compact-empty">{emptyLabel}</div>;
  }

  return (
    <div className="strategy-test-table-wrap">
      <table className="strategy-test-simple-table">
        <thead>
          <tr>
            <th>Signal</th>
            <th>Strategy</th>
            <th>Market</th>
            <th>Direction</th>
            <th>Score</th>
            <th>Gate</th>
            <th>Entry</th>
            <th>Outcome</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((signal, index) => (
            <tr key={`${asString(signal.signal_id) || "signal"}:${index}`}>
              <td>{shortId(asString(signal.signal_id))}</td>
              <td>{asString(signal.strategy_code) || "-"}</td>
              <td>{marketLabel(signal)}</td>
              <td>{asString(signal.direction) || "-"}</td>
              <td>{formatNumber(asNumber(signal.signal_score), 1)}</td>
              <td>{gateLabel(signal)}</td>
              <td>{entryLabel(signal)}</td>
              <td>{outcomeLabel(signal)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function marketLabel(signal: StrategyTestSignalRow): string {
  const exchange = asString(signal.exchange);
  const symbol = asString(signal.symbol);
  const timeframe = asString(signal.timeframe);
  const pair = [exchange, symbol].filter(Boolean).join(":");
  return [pair, timeframe].filter(Boolean).join(" / ") || "-";
}

function gateLabel(signal: StrategyTestSignalRow): string {
  const feedKind = asString(signal.feed_kind);
  const gateStatus = asString(signal.gate_status);
  if (feedKind && gateStatus) return `${feedKind} / ${gateStatus}`;
  return feedKind || gateStatus || "-";
}

function entryLabel(signal: StrategyTestSignalRow): string {
  if (signal.filled) return "filled";
  if (signal.entry_touched) return "touched";
  if (signal.no_entry) return "no entry";
  return "-";
}

function outcomeLabel(signal: StrategyTestSignalRow): string {
  const outcome = asString(signal.outcome);
  const reason = asString(signal.outcome_reason);
  if (outcome && reason) return `${outcome} / ${reason}`;
  return outcome || reason || "-";
}

function formatNumber(value: number | null, digits: number): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return value.toFixed(digits);
}

function shortId(value: string): string {
  return value ? value.slice(0, 8) : "-";
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}
