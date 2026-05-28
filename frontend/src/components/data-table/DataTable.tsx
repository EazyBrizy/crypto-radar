"use client";

/* eslint-disable react-hooks/incompatible-library */

import { useRef } from "react";
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type ColumnFiltersState,
  type OnChangeFn,
  type PaginationState,
  type Row,
  type SortingState,
  type VisibilityState
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { KeyboardEvent, ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface DataTableProps<TData> {
  columns: ColumnDef<TData>[];
  data: TData[];
  estimateRowHeight?: number;
  overscan?: number;
  className?: string;
  emptyLabel?: string;
  enablePagination?: boolean;
  globalFilter?: string;
  getRowId?: (row: TData, index: number) => string;
  onGlobalFilterChange?: (value: string) => void;
  onRowClick?: (row: TData) => void;
  pageSize?: number;
  selectedRowId?: string | null;
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  columnFilters?: ColumnFiltersState;
  onColumnFiltersChange?: OnChangeFn<ColumnFiltersState>;
  columnVisibility?: VisibilityState;
  onColumnVisibilityChange?: OnChangeFn<VisibilityState>;
  toolbar?: ReactNode;
}

export function DataTable<TData>({
  columns,
  data,
  estimateRowHeight = 52,
  overscan = 8,
  className,
  emptyLabel = "No rows",
  enablePagination = false,
  getRowId,
  globalFilter,
  onGlobalFilterChange,
  onRowClick,
  pageSize = 50,
  selectedRowId,
  sorting,
  onSortingChange,
  columnFilters,
  onColumnFiltersChange,
  columnVisibility,
  onColumnVisibilityChange,
  toolbar
}: DataTableProps<TData>) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pagination: PaginationState = { pageIndex: 0, pageSize };
  const table = useReactTable({
    data,
    columns,
    state: {
      columnFilters,
      columnVisibility,
      globalFilter,
      pagination,
      sorting
    },
    enableSorting: true,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: enablePagination ? getPaginationRowModel() : undefined,
    getSortedRowModel: getSortedRowModel(),
    onColumnFiltersChange,
    onColumnVisibilityChange,
    onGlobalFilterChange,
    onSortingChange
  });
  const rows = table.getRowModel().rows;
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimateRowHeight,
    overscan
  });

  return (
    <div className={cn("data-table", className)}>
      {(toolbar || onGlobalFilterChange) ? (
        <div className="data-table-toolbar">
          {onGlobalFilterChange ? (
            <Input
              className="data-table-search"
              placeholder="Filter rows"
              value={globalFilter ?? ""}
              onChange={(event) => onGlobalFilterChange(event.target.value)}
            />
          ) : null}
          {toolbar}
        </div>
      ) : null}

      <div className="data-table-header" role="rowgroup">
        {table.getHeaderGroups().map((headerGroup) => (
          <div className="data-table-row data-table-head-row" key={headerGroup.id} role="row">
            {headerGroup.headers.map((header) => (
              <div className="data-table-cell data-table-head-cell" key={header.id} role="columnheader">
                {header.isPlaceholder ? null : (
                  <button
                    className={header.column.getCanSort() ? "data-table-sort-button" : "data-table-static-head"}
                    onClick={header.column.getToggleSortingHandler()}
                    type="button"
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {header.column.getIsSorted() === "asc" ? " ↑" : null}
                    {header.column.getIsSorted() === "desc" ? " ↓" : null}
                  </button>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="data-table-scroll" ref={scrollRef} role="table">
        {rows.length ? (
          <div className="data-table-virtual" style={{ height: rowVirtualizer.getTotalSize() }}>
            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
              const row = rows[virtualRow.index];
              if (!row) return null;

              return (
                <div
                  aria-selected={selectedRowId === row.id}
                  className={cn(
                    "data-table-row data-table-body-row",
                    onRowClick && "data-table-body-row-clickable",
                    selectedRowId === row.id && "selected"
                  )}
                  data-index={virtualRow.index}
                  key={row.id}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                  onKeyDown={onRowClick ? (event) => handleRowKeyDown(event, row, onRowClick) : undefined}
                  ref={rowVirtualizer.measureElement}
                  role="row"
                  style={{ transform: `translateY(${virtualRow.start}px)` }}
                  tabIndex={onRowClick ? 0 : undefined}
                >
                  {row.getVisibleCells().map((cell) => (
                    <div className="data-table-cell" key={cell.id} role="cell">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="data-table-empty">{emptyLabel}</div>
        )}
      </div>

      {enablePagination ? (
        <div className="data-table-footer">
          <span>{rows.length} rows</span>
          <span>Page size {pageSize}</span>
        </div>
      ) : null}
    </div>
  );
}

function handleRowKeyDown<TData>(
  event: KeyboardEvent<HTMLDivElement>,
  row: Row<TData>,
  onRowClick: (row: TData) => void,
) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  onRowClick(row.original);
}
