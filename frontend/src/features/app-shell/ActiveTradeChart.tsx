"use client";

import { Activity, Crosshair, DollarSign, Gauge, ShieldAlert, Target } from "lucide-react";

import { PositionChartPanel } from "@/components/charts/PositionChartPanel";
import { useCandlesQuery } from "@/hooks/use-radar-queries";
import type { Timeframe, TradeJournalEntry } from "@/types";
import { formatPercent, formatPrice, tradePnlClass } from "@/utils";

const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h", "4h", "1d"];

interface ActiveTradeChartProps {
  trade: TradeJournalEntry;
}

export function ActiveTradeChart({ trade }: ActiveTradeChartProps) {
  const timeframe = normalizeTimeframe(trade.timeframe);
  const candlesQuery = useCandlesQuery(
    {
      exchange: trade.exchange,
      symbol: trade.symbol,
      timeframe,
      includeOpen: true,
      limit: 220
    },
    {
      enabled: Boolean(trade.exchange && trade.symbol),
      refetchInterval: trade.status === "open" ? 10_000 : false
    }
  );

  const takeProfit = trade.take_profit[trade.take_profit.length - 1] ?? null;

  return (
    <div className="active-trade-panel">
      <div className="section-title active-trade-title">
        <Activity size={17} />
        <div>
          <strong>{trade.symbol} {trade.side.toUpperCase()}</strong>
          <span>{trade.exchange} - {timeframe} - {trade.status} - {formatExecutionSummary(trade)}</span>
        </div>
      </div>

      <div className="active-trade-summary">
        <div>
          <Crosshair size={15} />
          <span>Entry</span>
          <strong>{formatPrice(trade.entry_price)}</strong>
        </div>
        <div>
          <ShieldAlert size={15} />
          <span>Stop</span>
          <strong>{formatPrice(trade.stop_loss)}</strong>
        </div>
        <div>
          <Target size={15} />
          <span>TP 1:3</span>
          <strong>{formatPrice(takeProfit)}</strong>
        </div>
        <div>
          <DollarSign size={15} />
          <span>PnL</span>
          <strong className={tradePnlClass(trade)}>
            {formatUsd(trade.pnl ?? 0)} - {formatPercent(trade.pnl_percent)}
          </strong>
        </div>
        <div>
          <Gauge size={15} />
          <span>Execution</span>
          <strong>{formatExecutionSummary(trade)}</strong>
        </div>
      </div>

      {candlesQuery.data?.candles.length ? (
        <PositionChartPanel candles={candlesQuery.data.candles} height={340} trade={trade} />
      ) : (
        <div className="chart-panel chart-panel-loading">
          {candlesQuery.isLoading ? "Loading chart..." : "No candle data for this trade"}
        </div>
      )}
    </div>
  );
}

function normalizeTimeframe(value: string): Timeframe {
  return TIMEFRAMES.includes(value as Timeframe) ? (value as Timeframe) : "15m";
}

function formatUsd(value: number): string {
  return `${value >= 0 ? "+" : "-"}$${Math.abs(value).toFixed(2)}`;
}

function formatExecutionSummary(trade: TradeJournalEntry): string {
  if (!trade.execution) return trade.simulation_mode === "impact_aware" ? "Impact" : "Passive";
  if (trade.execution.quality_gate.status === "blocked" && trade.execution.quality_gate.suggested_max_size_usd != null) {
    return `Blocked / max $${trade.execution.quality_gate.suggested_max_size_usd.toFixed(0)}`;
  }
  const mode = trade.simulation_mode === "impact_aware" ? "Impact" : "Passive";
  const risk = trade.execution.quality_gate.status;
  if (trade.execution_status === "partially_filled") {
    return `Partial ${Math.round(trade.execution.fill_ratio * 100)}% / ${risk}`;
  }
  return `${mode} / ${risk}`;
}
