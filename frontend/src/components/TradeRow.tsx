import { Clock3, History } from "lucide-react";

import { Badge } from "./Badge";
import type { TradeJournalEntry } from "../types";
import {
  formatPercent,
  formatPrice,
  tradeCurrentStop,
  tradePnlClass,
  tradeRealizedPnl,
  tradeRemainingQuantity,
  tradeTargetStates,
  tradeUnrealizedPnl
} from "../utils";

interface TradeRowProps {
  trade: TradeJournalEntry;
}

export function TradeRow({ trade }: TradeRowProps) {
  const targets = tradeTargetStates(trade);
  const remainingQuantity = tradeRemainingQuantity(trade);
  const currentStop = tradeCurrentStop(trade);
  const realizedPnl = tradeRealizedPnl(trade);
  const unrealizedPnl = tradeUnrealizedPnl(trade);

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
          <span className="muted">{trade.strategy.replaceAll("_", " ")} | {trade.timeframe}</span>
          <div className="trade-lifecycle-badges">
            {targets.slice(0, 3).map((target) => (
              <Badge tone={target.hit ? "green" : "neutral"} key={`${target.label}:${target.price}`}>
                {target.label} {target.hit ? "hit" : formatPrice(target.price)}
              </Badge>
            ))}
            {trade.stop_moved_to_breakeven ? <Badge tone="blue">BE moved</Badge> : null}
            {trade.trailing_active ? <Badge tone="purple">Trailing</Badge> : null}
          </div>
        </div>
      </div>

      <div className="trade-values">
        <span>Entry<strong>{formatPrice(trade.entry_price)}</strong></span>
        <span>Current<strong>{formatPrice(trade.current_price)}</strong></span>
        <span>Stop<strong>{formatPrice(currentStop)}</strong></span>
        <span>Remaining<strong>{formatQuantity(remainingQuantity)}</strong></span>
        <span>PnL<strong className={tradePnlClass(trade)}>{formatPercent(trade.pnl_percent)}</strong></span>
        <span>Realized<strong className={pnlValueClass(realizedPnl)}>{formatSignedUsd(realizedPnl)}</strong></span>
        <span>Unrealized<strong className={pnlValueClass(unrealizedPnl)}>{formatSignedUsd(unrealizedPnl)}</strong></span>
        <span>Size<strong>${trade.size_usd.toFixed(0)}</strong></span>
      </div>

      <div className="trade-status">{trade.status}</div>
    </div>
  );
}

function formatQuantity(value: number): string {
  if (value === 0) return "0";
  if (Math.abs(value) >= 1) return value.toFixed(4).replace(/\.?0+$/u, "");
  return value.toPrecision(4);
}

function formatSignedUsd(value: number): string {
  return `${value >= 0 ? "+" : "-"}$${Math.abs(value).toFixed(2)}`;
}

function pnlValueClass(value: number): string {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "muted";
}
