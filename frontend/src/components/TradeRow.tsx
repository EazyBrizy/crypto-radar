import { Clock3, History } from "lucide-react";

import { Badge } from "./Badge";
import type { TradeJournalEntry } from "../types";
import { formatPercent, formatPrice, tradePnlClass } from "../utils";

interface TradeRowProps {
  trade: TradeJournalEntry;
}

export function TradeRow({ trade }: TradeRowProps) {
  return (
    <div className="trade-row">
      <div className="trade-main">
        <div className="trade-icon">
          {trade.status === "open" ? <Clock3 size={18} /> : <History size={18} />}
        </div>
        <div>
          <div className="pair-row">
            <strong>{trade.symbol}</strong>
            <Badge tone={trade.mode === "virtual" ? "purple" : "blue"}>{trade.mode === "virtual" ? "Virtual" : "Real"}</Badge>
            <Badge tone={trade.side === "long" ? "green" : "red"}>{trade.side}</Badge>
          </div>
          <span className="muted">{trade.strategy.replaceAll("_", " ")} · {trade.timeframe}</span>
        </div>
      </div>

      <div className="trade-values">
        <span>Entry<strong>{formatPrice(trade.entry_price)}</strong></span>
        <span>Current<strong>{formatPrice(trade.current_price)}</strong></span>
        <span>PnL<strong className={tradePnlClass(trade)}>{formatPercent(trade.pnl_percent)}</strong></span>
        <span>Size<strong>${trade.size_usd.toFixed(0)}</strong></span>
      </div>

      <div className="trade-status">{trade.status}</div>
    </div>
  );
}
