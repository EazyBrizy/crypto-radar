"use client";

import { useMemo, useState } from "react";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { BarChart3 } from "lucide-react";

import { Badge } from "@/components/Badge";
import { DataTable } from "@/components/data-table/DataTable";
import type { StrategyTestRunResponse, StrategyTestRunStatus } from "./types";

interface StrategyTestRunsTableProps {
  emptyLabel?: string;
  onOpenReport?: (run: StrategyTestRunResponse) => void;
  runs: StrategyTestRunResponse[];
  selectedRunId?: string | null;
}

export function StrategyTestRunsTable({
  emptyLabel = "No strategy test runs",
  onOpenReport,
  runs,
  selectedRunId
}: StrategyTestRunsTableProps) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);
  const columns = useMemo<ColumnDef<StrategyTestRunResponse>[]>(
    () => [
      {
        accessorKey: "run_id",
        header: "Run",
        cell: ({ row }) => (
          <div className="strategy-test-run-cell">
            <strong>{shortRunId(row.original.run_id)}</strong>
            <span>{matrixLabel(row.original)}</span>
          </div>
        )
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <Badge tone={statusTone(row.original.status)}>{row.original.status}</Badge>
      },
      {
        id: "scenario_count",
        header: "Scenarios",
        cell: ({ row }) => String(scenarioCount(row.original))
      },
      {
        id: "summary",
        header: "Summary",
        cell: ({ row }) => summaryLabel(row.original)
      },
      {
        accessorKey: "created_at",
        header: "Created",
        cell: ({ row }) => formatDate(row.original.created_at)
      },
      {
        id: "report",
        header: "Report",
        enableSorting: false,
        cell: ({ row }) => (
          <button
            aria-label={`Open report for run ${row.original.run_id}`}
            className="icon-button compact table-action-button"
            onClick={(event) => {
              event.stopPropagation();
              onOpenReport?.(row.original);
            }}
            title="Open report"
            type="button"
          >
            <BarChart3 size={16} />
          </button>
        )
      }
    ],
    [onOpenReport]
  );

  return (
    <DataTable
      className="strategy-test-runs-table"
      columns={columns}
      data={runs}
      emptyLabel={emptyLabel}
      estimateRowHeight={70}
      getRowId={(run) => run.run_id}
      globalFilter={globalFilter}
      onGlobalFilterChange={setGlobalFilter}
      onSortingChange={setSorting}
      selectedRowId={selectedRunId}
      sorting={sorting}
    />
  );
}

export function scenarioCount(run: StrategyTestRunResponse): number {
  const requested = run.requested_matrix.scenario_count;
  if (typeof requested === "number") return requested;
  const summary = run.summary.scenario_count;
  if (typeof summary === "number") return summary;
  return matrixLength(run.requested_matrix.strategies) *
    matrixLength(run.requested_matrix.pairs) *
    matrixLength(run.requested_matrix.timeframes);
}

function matrixLength(value: unknown[] | undefined): number {
  return value?.length ? value.length : 1;
}

function matrixLabel(run: StrategyTestRunResponse): string {
  const strategies = run.requested_matrix.strategies?.length ?? 0;
  const pairs = run.requested_matrix.pairs?.length ?? 0;
  const timeframes = run.requested_matrix.timeframes?.length ?? 0;
  return `${strategies} strategies / ${pairs} pairs / ${timeframes} timeframes`;
}

function summaryLabel(run: StrategyTestRunResponse): string {
  if (run.error) return run.error;
  const completed = numericSummary(run, "completed_scenarios");
  const failed = numericSummary(run, "failed_scenarios");
  const trades = numericSummary(run, "trades_count");
  if (completed != null || failed != null) return `${completed ?? 0} done / ${failed ?? 0} failed`;
  if (trades != null) return `${trades} trades`;
  return "-";
}

function numericSummary(run: StrategyTestRunResponse, key: keyof StrategyTestRunResponse["summary"]): number | null {
  const value = run.summary[key];
  return typeof value === "number" ? value : null;
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function shortRunId(runId: string): string {
  return runId.slice(0, 8);
}

function statusTone(status: StrategyTestRunStatus): "green" | "red" | "yellow" | "blue" | "purple" | "neutral" {
  if (status === "completed") return "green";
  if (status === "failed") return "red";
  if (status === "running") return "blue";
  return "yellow";
}
