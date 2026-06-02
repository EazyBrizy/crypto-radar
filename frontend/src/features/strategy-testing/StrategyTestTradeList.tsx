"use client";

import type { StrategyTestTrade } from "./types";

type StrategyTestTradeRow = Partial<StrategyTestTrade> & Record<string, unknown>;

interface StrategyTestTradeListProps {
  emptyLabel?: string;
  trades: StrategyTestTradeRow[];
}

export function StrategyTestTradeList({
  emptyLabel = "No trade rows",
  trades
}: StrategyTestTradeListProps) {
  if (!trades.length) {
    return <div className="empty-state compact-empty">{emptyLabel}</div>;
  }

  return (
    <div className="strategy-test-table-wrap">
      <table className="strategy-test-simple-table">
        <thead>
          <tr>
            <th>Trade</th>
            <th>Strategy</th>
            <th>Market</th>
            <th>Direction</th>
            <th>Score</th>
            <th>R</th>
            <th>MFE/MAE</th>
            <th>Outcome</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade, index) => (
            <tr key={`${asString(trade.trade_id) || "trade"}:${index}`}>
              <td>{shortId(asString(trade.trade_id))}</td>
              <td>{asString(trade.strategy_code) || "-"}</td>
              <td>{marketLabel(trade)}</td>
              <td>{asString(trade.direction) || "-"}</td>
              <td>{formatNumber(asNumber(trade.signal_score), 1)}</td>
              <td>{formatNumber(asNumber(trade.realized_r), 2)}</td>
              <td>{formatExcursion(trade)}</td>
              <td>{outcomeLabel(trade)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function marketLabel(trade: StrategyTestTradeRow): string {
  const exchange = asString(trade.exchange);
  const symbol = asString(trade.symbol);
  const timeframe = asString(trade.timeframe);
  const pair = [exchange, symbol].filter(Boolean).join(":");
  return [pair, timeframe].filter(Boolean).join(" / ") || "-";
}

function outcomeLabel(trade: StrategyTestTradeRow): string {
  const outcome = asString(trade.outcome);
  const closeReason = asString(trade.close_reason);
  if (outcome && closeReason) return `${outcome} / ${closeReason}`;
  return outcome || closeReason || "-";
}

function formatExcursion(trade: StrategyTestTradeRow): string {
  const mfe = formatNumber(asNumber(trade.mfe_r), 2);
  const mae = formatNumber(asNumber(trade.mae_r), 2);
  return `${mfe} / ${mae}`;
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
