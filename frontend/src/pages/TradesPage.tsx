import { BarChart3, History, ListFilter } from "lucide-react";

import { Metric } from "../components/Metric";
import { TradeRow } from "../components/TradeRow";
import type { TradeJournalEntry } from "../types";
import { formatPercent } from "../utils";

interface TradesPageProps {
  trades: TradeJournalEntry[];
  activeTab: "active" | "journal" | "analytics";
  onTabChange: (tab: "active" | "journal" | "analytics") => void;
}

export function TradesPage({ trades, activeTab, onTabChange }: TradesPageProps) {
  const activeTrades = trades.filter((trade) => trade.status === "open");
  const closedTrades = trades.filter((trade) => trade.status !== "open");
  const visibleTrades = activeTab === "active" ? activeTrades : closedTrades;
  const winners = closedTrades.filter((trade) => trade.result === "win").length;
  const winRate = closedTrades.length ? (winners / closedTrades.length) * 100 : 0;
  const netPnl = trades.reduce((sum, trade) => sum + (trade.pnl_percent ?? 0), 0);

  return (
    <section className="wide-panel">
      <div className="page-head">
        <div>
          <span className="muted">Trades</span>
          <h1>Сделки и журнал</h1>
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

      {activeTab === "analytics" ? (
        <div className="analytics-grid">
          <Metric label="Total Trades" value={String(trades.length)} hint="all modes" />
          <Metric label="Win Rate" value={formatPercent(winRate)} hint="closed only" />
          <Metric label="Net PnL" value={formatPercent(netPnl)} hint="journal sum" />
          <Metric label="Virtual Trades" value={String(trades.filter((trade) => trade.mode === "virtual").length)} hint="paper" />
        </div>
      ) : (
        <div className="trade-list">
          {!visibleTrades.length ? (
            <div className="empty-state">
              <strong>{activeTab === "active" ? "Нет активных сделок" : "Журнал пока пуст"}</strong>
              <span>Paper Trade из Signal Details появится здесь автоматически.</span>
            </div>
          ) : null}
          {visibleTrades.map((trade) => <TradeRow key={trade.id} trade={trade} />)}
        </div>
      )}
    </section>
  );
}
