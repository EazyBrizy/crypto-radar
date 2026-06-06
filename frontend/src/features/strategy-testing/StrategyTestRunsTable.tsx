"use client";

import { useMemo, useState, type ReactNode } from "react";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { BarChart3, Square } from "lucide-react";

import { Badge } from "@/components/Badge";
import { DataTable } from "@/components/data-table/DataTable";
import type { StrategyTestRunResponse, StrategyTestRunStatus } from "./types";

interface StrategyTestRunsTableProps {
  emptyLabel?: string;
  onCancelRun?: (runId: string) => void;
  onOpenReport?: (run: StrategyTestRunResponse) => void;
  runs: StrategyTestRunResponse[];
  selectedRunId?: string | null;
}

export function StrategyTestRunsTable({
  emptyLabel = "No strategy test runs",
  onCancelRun,
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
        id: "test_type",
        header: "Type",
        cell: ({ row }) => testType(row.original)
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
        header: "Actions",
        enableSorting: false,
        cell: ({ row }) => {
          const run = row.original;
          return (
            <div className="table-action-group">
              {isRunningForwardRun(run) && onCancelRun ? (
                <button
                  aria-label={`Cancel forward run ${run.run_id}`}
                  className="icon-button compact table-action-button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onCancelRun(run.run_id);
                  }}
                  title="Cancel forward run"
                  type="button"
                >
                  <Square size={16} />
                </button>
              ) : null}
              <button
                aria-label={`Open report for run ${run.run_id}`}
                className="icon-button compact table-action-button"
                onClick={(event) => {
                  event.stopPropagation();
                  onOpenReport?.(run);
                }}
                title="Open report"
                type="button"
              >
                <BarChart3 size={16} />
              </button>
            </div>
          );
        }
      }
    ],
    [onCancelRun, onOpenReport]
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

function testType(run: StrategyTestRunResponse): string {
  return run.requested_matrix.test_type ?? "historical_backtest";
}

function summaryLabel(run: StrategyTestRunResponse): ReactNode {
  if (run.error) return run.error;
  if (testType(run) === "forward_virtual") {
    const signals = numericSummary(run, "signals_seen") ?? 0;
    const open = numericSummary(run, "open_positions") ?? 0;
    const pnl = numericSummary(run, "realized_pnl");
    return (
      <div className="strategy-test-run-counters">
        <span>{signals} signals</span>
        <span>{open} open</span>
        <span>PnL {pnl ?? 0}</span>
      </div>
    );
  }
  const completed = numericSummary(run, "completed_scenarios");
  const failed = numericSummary(run, "failed_scenarios");
  const trades = numericSummary(run, "trades_count");
  if (completed != null || failed != null) return `${completed ?? 0} done / ${failed ?? 0} failed`;
  if (trades != null) return `${trades} trades`;
  return "-";
}

function isRunningForwardRun(run: StrategyTestRunResponse): boolean {
  return testType(run) === "forward_virtual" && ["queued", "running", "stopping"].includes(run.status);
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
