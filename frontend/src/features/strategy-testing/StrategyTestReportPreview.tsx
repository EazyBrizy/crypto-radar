"use client";

import { X } from "lucide-react";

import { Badge } from "@/components/Badge";
import type { StrategyTestMetric, StrategyTestMetricValue, StrategyTestReport, StrategyTestRunResponse } from "./types";

interface StrategyTestReportPreviewProps {
  error?: Error | null;
  loading?: boolean;
  onClose?: () => void;
  report: StrategyTestReport | null;
  run: StrategyTestRunResponse | null;
}

export function StrategyTestReportPreview({
  error,
  loading = false,
  onClose,
  report,
  run
}: StrategyTestReportPreviewProps) {
  const metrics = report?.summary_metrics ?? summaryMetricsFromRun(run);
  const summary = { ...summaryFromRun(run), ...(report?.summary ?? {}) };
  const partial = Boolean(report?.is_partial || report?.data_completeness === "partial" || (run && ["queued", "running", "stopping"].includes(run.status)));
  return (
    <section className="strategy-test-report-panel" aria-live="polite">
      <div className="strategy-test-panel-head">
        <div>
          <h4>Report {run?.run_id ? run.run_id.slice(0, 8) : ""}</h4>
          <span>{run ? `${run.status} / ${scenarioLabel(run)}` : "No run selected"}</span>
        </div>
        {onClose ? (
          <button className="icon-button compact" onClick={onClose} title="Close report" type="button">
            <X size={16} />
          </button>
        ) : null}
      </div>

      {loading ? <div className="empty-state compact-empty">Loading report</div> : null}
      {error ? <p className="form-error">{error.message}</p> : null}

      {!loading && !error ? (
        <>
          <div className="strategy-test-report-strip">
            <Badge tone="purple">{scenarioCompleted(summary)} / {scenarioTotal(summary, run)} scenarios</Badge>
            <Badge tone={metricNumber(summary.failed_scenarios ?? summary.scenarios_failed) ? "red" : "green"}>
              {metricNumber(summary.failed_scenarios ?? summary.scenarios_failed)} failed
            </Badge>
            <Badge tone={metricNumber(summary.errors_count) ? "red" : "green"}>{metricNumber(summary.errors_count)} errors</Badge>
            <Badge tone="blue">{report?.trades_count ?? metricNumber(run?.summary.trades_count)} trades</Badge>
            <Badge tone={metricNumber(summary.warnings_count) || report?.warnings.length ? "yellow" : "green"}>
              {metricNumber(summary.warnings_count) || report?.warnings.length || 0} warnings
            </Badge>
            <Badge tone={report?.rejections.length ? "red" : "neutral"}>{report?.rejections.length ?? 0} rejections</Badge>
            {partial ? <Badge tone="yellow">Partial report</Badge> : null}
          </div>

          {partial ? <div className="empty-state compact-empty">Run is still running; aggregate metrics may change.</div> : null}
          {metrics.length ? (
            <div className="strategy-test-metric-grid">
              {metrics.slice(0, 6).map((metric, index) => (
                <div className="strategy-test-metric" key={`${metric.name ?? metric.code ?? "metric"}:${index}`}>
                  <span>{metric.label ?? metric.name ?? metric.code ?? "metric"}</span>
                  <strong>{formatMetricValue(metric)}</strong>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state compact-empty">No report metrics yet</div>
          )}
        </>
      ) : null}
    </section>
  );
}

function summaryMetricsFromRun(run: StrategyTestRunResponse | null): StrategyTestMetric[] {
  if (!run) return [];
  return Object.entries(run.summary)
    .filter((entry): entry is [string, StrategyTestMetricValue] => isMetricValue(entry[1]))
    .slice(0, 6)
    .map(([name, value]) => ({ name, value }));
}

function summaryFromRun(run: StrategyTestRunResponse | null): Record<string, unknown> {
  if (!run) return {};
  const partial = run.runtime_state.partial_summary;
  return {
    ...(partial && typeof partial === "object" && !Array.isArray(partial) ? partial : {}),
    ...run.summary
  };
}

function isMetricValue(value: unknown): value is StrategyTestMetricValue {
  return value == null || typeof value === "number" || typeof value === "string" || typeof value === "boolean";
}

function scenarioLabel(run: StrategyTestRunResponse): string {
  const count = run.requested_matrix.scenario_count;
  if (typeof count === "number") return `${count} scenarios`;
  return "matrix run";
}

function scenarioTotal(summary: Record<string, unknown>, run: StrategyTestRunResponse | null): number {
  return metricNumber(summary.scenarios_total ?? summary.scenario_count ?? run?.requested_matrix.scenario_count);
}

function scenarioCompleted(summary: Record<string, unknown>): number {
  return metricNumber(summary.scenarios_completed ?? summary.completed_scenarios);
}

function metricNumber(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function formatMetricValue(metric: StrategyTestMetric): string {
  if (metric.value == null) return "-";
  if (typeof metric.value === "number") {
    const formatted = Number.isInteger(metric.value) ? String(metric.value) : metric.value.toFixed(3);
    return metric.unit ? `${formatted} ${metric.unit}` : formatted;
  }
  return String(metric.value);
}
