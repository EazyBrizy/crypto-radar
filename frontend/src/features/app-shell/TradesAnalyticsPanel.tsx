import { Metric } from "@/components/Metric";
import type { TradeJournalEntry } from "@/types";
import { formatPercent } from "@/utils";

interface TradesAnalyticsPanelProps {
  trades: TradeJournalEntry[];
}

export function TradesAnalyticsPanel({ trades }: TradesAnalyticsPanelProps) {
  const closedTrades = trades.filter((trade) => trade.status !== "open");
  const winners = closedTrades.filter((trade) => trade.result === "win").length;
  const winRate = closedTrades.length ? (winners / closedTrades.length) * 100 : 0;
  const netPnl = trades.reduce((sum, trade) => sum + (trade.pnl_percent ?? 0), 0);

  return (
    <div className="analytics-grid">
      <Metric label="Total Trades" value={String(trades.length)} hint="loaded window" />
      <Metric label="Win Rate" value={formatPercent(winRate)} hint="closed only" />
      <Metric label="Net PnL" value={formatPercent(netPnl)} hint="journal sum" />
      <Metric label="Virtual Trades" value={String(trades.filter((trade) => trade.mode === "virtual").length)} hint="paper" />
    </div>
  );
}
