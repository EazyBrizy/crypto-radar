"use client";

import { useMemo, useState } from "react";
import type { ColumnDef, SortingState } from "@tanstack/react-table";

import { Badge } from "@/components/Badge";
import { DataTable } from "@/components/data-table/DataTable";
import type { RadarSignal } from "@/types";
import { entryZone, formatPrice, riskLabel } from "@/utils";

interface SignalHistoryTableProps {
  emptyLabel?: string;
  signals: RadarSignal[];
}

export function SignalHistoryTable({ emptyLabel = "No signals", signals }: SignalHistoryTableProps) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "updated_at", desc: true }]);
  const columns = useMemo<ColumnDef<RadarSignal>[]>(
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
        accessorKey: "direction",
        header: "Side",
        cell: ({ row }) => <Badge tone={row.original.direction === "long" ? "green" : "red"}>{row.original.direction}</Badge>
      },
      {
        accessorKey: "score",
        header: "Score"
      },
      {
        accessorKey: "status",
        header: "Status"
      },
      {
        accessorKey: "entry_min",
        header: "Entry",
        cell: ({ row }) => entryZone(row.original)
      },
      {
        accessorKey: "stop_loss",
        header: "SL",
        cell: ({ row }) => formatPrice(row.original.stop_loss)
      },
      {
        accessorKey: "take_profit_1",
        header: "TP1",
        cell: ({ row }) => formatPrice(row.original.take_profit_1)
      },
      {
        id: "risk",
        header: "Risk",
        cell: ({ row }) => riskLabel(row.original)
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
      data={signals}
      emptyLabel={emptyLabel}
      estimateRowHeight={64}
      globalFilter={globalFilter}
      onGlobalFilterChange={setGlobalFilter}
      onSortingChange={setSorting}
      sorting={sorting}
    />
  );
}
