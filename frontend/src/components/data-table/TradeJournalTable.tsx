"use client";

import { useMemo, useState } from "react";
import type { ColumnDef, SortingState } from "@tanstack/react-table";

import { Badge } from "@/components/Badge";
import { DataTable } from "@/components/data-table/DataTable";
import type { TradeJournalEntry } from "@/types";
import { formatPercent, formatPrice, tradePnlClass } from "@/utils";

interface TradeJournalTableProps {
  emptyLabel?: string;
  onSelectTrade?: (trade: TradeJournalEntry) => void;
  selectedTradeId?: string | null;
  trades: TradeJournalEntry[];
}

export function TradeJournalTable({
  emptyLabel = "No trades",
  onSelectTrade,
  selectedTradeId,
  trades
}: TradeJournalTableProps) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "updated_at", desc: true }]);
  const columns = useMemo<ColumnDef<TradeJournalEntry>[]>(
    () => [
      {
        accessorKey: "symbol",
        header: "Pair",
        cell: ({ row }) => (
          <div className="table-pair-cell">
            <strong>{row.original.symbol}</strong>
            <span>{row.original.strategy.replaceAll("_", " ")} · {row.original.timeframe}</span>
          </div>
        )
      },
      {
        accessorKey: "mode",
        header: "Mode",
        cell: ({ row }) => <Badge tone={row.original.mode === "virtual" ? "purple" : "blue"}>{row.original.mode}</Badge>
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
        cell: ({ row }) => formatPrice(row.original.stop_loss)
      },
      {
        id: "take_profit",
        header: "TP",
        cell: ({ row }) => formatPrice(row.original.take_profit[row.original.take_profit.length - 1])
      },
      {
        accessorKey: "pnl_percent",
        header: "PnL",
        cell: ({ row }) => (
          <strong className={tradePnlClass(row.original)}>
            {formatUsd(row.original.pnl ?? 0)} / {formatPercent(row.original.pnl_percent)}
          </strong>
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
    ],
    []
  );

  return (
    <DataTable
      columns={columns}
      data={trades}
      emptyLabel={emptyLabel}
      estimateRowHeight={64}
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

function formatUsd(value: number): string {
  return `${value >= 0 ? "+" : "-"}$${Math.abs(value).toFixed(2)}`;
}

function formatExecutionMode(trade: TradeJournalEntry): string {
  if (trade.execution_status === "partially_filled") return "Partial";
  return trade.simulation_mode === "impact_aware" ? "Impact" : "Passive";
}

function formatExecutionDetail(trade: TradeJournalEntry): string {
  const execution = trade.execution;
  if (!execution) return `${trade.slippage_bps.toFixed(1)} bps`;
  if (execution.quality_gate.status === "blocked" && execution.quality_gate.suggested_max_size_usd != null) {
    return `max $${execution.quality_gate.suggested_max_size_usd.toFixed(0)}`;
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
