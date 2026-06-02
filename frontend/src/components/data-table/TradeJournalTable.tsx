"use client";

import { useMemo, useState } from "react";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { CircleStop } from "lucide-react";

import { Badge } from "@/components/Badge";
import { DataTable } from "@/components/data-table/DataTable";
import type { TradeJournalEntry } from "@/types";
import {
  formatPercent,
  formatPrice,
  tradeCurrentStop,
  tradePnlClass,
  tradeRealizedPnl,
  tradeRemainingQuantity,
  tradeTargetStates,
  tradeUnrealizedPnl
} from "@/utils";

interface TradeJournalTableProps {
  closingTradeId?: string | null;
  emptyLabel?: string;
  onCloseMarket?: (trade: TradeJournalEntry) => void;
  onSelectTrade?: (trade: TradeJournalEntry) => void;
  selectedTradeId?: string | null;
  trades: TradeJournalEntry[];
}

export function TradeJournalTable({
  closingTradeId = null,
  emptyLabel = "No trades",
  onCloseMarket,
  onSelectTrade,
  selectedTradeId,
  trades
}: TradeJournalTableProps) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "updated_at", desc: true }]);
  const columns = useMemo<ColumnDef<TradeJournalEntry>[]>(
    () => {
      const tableColumns: ColumnDef<TradeJournalEntry>[] = [
      {
        accessorKey: "symbol",
        header: "Pair",
        cell: ({ row }) => (
          <div className="table-pair-cell">
            <strong>{row.original.symbol}</strong>
            <span>{row.original.strategy.replaceAll("_", " ")} · {row.original.timeframe}</span>
            {row.original.source === "backtest" && row.original.run_id ? (
              <Badge tone="yellow">run {shortRunId(row.original.run_id)}</Badge>
            ) : null}
          </div>
        )
      },
      {
        accessorKey: "source",
        header: "Mode",
        cell: ({ row }) => (
          <div className="table-target-state-cell">
            <Badge tone={sourceTone(row.original)}>{row.original.source}</Badge>
            {row.original.source === "backtest" ? <Badge tone="purple">{row.original.mode}</Badge> : null}
          </div>
        )
      },
      {
        id: "execution",
        header: "Exec",
        cell: ({ row }) => (
          <div className="table-execution-cell">
            <Badge tone={executionTone(row.original)}>
              {formatExecutionMode(row.original)}
            </Badge>
            <span>{formatExecutionDetail(row.original)}</span>
          </div>
        )
      },
      {
        accessorKey: "side",
        header: "Side",
        cell: ({ row }) => <Badge tone={row.original.side === "long" ? "green" : "red"}>{row.original.side}</Badge>
      },
      {
        accessorKey: "entry_price",
        header: "Entry",
        cell: ({ row }) => formatPrice(row.original.entry_price)
      },
      {
        accessorKey: "current_price",
        header: "Current",
        cell: ({ row }) => formatPrice(row.original.current_price)
      },
      {
        accessorKey: "stop_loss",
        header: "Stop",
        cell: ({ row }) => formatPrice(tradeCurrentStop(row.original))
      },
      {
        id: "take_profit",
        header: "TP",
        cell: ({ row }) => <TargetStateCell trade={row.original} />
      },
      {
        id: "lifecycle",
        header: "Lifecycle",
        cell: ({ row }) => <LifecycleCell trade={row.original} />
      },
      {
        accessorKey: "pnl_percent",
        header: "PnL",
        cell: ({ row }) => (
          <div className="table-pnl-cell">
            <strong className={tradePnlClass(row.original)}>
              {formatUsd(row.original.pnl ?? 0)} / {formatPercent(row.original.pnl_percent)}
            </strong>
            <span>
              R {formatUsd(tradeRealizedPnl(row.original))} / U {formatUsd(tradeUnrealizedPnl(row.original))}
            </span>
          </div>
        )
      },
      {
        accessorKey: "risk_amount",
        header: "Risk",
        cell: ({ row }) => `$${(row.original.risk_amount ?? 0).toFixed(2)}`
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => row.original.close_reason ?? row.original.status
      },
      {
        accessorKey: "updated_at",
        header: "Updated",
        cell: ({ row }) => new Date(row.original.updated_at).toLocaleString()
      }
      ];

      if (onCloseMarket) {
        tableColumns.unshift({
          id: "actions",
          header: "Close",
          enableSorting: false,
          cell: ({ row }) => {
            const trade = row.original;
            const closing = closingTradeId === trade.id;
            const disabled = trade.status !== "open" || trade.source === "backtest" || closing;
            return (
              <div className="table-action-cell">
                <button
                  aria-label={`Close ${trade.symbol} at market`}
                  className="icon-button compact table-action-button danger"
                  disabled={disabled}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (!disabled) onCloseMarket(trade);
                  }}
                  onKeyDown={(event) => event.stopPropagation()}
                  title={closeMarketTitle(trade)}
                  type="button"
                >
                  <CircleStop size={16} />
                </button>
              </div>
            );
          }
        });
      }

      return tableColumns;
    },
    [closingTradeId, onCloseMarket]
  );

  return (
    <DataTable
      columns={columns}
      data={trades}
      emptyLabel={emptyLabel}
      estimateRowHeight={76}
      getRowId={(trade) => trade.id}
      globalFilter={globalFilter}
      onGlobalFilterChange={setGlobalFilter}
      onRowClick={onSelectTrade}
      onSortingChange={setSorting}
      selectedRowId={selectedTradeId}
      sorting={sorting}
    />
  );
}

function TargetStateCell({ trade }: { trade: TradeJournalEntry }) {
  const targets = tradeTargetStates(trade);
  if (!targets.length) return <span className="muted">-</span>;
  return (
    <div className="table-target-state-cell">
      {targets.slice(0, 3).map((target) => (
        <Badge tone={target.hit ? "green" : "neutral"} key={`${target.label}:${target.price}`}>
          {target.label} {target.hit ? "hit" : formatPrice(target.price)}
        </Badge>
      ))}
    </div>
  );
}

function LifecycleCell({ trade }: { trade: TradeJournalEntry }) {
  const remaining = tradeRemainingQuantity(trade);
  return (
    <div className="table-lifecycle-cell">
      <span>Remain {formatQuantity(remaining)}</span>
      <span>Stop {formatPrice(tradeCurrentStop(trade))}</span>
      <div>
        {trade.stop_moved_to_breakeven ? <Badge tone="blue">BE</Badge> : null}
        {trade.trailing_active ? <Badge tone="purple">Trail</Badge> : null}
      </div>
    </div>
  );
}

function formatUsd(value: number): string {
  return `${value >= 0 ? "+" : "-"}$${Math.abs(value).toFixed(2)}`;
}

function formatQuantity(value: number): string {
  if (value === 0) return "0";
  if (Math.abs(value) >= 1) return value.toFixed(4).replace(/\.?0+$/u, "");
  return value.toPrecision(4);
}

function formatExecutionMode(trade: TradeJournalEntry): string {
  if (trade.execution_status === "partially_filled") return "Partial";
  return trade.simulation_mode === "impact_aware" ? "Impact" : "Passive";
}

function sourceTone(trade: TradeJournalEntry): "green" | "red" | "yellow" | "blue" | "purple" | "neutral" {
  if (trade.source === "backtest") return "yellow";
  return trade.mode === "virtual" ? "purple" : "blue";
}

function shortRunId(runId: string): string {
  return runId.slice(0, 8);
}

function closeMarketTitle(trade: TradeJournalEntry): string {
  if (trade.source === "backtest") return "Backtest trades cannot be closed from the journal";
  return trade.mode === "real" ? "Real close stub" : "Close at market";
}

function formatExecutionDetail(trade: TradeJournalEntry): string {
  const execution = trade.execution;
  if (!execution) return `${trade.slippage_bps.toFixed(1)} bps`;
  if (execution.quality_gate.status === "blocked" && execution.quality_gate.suggested_max_size_usd != null) {
    return `low realism · max $${execution.quality_gate.suggested_max_size_usd.toFixed(0)}`;
  }
  const fill = trade.execution_status === "partially_filled" ? `${Math.round(execution.fill_ratio * 100)}% fill` : `${execution.entry_slippage_bps.toFixed(1)} bps`;
  return `${fill} · ${execution.quality_gate.status}`;
}

function executionTone(trade: TradeJournalEntry): "green" | "red" | "yellow" | "blue" | "purple" | "neutral" {
  if (trade.execution?.quality_gate.status === "blocked") return "red";
  if (trade.execution_status === "partially_filled") return "yellow";
  if (trade.execution?.liquidity.impact_risk === "high") return "red";
  if (trade.simulation_mode === "impact_aware") return "blue";
  return "neutral";
}
