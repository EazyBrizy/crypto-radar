"use client";

import { Eye } from "lucide-react";
import { useMemo, useState } from "react";
import type { CandlestickData, SeriesMarker, Time, UTCTimestamp } from "lightweight-charts";

import { Badge } from "@/components/Badge";
import { ChartPanel } from "@/components/charts/ChartPanel";
import type { ChartRiskLine } from "@/components/charts/chart-overlays";
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
  const [selectedTradeKey, setSelectedTradeKey] = useState<string | null>(null);
  const effectiveSelectedKey = selectedTradeKey ?? (trades[0] ? tradeRowKey(trades[0], 0) : null);
  const selectedTrade = useMemo(
    () => trades.find((trade, index) => tradeRowKey(trade, index) === effectiveSelectedKey) ?? trades[0] ?? null,
    [effectiveSelectedKey, trades]
  );

  if (!trades.length) {
    return <div className="empty-state compact-empty">{emptyLabel}</div>;
  }

  return (
    <div className="strategy-test-trade-workspace">
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
            {trades.map((trade, index) => {
              const rowKey = tradeRowKey(trade, index);
              const selected = rowKey === effectiveSelectedKey;
              const tradeId = tradeIdLabel(trade, index);
              return (
                <tr aria-selected={selected} className={selected ? "selected" : undefined} key={rowKey}>
                  <td>
                    <button
                      aria-label={`View trade ${tradeId}`}
                      className="strategy-test-trade-select"
                      onClick={() => setSelectedTradeKey(rowKey)}
                      type="button"
                    >
                      <Eye size={14} />
                      <span>{shortId(tradeId)}</span>
                    </button>
                  </td>
                  <td>{asString(trade.strategy_code) || "-"}</td>
                  <td>{marketLabel(trade)}</td>
                  <td>{asString(trade.direction) || "-"}</td>
                  <td>{formatNumber(asNumber(trade.signal_score), 1)}</td>
                  <td>{formatNumber(asNumber(trade.realized_r), 2)}</td>
                  <td>{formatExcursion(trade)}</td>
                  <td>{outcomeLabel(trade)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {selectedTrade ? <SelectedTradePanel trade={selectedTrade} /> : null}
    </div>
  );
}

function SelectedTradePanel({ trade }: { trade: StrategyTestTradeRow }) {
  const chart = useMemo(() => tradeChartData(trade), [trade]);
  const outcome = outcomeLabel(trade);
  return (
    <section aria-label="Selected strategy test trade" className="strategy-test-trade-detail">
      <div className="strategy-test-trade-detail-head">
        <div>
          <strong>{tradeIdLabel(trade, 0)}</strong>
          <span>{marketShortLabel(trade)}</span>
        </div>
        <Badge tone={outcomeTone(trade)}>{outcome}</Badge>
      </div>
      <ChartPanel
        candles={chart.candles}
        height={280}
        markers={chart.markers}
        priceLines={chart.priceLines}
      />
      <div className="strategy-test-summary-grid">
        {tradeMetric("Entry time", trade.entry_time)}
        {tradeMetric("Exit time", trade.exit_time)}
        {tradeMetric("Entry price", trade.entry_price)}
        {tradeMetric("Exit price", trade.exit_price)}
        {tradeMetric("Stop", trade.stop_loss)}
        {tradeMetric("Realized R", trade.realized_r)}
        {tradeMetric("PnL", trade.pnl)}
        {tradeMetric("PnL %", trade.pnl_pct)}
        {tradeMetric("Fees", trade.fees)}
        {tradeMetric("Slippage", trade.slippage)}
        {tradeMetric("MFE / MAE", formatExcursion(trade))}
        {tradeMetric("Bars", barsLabel(trade))}
        {tradeMetric("Market regime", trade.market_regime)}
        {tradeMetric("Score bucket", trade.score_bucket)}
        {tradeMetric("Signal score", trade.signal_score)}
        {tradeMetric("Direction", trade.direction)}
      </div>
      <div className="strategy-test-trade-context-grid">
        <article className="strategy-test-trade-context">
          <strong>Market conditions</strong>
          <pre>{jsonBlock(trade.features_snapshot)}</pre>
        </article>
        <article className="strategy-test-trade-context">
          <strong>Execution details</strong>
          <pre>{jsonBlock({
            close_reason: trade.close_reason,
            risk_rejected: trade.risk_rejected,
            execution_rejected: trade.execution_rejected,
            warnings: trade.warnings,
            trade_plan: trade.trade_plan,
            targets: trade.targets
          })}</pre>
        </article>
      </div>
    </section>
  );
}

function tradeMetric(label: string, value: unknown) {
  return (
    <div className="strategy-test-summary-item" key={label}>
      <span>{label}</span>
      <strong>{formatTradeValue(value)}</strong>
    </div>
  );
}

function tradeChartData(trade: StrategyTestTradeRow): {
  candles: CandlestickData<Time>[];
  markers: SeriesMarker<Time>[];
  priceLines: ChartRiskLine[];
} {
  const entry = asNumber(trade.entry_price);
  if (entry == null) {
    return { candles: [], markers: [], priceLines: [] };
  }
  const exit = asNumber(trade.exit_price) ?? entry;
  const stop = asNumber(trade.stop_loss);
  const targets = targetPrices(trade.targets);
  const risk = Math.max(Math.abs(entry - (stop ?? exit)), Math.abs(exit - entry), Math.abs(entry) * 0.002, 1e-8);
  const isShort = asString(trade.direction).toLowerCase() === "short";
  const mfe = asNumber(trade.mfe_r) ?? 0;
  const mae = asNumber(trade.mae_r) ?? 0;
  const favorable = isShort ? entry - risk * Math.max(0, mfe) : entry + risk * Math.max(0, mfe);
  const adverse = isShort ? entry - risk * Math.min(0, mae) : entry + risk * Math.min(0, mae);
  const prices = [entry, exit, stop, favorable, adverse, ...targets].filter((price): price is number => price != null);
  const high = Math.max(...prices);
  const low = Math.min(...prices);
  const entryTime = dateToChartTime(asString(trade.entry_time)) ?? (1_783_036_800 as UTCTimestamp);
  const rawExitTime = dateToChartTime(asString(trade.exit_time));
  const exitTime = rawExitTime && rawExitTime > entryTime ? rawExitTime : ((entryTime + 3600) as UTCTimestamp);
  const midTime = (entryTime + Math.max(60, Math.floor((exitTime - entryTime) / 2))) as UTCTimestamp;
  const midClose = isShort ? Math.min(entry, favorable) : Math.max(entry, favorable);
  const candles: CandlestickData<Time>[] = [
    {
      time: entryTime,
      open: entry,
      high: Math.max(entry, midClose, high),
      low: Math.min(entry, adverse, low),
      close: midClose
    },
    {
      time: midTime,
      open: midClose,
      high,
      low,
      close: exit
    },
    {
      time: exitTime,
      open: exit,
      high: Math.max(exit, high),
      low: Math.min(exit, low),
      close: exit
    }
  ];
  const priceLines: ChartRiskLine[] = [
    { id: "entry", price: entry, role: "entry", title: "Entry" },
    { id: "exit", price: exit, role: "entry", title: "Exit" },
    ...(stop == null ? [] : [{ id: "stop", price: stop, role: "stop-loss" as const, title: "Stop" }]),
    ...targets.map((price, index) => ({
      id: `target-${index + 1}`,
      price,
      role: "take-profit" as const,
      title: `TP${index + 1}`
    }))
  ];
  const markers: SeriesMarker<Time>[] = [
    {
      time: entryTime,
      position: isShort ? "aboveBar" : "belowBar",
      color: "#38bdf8",
      shape: isShort ? "arrowDown" : "arrowUp",
      text: "Entry",
      size: 1.1
    },
    {
      time: exitTime,
      position: isShort ? "belowBar" : "aboveBar",
      color: (asNumber(trade.pnl) ?? asNumber(trade.realized_r) ?? 0) >= 0 ? "#22c55e" : "#ef4444",
      shape: "circle",
      text: "Exit",
      size: 1.05
    }
  ];
  return { candles, markers, priceLines };
}

function marketLabel(trade: StrategyTestTradeRow): string {
  const exchange = asString(trade.exchange);
  const symbol = asString(trade.symbol);
  const timeframe = asString(trade.timeframe);
  const pair = [exchange, symbol].filter(Boolean).join(":");
  return [pair, timeframe].filter(Boolean).join(" / ") || "-";
}

function marketShortLabel(trade: StrategyTestTradeRow): string {
  return [asString(trade.symbol), asString(trade.timeframe)].filter(Boolean).join(" / ") || marketLabel(trade);
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

function formatTradeValue(value: unknown): string {
  if (value == null || value === "") return "-";
  if (typeof value === "number") return Number.isFinite(value) ? formatCompactNumber(value) : "-";
  if (typeof value === "string") return value || "-";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.length ? String(value.length) : "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatCompactNumber(value: number): string {
  if (Math.abs(value) >= 1000) return value.toFixed(2).replace(/\.00$/u, "");
  const rounded = Math.round(value * 10000) / 10000;
  return Number.isInteger(rounded) ? String(rounded) : String(rounded);
}

function shortId(value: string): string {
  return value ? value.slice(0, 8) : "-";
}

function tradeRowKey(trade: StrategyTestTradeRow, index: number): string {
  return `${tradeIdLabel(trade, index)}:${index}`;
}

function tradeIdLabel(trade: StrategyTestTradeRow, index: number): string {
  return asString(trade.trade_id) || `trade-${index + 1}`;
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

function targetPrices(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((target) => {
      if (!target || typeof target !== "object" || Array.isArray(target)) return null;
      const row = target as Record<string, unknown>;
      return asNumber(row.price) ?? asNumber(row.target_price) ?? asNumber(row.value);
    })
    .filter((price): price is number => price != null);
}

function dateToChartTime(value: string): UTCTimestamp | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return null;
  return Math.floor(timestamp / 1000) as UTCTimestamp;
}

function barsLabel(trade: StrategyTestTradeRow): string {
  const toEntry = asNumber(trade.bars_to_entry);
  const inTrade = asNumber(trade.bars_in_trade);
  if (toEntry == null && inTrade == null) return "-";
  return `${toEntry ?? 0} to entry / ${inTrade ?? 0} in trade`;
}

function outcomeTone(trade: StrategyTestTradeRow): "green" | "red" | "yellow" | "neutral" {
  const outcome = asString(trade.outcome).toLowerCase();
  const pnl = asNumber(trade.pnl) ?? asNumber(trade.realized_r);
  if (outcome.includes("win") || (pnl != null && pnl > 0)) return "green";
  if (outcome.includes("loss") || (pnl != null && pnl < 0)) return "red";
  if (outcome.includes("open")) return "yellow";
  return "neutral";
}

function jsonBlock(value: unknown): string {
  if (!value || (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0)) return "-";
  return JSON.stringify(value, null, 2);
}
