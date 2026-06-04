import dynamic from "next/dynamic";
import { BarChart3, History, ListFilter } from "lucide-react";

import { Metric } from "@/components/Metric";
import { isActiveTradeStatus } from "@/domain/trade-status";
import type { TradeCloseReason, TradeInvalidationAlert, TradeJournalEntry, VirtualAccount } from "@/types";

const LazyTradeJournalTable = dynamic(
  () => import("@/components/data-table/TradeJournalTable").then((module) => module.TradeJournalTable),
  { loading: () => <div className="empty-state">Loading table...</div> }
);

const LazyTradesAnalyticsPanel = dynamic(
  () => import("./TradesAnalyticsPanel").then((module) => module.TradesAnalyticsPanel),
  { loading: () => <div className="empty-state">Loading analytics...</div> }
);

const LazyActiveTradeChart = dynamic(
  () => import("./ActiveTradeChart").then((module) => module.ActiveTradeChart),
  { loading: () => <div className="chart-panel chart-panel-loading">Loading chart...</div> }
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
  const activeTrade = selectedTrade ?? trades.find((trade) => isActiveTradeStatus(trade.status)) ?? null;
  const openPositions = account?.open_positions ?? (activeTrade ? 1 : 0);

  return (
    <section className="wide-panel">
      <div className="page-head">
        <div>
          <span className="muted">Trades</span>
          <h1>Trades and journal</h1>
        </div>
      </div>

      <div className="tab-row">
        <button className={activeTab === "active" ? "tab active" : "tab"} onClick={() => onTabChange("active")} type="button">
          <ListFilter size={16} /> Active
        </button>
        <button className={activeTab === "journal" ? "tab active" : "tab"} onClick={() => onTabChange("journal")} type="button">
          <History size={16} /> Journal
        </button>
        <button className={activeTab === "analytics" ? "tab active" : "tab"} onClick={() => onTabChange("analytics")} type="button">
          <BarChart3 size={16} /> Analytics
        </button>
      </div>

      <div className="virtual-account-strip">
        <Metric
          hint={`Risk ${formatUsd(account?.risk_per_trade ?? 10)} per trade`}
          label="Balance"
          value={formatUsd(account?.balance ?? 100)}
        />
        <Metric
          hint={`Unrealized ${formatSignedUsd(account?.unrealized_pnl ?? 0)}`}
          label="Equity"
          value={formatUsd(account?.equity ?? account?.balance ?? 100)}
        />
        <Metric
          hint={`${account?.wins ?? 0}W / ${account?.losses ?? 0}L / ${account?.breakeven ?? 0}BE`}
          label="Realized PnL"
          value={formatSignedUsd(account?.realized_pnl ?? 0)}
        />
        <Metric
          hint={`RR 1:${account?.risk_reward ?? 3}`}
          label="Open positions"
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
          emptyLabel={activeTab === "active" ? "No active trades" : "Journal is empty"}
          onCloseMarket={activeTab === "active" ? onCloseMarket : undefined}
          onSelectTrade={activeTab === "active" ? onSelectTrade : undefined}
          selectedTradeId={activeTab === "active" ? activeTrade?.id ?? selectedTradeId : null}
          trades={trades}
        />
      )}
    </section>
  );
}

function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`;
}

function formatSignedUsd(value: number): string {
  return `${value >= 0 ? "+" : "-"}$${Math.abs(value).toFixed(2)}`;
}
