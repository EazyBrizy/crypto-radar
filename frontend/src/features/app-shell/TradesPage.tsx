"use client";

import dynamic from "next/dynamic";
import { BarChart3, History, ListFilter } from "lucide-react";

import { Metric } from "@/components/Metric";
import { isActiveTradeStatus } from "@/domain/trade-status";
import { useI18n } from "@/i18n";
import type { TradeCloseReason, TradeInvalidationAlert, TradeJournalEntry, VirtualAccount } from "@/types";

const LazyTradeJournalTable = dynamic(
  () => import("@/components/data-table/TradeJournalTable").then((module) => module.TradeJournalTable),
  { loading: TradeJournalLoading }
);

const LazyTradesAnalyticsPanel = dynamic(
  () => import("./TradesAnalyticsPanel").then((module) => module.TradesAnalyticsPanel),
  { loading: TradesAnalyticsLoading }
);

const LazyActiveTradeChart = dynamic(
  () => import("./ActiveTradeChart").then((module) => module.ActiveTradeChart),
  { loading: ActiveTradeChartLoading }
);

interface TradesPageProps {
  activeTab: "active" | "journal" | "analytics";
  onTabChange: (tab: "active" | "journal" | "analytics") => void;
  actionError?: string | null;
  closingTradeId?: string | null;
  invalidationAlert?: TradeInvalidationAlert | null;
  onCloseMarket?: (trade: TradeJournalEntry, reason?: TradeCloseReason) => void;
  onDismissInvalidation?: (tradeId: string) => void;
  onSelectTrade?: (trade: TradeJournalEntry) => void;
  account?: VirtualAccount | null;
  selectedTrade?: TradeJournalEntry | null;
  selectedTradeId?: string | null;
  trades: TradeJournalEntry[];
}

export function TradesPage({
  activeTab,
  actionError = null,
  account,
  closingTradeId = null,
  invalidationAlert = null,
  onCloseMarket,
  onDismissInvalidation,
  onSelectTrade,
  onTabChange,
  selectedTrade = null,
  selectedTradeId = null,
  trades
}: TradesPageProps) {
  const { tKey } = useI18n();
  const activeTrade = selectedTrade ?? trades.find((trade) => isActiveTradeStatus(trade.status)) ?? null;
  const openPositions = account?.open_positions ?? (activeTrade ? 1 : 0);

  return (
    <section className="wide-panel">
      <div className="page-head">
        <div>
          <span className="muted">{tKey("trades.eyebrow")}</span>
          <h1>{tKey("trades.title")}</h1>
        </div>
      </div>

      <div className="tab-row">
        <button className={activeTab === "active" ? "tab active" : "tab"} onClick={() => onTabChange("active")} type="button">
          <ListFilter size={16} /> {tKey("trades.active")}
        </button>
        <button className={activeTab === "journal" ? "tab active" : "tab"} onClick={() => onTabChange("journal")} type="button">
          <History size={16} /> {tKey("trades.journal")}
        </button>
        <button className={activeTab === "analytics" ? "tab active" : "tab"} onClick={() => onTabChange("analytics")} type="button">
          <BarChart3 size={16} /> {tKey("trades.analytics")}
        </button>
      </div>

      <div className="virtual-account-strip">
        <Metric
          hint={tKey("trades.riskPerTrade", { amount: formatUsd(account?.risk_per_trade ?? 10) })}
          label={tKey("trades.balance")}
          value={formatUsd(account?.balance ?? 100)}
        />
        <Metric
          hint={tKey("trades.unrealized", { amount: formatSignedUsd(account?.unrealized_pnl ?? 0) })}
          label={tKey("trades.equity")}
          value={formatUsd(account?.equity ?? account?.balance ?? 100)}
        />
        <Metric
          hint={tKey("trades.winLossBreakeven", { wins: account?.wins ?? 0, losses: account?.losses ?? 0, breakeven: account?.breakeven ?? 0 })}
          label={tKey("trades.realizedPnl")}
          value={formatSignedUsd(account?.realized_pnl ?? 0)}
        />
        <Metric
          hint={tKey("trades.rr", { value: account?.risk_reward ?? 3 })}
          label={tKey("trades.openPositions")}
          value={`${openPositions}`}
        />
      </div>

      {actionError ? <p className="form-error">{actionError}</p> : null}

      {activeTab === "active" && activeTrade ? (
        <LazyActiveTradeChart
          closing={closingTradeId === activeTrade.id}
          invalidationAlert={invalidationAlert?.trade_id === activeTrade.id ? invalidationAlert : null}
          onCloseInvalidated={onCloseMarket ? () => onCloseMarket(activeTrade, "invalidation") : undefined}
          onKeepStopLoss={onDismissInvalidation ? () => onDismissInvalidation(activeTrade.id) : undefined}
          trade={activeTrade}
        />
      ) : null}

      {activeTab === "analytics" ? (
        <LazyTradesAnalyticsPanel trades={trades} />
      ) : (
        <LazyTradeJournalTable
          closingTradeId={activeTab === "active" ? closingTradeId : null}
          emptyLabel={activeTab === "active" ? tKey("trades.noActiveTrades") : tKey("trades.journalEmpty")}
          onCloseMarket={activeTab === "active" ? onCloseMarket : undefined}
          onSelectTrade={activeTab === "active" ? onSelectTrade : undefined}
          selectedTradeId={activeTab === "active" ? activeTrade?.id ?? selectedTradeId : null}
          trades={trades}
        />
      )}
    </section>
  );
}

function TradeJournalLoading() {
  const { tKey } = useI18n();
  return <div className="empty-state">{tKey("trades.loadingTable")}</div>;
}

function TradesAnalyticsLoading() {
  const { tKey } = useI18n();
  return <div className="empty-state">{tKey("trades.loadingAnalytics")}</div>;
}

function ActiveTradeChartLoading() {
  const { tKey } = useI18n();
  return <div className="chart-panel chart-panel-loading">{tKey("trades.loadingChart")}</div>;
}

function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`;
}

function formatSignedUsd(value: number): string {
  return `${value >= 0 ? "+" : "-"}$${Math.abs(value).toFixed(2)}`;
}
