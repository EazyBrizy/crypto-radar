"use client";

import { Upload, X } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";

import { Badge } from "@/components/Badge";
import { StrategyTestMetricGrid, formatMetricValue } from "./StrategyTestMetricGrid";
import { StrategyTestSignalList } from "./StrategyTestSignalList";
import { StrategyTestTradeList } from "./StrategyTestTradeList";
import type {
  StrategyTestCandidateAdjustment,
  StrategyTestCalibrationPublishResponse,
  StrategyTestMetric,
  StrategyTestMetricValue,
  StrategyTestReport as StrategyTestReportData,
  StrategyTestReportSection,
  StrategyTestRunResponse
} from "./types";

interface StrategyTestReportProps {
  error?: Error | null;
  loading?: boolean;
  onClose?: () => void;
  onPublishCalibration?: (runId: string) => Promise<StrategyTestCalibrationPublishResponse> | StrategyTestCalibrationPublishResponse;
  report: StrategyTestReportData | null;
  run: StrategyTestRunResponse | null;
}

const SECTION_TABLE_COLUMNS: Record<string, string[]> = {
  conversion_funnel: ["stage", "count", "rate"],
  entry_quality: ["strategy", "timeframe", "entry_touch_rate", "median_bars_to_entry", "false_signal_rate", "avg_mfe_r", "sample_size"],
  exit_quality: ["strategy", "timeframe", "tp1_rate", "tp2_rate", "stop_rate", "time_stop_rate", "avg_mfe_r", "avg_mae_r", "sample_size"],
  pair_timeframe_breakdown: ["strategy", "symbol", "timeframe", "trades_count", "winrate", "expectancy_r", "expectancy_after_costs_r", "max_drawdown_r", "sample_size"],
  regime_breakdown: ["strategy", "regime", "trades_count", "winrate", "expectancy_r", "stop_rate", "sample_size"],
  rejection_analysis: ["strategy", "risk_rejection_rate", "execution_rejection_rate", "sample_size"],
  score_bucket_breakdown: ["strategy", "score_bucket", "trades_count", "winrate", "expectancy_r", "expectancy_after_costs_r", "sample_size"],
  strategy_comparison: ["strategy", "trades_count", "winrate", "expectancy_r", "expectancy_after_costs_r", "profit_factor", "max_drawdown_r", "sample_size"]
};

export function StrategyTestReport({
  error,
  loading = false,
  onClose,
  onPublishCalibration,
  report,
  run
}: StrategyTestReportProps) {
  const [calibrationResult, setCalibrationResult] = useState<StrategyTestCalibrationPublishResponse | null>(null);
  const [calibrationError, setCalibrationError] = useState<string | null>(null);
  const [calibrationBusy, setCalibrationBusy] = useState(false);
  const liveForward = !report && isForwardRun(run);
  const summaryMetrics = liveForward ? [] : report?.summary_metrics ?? summaryMetricsFromRun(run);
  const adjustments = report?.candidate_adjustments ?? [];
  const canPublishCalibration = Boolean(report && report.status === "completed" && onPublishCalibration);

  async function handlePublishCalibration() {
    if (!report || !onPublishCalibration || calibrationBusy) return;
    setCalibrationBusy(true);
    setCalibrationError(null);
    try {
      const result = await onPublishCalibration(report.run_id);
      setCalibrationResult(result);
    } catch (error) {
      setCalibrationError(error instanceof Error ? error.message : "Unable to publish calibration");
    } finally {
      setCalibrationBusy(false);
    }
  }

  return (
    <section className="strategy-test-report-panel strategy-test-report-full" aria-live="polite">
      <div className="strategy-test-panel-head">
        <div>
          <h4>Strategy Test Report</h4>
          <span>{report ? `${shortRunId(report.run_id)} / ${report.status} / ${report.mode}` : reportFallbackLabel(run)}</span>
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
            <Badge tone="blue">{report?.trades_count ?? metricNumber(run?.summary.trades_count)} trades</Badge>
            <Badge tone={report?.warnings?.length ? "yellow" : "green"}>{report?.warnings?.length ?? 0} warnings</Badge>
            <Badge tone={report?.rejections?.length ? "red" : "neutral"}>{report?.rejections?.length ?? 0} rejections</Badge>
            {report ? <Badge tone="purple">{report.sections.length} sections</Badge> : null}
          </div>

          {canPublishCalibration ? (
            <div className="strategy-test-report-actions">
              <button
                className="secondary-action"
                disabled={calibrationBusy}
                onClick={handlePublishCalibration}
                type="button"
              >
                <Upload size={16} /> {calibrationBusy ? "Publishing calibration" : "Use this run for calibration"}
              </button>
            </div>
          ) : null}
          {calibrationResult ? (
            <p className="strategy-test-calibration-result">
              Calibration profiles updated: {calibrationResult.eligible_count} eligible, {calibrationResult.blocked_count} blocked
            </p>
          ) : null}
          {calibrationError ? <p className="form-error">{calibrationError}</p> : null}

          {liveForward ? null : (
            <StrategyTestMetricGrid emptyLabel="No summary metrics" limit={9} metrics={summaryMetrics} />
          )}

          {report ? (
            <div className="strategy-test-report-sections">
              <ReportSummarySection report={report} />
              <MetricSection report={report} sectionCode="strategy_comparison" />
              <MetricSection report={report} sectionCode="pair_timeframe_breakdown" />
              <MetricSection report={report} sectionCode="regime_breakdown" />
              <MetricSection report={report} sectionCode="score_bucket_breakdown" />
              <MetricSection report={report} sectionCode="entry_quality" />
              <MetricSection report={report} sectionCode="exit_quality" />
              <DistributionSection report={report} />
              <RejectionSection report={report} />
              <ConversionFunnelSection report={report} />
              <SignalListSection report={report} />
              <TradeListSection report={report} />
              <CandidateAdjustmentsSection adjustments={adjustments} />
            </div>
          ) : liveForward ? (
            <LiveForwardDashboard run={run} />
          ) : (
            <div className="empty-state compact-empty">No report selected</div>
          )}
        </>
      ) : null}
    </section>
  );
}

function LiveForwardDashboard({ run }: { run: StrategyTestRunResponse | null }) {
  const summary = run?.summary ?? {};
  return (
    <ReportSection name="Live forward test">
      <div className="strategy-test-summary-grid">
        {liveSummaryItem("Signals found", summary.signals_seen)}
        {liveSummaryItem("Execution candidates", summary.execution_candidates)}
        {liveSummaryItem("Blocked", summary.blocked_signals)}
        {liveSummaryItem("Pending", summary.pending_entries)}
        {liveSummaryItem("Filled", summary.filled_trades)}
        {liveSummaryItem("Open positions", summary.open_positions)}
        {liveSummaryItem("Closed trades", summary.closed_trades)}
        {liveSummaryItem("Current equity", summary.current_equity)}
        {liveSummaryItem("Realized PnL", summary.realized_pnl)}
        {liveSummaryItem("Unrealized PnL", summary.unrealized_pnl)}
        {liveSummaryItem("Last tick", summary.last_tick_at)}
      </div>
    </ReportSection>
  );
}

function ReportSummarySection({ report }: { report: StrategyTestReportData }) {
  const section = findSection(report, "summary");
  const summary = section?.summary ?? report.summary;
  return (
    <ReportSection name="Summary">
      <div className="strategy-test-summary-grid">
        {summaryItem("Scenarios", summary.scenario_count)}
        {summaryItem("Signals", summary.signals_count ?? summary.total_signals)}
        {summaryItem("Mode", summary.mode)}
        {summaryItem("Start", summary.start_at)}
        {summaryItem("End", summary.end_at)}
        {summaryItem("Winrate", summary.winrate)}
        {summaryItem("Expectancy R", summary.expectancy_r)}
        {summaryItem("After Costs R", summary.expectancy_after_costs_r)}
        {summaryItem("Max DD R", summary.max_drawdown_r)}
      </div>
    </ReportSection>
  );
}

function MetricSection({
  report,
  sectionCode
}: {
  report: StrategyTestReportData;
  sectionCode: string;
}) {
  const section = findSection(report, sectionCode);
  if (!section) return null;
  return (
    <ReportSection name={section.name}>
      <StrategyTestMetricGrid limit={6} metrics={section.metrics} />
      <SectionRowsTable columns={SECTION_TABLE_COLUMNS[section.code] ?? []} rows={section.rows} />
    </ReportSection>
  );
}

function DistributionSection({ report }: { report: StrategyTestReportData }) {
  const section = findSection(report, "mfe_mae_distribution");
  if (!section) return null;
  return (
    <ReportSection name={section.name}>
      <SectionRowsTable columns={["metric", "bucket", "count", "rate", "sample_size"]} rows={section.rows} />
    </ReportSection>
  );
}

function RejectionSection({ report }: { report: StrategyTestReportData }) {
  const section = findSection(report, "rejection_analysis");
  if (!section) return null;
  const warningCounts = arrayRows(section.summary.warning_counts);
  return (
    <ReportSection name={section.name}>
      <StrategyTestMetricGrid metrics={section.metrics} />
      <SectionRowsTable columns={SECTION_TABLE_COLUMNS.rejection_analysis} rows={section.rows} />
      <SectionRowsTable columns={["warning", "count"]} emptyLabel="No warning counts" rows={warningCounts} />
    </ReportSection>
  );
}

function ConversionFunnelSection({ report }: { report: StrategyTestReportData }) {
  const section = findSection(report, "conversion_funnel");
  if (!section) return null;
  return (
    <ReportSection name={section.name}>
      <div className="strategy-test-summary-grid">
        {summaryItem("Signals", section.summary.signals_count)}
        {summaryItem("Entry touched", section.summary.entry_touched_count)}
        {summaryItem("Filled", section.summary.filled_count)}
        {summaryItem("No entry", section.summary.no_entry_count)}
      </div>
      <SectionRowsTable columns={SECTION_TABLE_COLUMNS.conversion_funnel} rows={section.rows} />
    </ReportSection>
  );
}

function SignalListSection({ report }: { report: StrategyTestReportData }) {
  const section = findSection(report, "signal_list");
  if (!section) return null;
  return (
    <ReportSection name={section.name}>
      <StrategyTestSignalList signals={section.rows} />
    </ReportSection>
  );
}

function TradeListSection({ report }: { report: StrategyTestReportData }) {
  const section = findSection(report, "trade_list");
  if (!section) return null;
  return (
    <ReportSection name={section.name}>
      <StrategyTestTradeList trades={section.rows} />
    </ReportSection>
  );
}

function CandidateAdjustmentsSection({
  adjustments
}: {
  adjustments: StrategyTestCandidateAdjustment[];
}) {
  return (
    <ReportSection name="Recommended strategy adjustments">
      {adjustments.length ? (
        <div className="strategy-test-adjustment-grid">
          {adjustments.map((adjustment, index) => (
            <article className="strategy-test-adjustment-card" key={`${adjustment.strategy_code}:${adjustment.scope}:${index}`}>
              <div className="strategy-test-adjustment-head">
                <strong>{adjustment.strategy_code}</strong>
                <Badge tone={confidenceTone(adjustment.confidence)}>{adjustment.confidence}</Badge>
              </div>
              <span>{adjustment.scope}</span>
              <p>{adjustment.reason}</p>
              <small>{evidenceLabel(adjustment.evidence)}</small>
              <strong>{adjustment.suggested_change}</strong>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-state compact-empty">No candidate adjustments</div>
      )}
    </ReportSection>
  );
}

function ReportSection({ children, name }: { children: ReactNode; name: string }) {
  return (
    <section className="strategy-test-report-section">
      <h5>{name}</h5>
      {children}
    </section>
  );
}

function SectionRowsTable({
  columns,
  emptyLabel = "No rows",
  rows
}: {
  columns: string[];
  emptyLabel?: string;
  rows: Array<Record<string, unknown>>;
}) {
  const visibleColumns = columns.length ? columns : inferColumns(rows);
  if (!rows.length || !visibleColumns.length) {
    return <div className="empty-state compact-empty">{emptyLabel}</div>;
  }

  return (
    <div className="strategy-test-table-wrap">
      <table className="strategy-test-simple-table">
        <thead>
          <tr>
            {visibleColumns.map((column) => <th key={column}>{columnLabel(column)}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {visibleColumns.map((column) => <td key={column}>{formatCell(row[column])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function summaryItem(label: string, value: unknown) {
  return (
    <div className="strategy-test-summary-item" key={label}>
      <span>{label}</span>
      <strong>{formatCell(value)}</strong>
    </div>
  );
}

function liveSummaryItem(label: string, value: unknown) {
  return (
    <div className="strategy-test-summary-item" key={label}>
      <span>{label}</span>
      <strong>{value == null || value === "" ? "-" : String(value)}</strong>
    </div>
  );
}

function summaryMetricsFromRun(run: StrategyTestRunResponse | null): StrategyTestMetric[] {
  if (!run) return [];
  return Object.entries(run.summary)
    .filter((entry): entry is [string, StrategyTestMetricValue] => isMetricValue(entry[1]))
    .slice(0, 9)
    .map(([name, value]) => ({ name, value }));
}

function findSection(report: StrategyTestReportData, code: string): StrategyTestReportSection | null {
  return report.sections.find((section) => section.code === code) ?? null;
}

function arrayRows(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function inferColumns(rows: Array<Record<string, unknown>>): string[] {
  const first = rows[0];
  return first ? Object.keys(first).slice(0, 8) : [];
}

function formatCell(value: unknown): string {
  if (isMetricValue(value)) return formatMetricValue(value);
  if (value instanceof Date) return value.toLocaleString();
  if (Array.isArray(value)) return value.length ? `${value.length}` : "-";
  if (isRecord(value)) return Object.keys(value).length ? JSON.stringify(value) : "-";
  return "-";
}

function evidenceLabel(evidence: Record<string, unknown>): string {
  const entries = Object.entries(evidence).slice(0, 4);
  if (!entries.length) return "evidence unavailable";
  return entries.map(([key, value]) => `${columnLabel(key)}: ${formatCell(value)}`).join(" / ");
}

function reportFallbackLabel(run: StrategyTestRunResponse | null): string {
  if (!run) return "No run selected";
  return `${shortRunId(run.run_id)} / ${run.status}`;
}

function shortRunId(runId: string): string {
  return runId.slice(0, 8);
}

function confidenceTone(confidence: StrategyTestCandidateAdjustment["confidence"]): "green" | "yellow" | "blue" {
  if (confidence === "high") return "green";
  if (confidence === "medium") return "blue";
  return "yellow";
}

function metricNumber(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function isForwardRun(run: StrategyTestRunResponse | null): boolean {
  return run?.requested_matrix.test_type === "forward_virtual" && ["queued", "running", "stopping"].includes(run.status);
}

function columnLabel(column: string): string {
  return column.replaceAll("_", " ");
}

function isMetricValue(value: unknown): value is StrategyTestMetricValue {
  return value == null || typeof value === "number" || typeof value === "string" || typeof value === "boolean";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
