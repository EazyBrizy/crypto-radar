"use client";

import { Activity, AlertTriangle, Crosshair, DollarSign, Gauge, LogOut, ShieldAlert, ShieldCheck, Target } from "lucide-react";

import { PositionChartPanel } from "@/components/charts/PositionChartPanel";
import { useCandlesQuery } from "@/hooks/use-radar-queries";
import { useI18n } from "@/i18n";
import type { Timeframe, TradeInvalidationAlert, TradeJournalEntry } from "@/types";
import { formatPercent, formatPrice, tradePnlClass } from "@/utils";

const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h", "4h", "1d"];

interface ActiveTradeChartProps {
  closing?: boolean;
  invalidationAlert?: TradeInvalidationAlert | null;
  onCloseInvalidated?: () => void;
  onKeepStopLoss?: () => void;
  trade: TradeJournalEntry;
}

export function ActiveTradeChart({
  closing = false,
  invalidationAlert = null,
  onCloseInvalidated,
  onKeepStopLoss,
  trade
}: ActiveTradeChartProps) {
  const { tKey, tReason } = useI18n();
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
  const simulatedPath = trade.execution?.simulated_path ?? null;

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
          <span>{tKey("trades.entry")}</span>
          <strong>{formatPrice(trade.entry_price)}</strong>
        </div>
        <div>
          <ShieldAlert size={15} />
          <span>{tKey("trades.stop")}</span>
          <strong>{formatPrice(trade.stop_loss)}</strong>
        </div>
        <div>
          <Target size={15} />
          <span>{tKey("trades.takeProfit")} 1:3</span>
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
          <span>{tKey("trades.execution")}</span>
          <strong>{formatExecutionSummary(trade)}</strong>
        </div>
        <div>
          <Gauge size={15} />
          <span>{tKey("trades.model")}</span>
          <strong>{trade.execution?.simulation_tier.toUpperCase() ?? "MVP"}</strong>
        </div>
        {simulatedPath ? (
          <>
            <div>
              <Activity size={15} />
              <span>{tKey("trades.postImpact")}</span>
              <strong>{formatPrice(simulatedPath.post_trade_price)}</strong>
            </div>
            <div>
              <Gauge size={15} />
              <span>{tKey("trades.decay60s")}</span>
              <strong>{formatPrice(simulatedPath.simulated_candle.close)}</strong>
            </div>
          </>
        ) : null}
      </div>

      {invalidationAlert?.invalidated ? (
        <div className="trade-invalidation-alert">
          <div className="trade-invalidation-copy">
            <AlertTriangle size={18} />
            <div>
              <strong>{tKey("toast.strategyInvalidationTitle")}</strong>
              <span>{invalidationAlert.reason ? tReason(invalidationAlert.reason) : invalidationAlert.triggered_conditions.map((condition) => tReason(condition)).join("; ")}</span>
            </div>
          </div>
          <div className="trade-invalidation-meta">
            <span>{tKey("common.current")} {formatPrice(invalidationAlert.current_price)}</span>
            <span>{tKey("trades.stop")} {formatPrice(invalidationAlert.stop_loss)}</span>
            {invalidationAlert.invalidation_price != null ? (
              <span>{tKey("signalDetails.invalidation")} {formatPrice(invalidationAlert.invalidation_price)}</span>
            ) : null}
          </div>
          <div className="trade-invalidation-actions">
            <button className="danger-action compact-action" disabled={closing || !onCloseInvalidated} onClick={onCloseInvalidated} type="button">
              <LogOut size={15} /> {tKey("trades.closeMarket")}
            </button>
            <button className="secondary-action compact-action" disabled={closing || !onKeepStopLoss} onClick={onKeepStopLoss} type="button">
              <ShieldCheck size={15} /> {tKey("trades.keepStopLoss")}
            </button>
          </div>
        </div>
      ) : null}

      {candlesQuery.data?.candles.length ? (
        <PositionChartPanel candles={candlesQuery.data.candles} height={340} trade={trade} />
      ) : (
        <div className="chart-panel chart-panel-loading">
          {candlesQuery.isLoading ? tKey("trades.loadingChart") : tKey("trades.noCandleData")}
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
    return `Low realism / max $${trade.execution.quality_gate.suggested_max_size_usd.toFixed(0)}`;
  }
  const mode = trade.simulation_mode === "impact_aware" ? "Impact" : "Passive";
  const risk = trade.execution.quality_gate.status;
  if (trade.execution_status === "partially_filled") {
    return `Partial ${Math.round(trade.execution.fill_ratio * 100)}% / ${risk}`;
  }
  return `${mode} / ${risk}`;
}
