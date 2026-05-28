"use client";

import { useMemo, useState } from "react";
import type { ColumnDef, SortingState } from "@tanstack/react-table";

import { DataTable } from "@/components/data-table/DataTable";

export interface ScannerTableRow {
  candles: number;
  exchange: string;
  series: string;
  symbol: string;
  timeframe: string;
}

interface ScannerTableProps {
  rows: ScannerTableRow[];
}

export function ScannerTable({ rows }: ScannerTableProps) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "candles", desc: true }]);
  const columns = useMemo<ColumnDef<ScannerTableRow>[]>(
    () => [
      { accessorKey: "exchange", header: "Exchange" },
      { accessorKey: "symbol", header: "Pair" },
      { accessorKey: "timeframe", header: "TF" },
      { accessorKey: "candles", header: "Candles" },
      { accessorKey: "series", header: "Series" }
    ],
    []
  );

  return (
    <DataTable
      columns={columns}
      data={rows}
      emptyLabel="No scanner series"
      estimateRowHeight={52}
      globalFilter={globalFilter}
      onGlobalFilterChange={setGlobalFilter}
      onSortingChange={setSorting}
      sorting={sorting}
    />
  );
}
