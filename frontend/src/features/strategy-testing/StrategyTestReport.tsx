"use client";

import { LoaderCircle, ShieldCheck, X } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/Badge";
import { StrategyTestMetricGrid, formatMetricValue } from "./StrategyTestMetricGrid";
import { StrategyTestTradeList } from "./StrategyTestTradeList";
import type {
  StrategyTestCandidateAdjustment,
  StrategyTestCalibrationDecision,
  StrategyTestCalibrationResponse,
  StrategyTestMetric,
  StrategyTestMetricValue,
  StrategyTestReport as StrategyTestReportData,
  StrategyTestReportSection,
  StrategyTestRunResponse,
  StrategyTestRunSummary
} from "./types";

interface StrategyTestReportProps {
  calibrationError?: Error | null;
  calibrationPending?: boolean;
  calibrationResult?: StrategyTestCalibrationResponse | null;
  error?: Error | null;
  loading?: boolean;
  onClose?: () => void;
  onPublishCalibration?: (runId: string) => void;
  report: StrategyTestReportData | null;
  run: StrategyTestRunResponse | null;
}

const SECTION_TABLE_COLUMNS: Record<string, string[]> = {
  entry_quality: ["strategy", "timeframe", "entry_touch_rate", "median_bars_to_entry", "false_signal_rate", "avg_mfe_r", "sample_size"],
  exit_quality: ["strategy", "timeframe", "tp1_rate", "tp2_rate", "stop_rate", "time_stop_rate", "avg_mfe_r", "avg_mae_r", "sample_size"],
  pair_timeframe_breakdown: ["strategy", "symbol", "timeframe", "trades_count", "winrate", "expectancy_r", "expectancy_after_costs_r", "max_drawdown_r", "sample_size"],
  regime_breakdown: ["strategy", "regime", "trades_count", "winrate", "expectancy_r", "stop_rate", "sample_size"],
  rejection_analysis: ["strategy", "risk_rejection_rate", "execution_rejection_rate", "sample_size"],
  score_bucket_breakdown: ["strategy", "score_bucket", "trades_count", "winrate", "expectancy_r", "expectancy_after_costs_r", "sample_size"],
  strategy_comparison: ["strategy", "trades_count", "winrate", "expectancy_r", "expectancy_after_costs_r", "profit_factor", "max_drawdown_r", "sample_size"]
};
const ACTIVE_RUN_STATUSES = new Set(["queued", "running", "stopping"]);

export function StrategyTestReport({
  calibrationError,
  calibrationPending = false,
  calibrationResult,
  error,
  loading = false,
  onClose,
  onPublishCalibration,
  report,
  run
}: StrategyTestReportProps) {
  const fallbackSummary = report?.summary ?? summaryFromRun(run);
  const summaryMetrics = report?.summary_metrics?.length ? report.summary_metrics : summaryMetricsFromSummary(fallbackSummary);
  const adjustments = report?.candidate_adjustments ?? [];
  const calibrationRunId = report?.run_id ?? run?.run_id ?? null;
  const calibrationStatus = report?.status ?? run?.status ?? null;
  const canPublishCalibration = Boolean(onPublishCalibration && calibrationRunId && calibrationStatus === "completed");
  const activeRunWithoutReport = Boolean(run && ACTIVE_RUN_STATUSES.has(run.status) && !report);
  const selectedRunWithoutReport = Boolean(run && !report && !activeRunWithoutReport);

  return (
    <section className="strategy-test-report-panel strategy-test-report-full" aria-live="polite">
      <div className="strategy-test-panel-head">
        <div>
          <h4>Strategy Test Report</h4>
          <span>{report ? `${shortRunId(report.run_id)} / ${report.status} / ${report.mode}` : reportFallbackLabel(run)}</span>
        </div>
        <div className="strategy-test-panel-actions">
          {canPublishCalibration ? (
            <button
              className="secondary-action compact-action"
              disabled={calibrationPending}
              onClick={() => onPublishCalibration?.(calibrationRunId as string)}
              type="button"
            >
              {calibrationPending ? <LoaderCircle size={16} /> : <ShieldCheck size={16} />}
              Use this run for calibration
            </button>
          ) : null}
          {onClose ? (
            <button className="icon-button compact" onClick={onClose} title="Close report" type="button">
              <X size={16} />
            </button>
          ) : null}
        </div>
      </div>

      {loading ? <div className="empty-state compact-empty">Loading report</div> : null}
      {error ? <p className="form-error">{error.message}</p> : null}

      {!loading && !error ? (
        <>
          <div className="strategy-test-report-strip">
            <Badge tone="blue">{metricNumber(fallbackSummary.signals_count ?? fallbackSummary.signals_seen)} signals</Badge>
            <Badge tone="blue">{report?.trades_count ?? metricNumber(fallbackSummary.trades_count)} trades</Badge>
            <Badge tone={report?.warnings?.length ? "yellow" : "green"}>{report?.warnings?.length ?? 0} warnings</Badge>
            <Badge tone={report?.rejections?.length ? "red" : "neutral"}>{report?.rejections?.length ?? 0} rejections</Badge>
            {report ? <Badge tone="purple">{report.sections.length} sections</Badge> : null}
          </div>

          {calibrationError ? <p className="form-error">{calibrationError.message}</p> : null}
          {calibrationResult ? <CalibrationPublicationResult result={calibrationResult} /> : null}

          {activeRunWithoutReport && run ? (
            <ActiveRunProgress run={run} />
          ) : (
            <StrategyTestMetricGrid emptyLabel="No summary metrics" limit={9} metrics={summaryMetrics} />
          )}

          {report ? (
            <div className="strategy-test-report-sections">
              <ReportSummarySection report={report} />
              <SignalFunnelSection report={report} />
              <MetricSection report={report} sectionCode="strategy_comparison" />
              <MetricSection report={report} sectionCode="pair_timeframe_breakdown" />
              <MetricSection report={report} sectionCode="regime_breakdown" />
              <MetricSection report={report} sectionCode="score_bucket_breakdown" />
              <MetricSection report={report} sectionCode="entry_quality" />
              <MetricSection report={report} sectionCode="exit_quality" />
              <DistributionSection report={report} />
              <RejectionSection report={report} />
              <TradeListSection report={report} />
              <CandidateAdjustmentsSection adjustments={adjustments} />
            </div>
          ) : activeRunWithoutReport ? null : selectedRunWithoutReport && run ? (
            <RunSummaryFallback run={run} summary={fallbackSummary} />
          ) : (
            <div className="empty-state compact-empty">No report selected</div>
          )}
        </>
      ) : null}
    </section>
  );
}

function RunSummaryFallback({
  run,
  summary
}: {
  run: StrategyTestRunResponse;
  summary: StrategyTestRunSummary;
}) {
  const message = fallbackReportMessage(run, summary);
  const completed = summaryNumberValue(summary, "completed_scenarios");
  const total = summaryNumberValue(summary, "scenario_count") ?? requestedScenarioCount(run);
  const failed = summaryNumberValue(summary, "failed_scenarios");
  return (
    <div className="strategy-test-report-sections">
      {message ? <p className={run.status === "failed" ? "form-error" : "empty-state compact-empty"}>{message}</p> : null}
      {run.error ? <p className="form-error">{run.error}</p> : null}
      <ReportSection name={run.status === "completed" ? "Summary" : "Partial summary"}>
        <div className="strategy-test-summary-grid" aria-label="Strategy test run summary">
          {summaryItem("Status", run.status)}
          {summaryItem("Scenarios", total != null ? `${completed ?? 0} / ${total}` : completed)}
          {summaryItem("Failed scenarios", failed ?? 0)}
          {summaryItem("Signals", summaryNumberValue(summary, "signals_count") ?? summaryNumberValue(summary, "signals_seen") ?? 0)}
          {summaryItem("Execution candidates", summaryNumberValue(summary, "execution_candidates") ?? 0)}
          {summaryItem("Pending armed", summaryNumberValue(summary, "pending_armed") ?? 0)}
          {summaryItem("Touched", summaryNumberValue(summary, "touched") ?? summaryNumberValue(summary, "entry_touched") ?? 0)}
          {summaryItem("Filled", summaryNumberValue(summary, "filled") ?? 0)}
          {summaryItem("Closed", summaryNumberValue(summary, "closed") ?? 0)}
          {summaryItem("No entry", summaryNumberValue(summary, "no_entry") ?? 0)}
          {summaryItem("Risk rejections", summaryNumberValue(summary, "risk_rejections") ?? 0)}
          {summaryItem("Execution rejections", summaryNumberValue(summary, "execution_rejections") ?? 0)}
        </div>
      </ReportSection>
    </div>
  );
}

function ActiveRunProgress({ run }: { run: StrategyTestRunResponse }) {
  const phase = runtimeText(run, "phase") ?? run.status;
  const scenarioCompleted = runtimeNumber(run, "scenarios_completed") ?? runtimeNumber(run, "scenario_completed") ?? summaryNumber(run, "completed_scenarios") ?? 0;
  const scenarioTotal = runtimeNumber(run, "scenarios_total") ?? runtimeNumber(run, "scenario_total") ?? requestedScenarioCount(run) ?? summaryNumber(run, "scenario_count") ?? 0;
  const currentScenarioIndex = runtimeNumber(run, "current_scenario_index");
  const matrixBarsProcessed = runtimeNumber(run, "matrix_bars_processed") ?? runtimeNumber(run, "bars_processed");
  const matrixBarsTotal = runtimeNumber(run, "matrix_bars_total") ?? runtimeNumber(run, "bars_total");
  const scenarioBarsProcessed = runtimeNumber(run, "current_scenario_bars_processed") ?? runtimeNumber(run, "scenario_bars_processed");
  const scenarioBarsTotal = runtimeNumber(run, "current_scenario_bars_total") ?? runtimeNumber(run, "scenario_bars_total");
  const barsPct = runtimeNumber(run, "bars_pct");
  const currentPair = currentPairLabel(run);
  const lastError = runtimeText(run, "last_error") ?? run.error;
  return (
    <ReportSection name="Progress">
      <section aria-label="Active run progress">
        <div className="strategy-test-summary-grid">
          {summaryItem("Status", run.status)}
          {summaryItem("Phase", phase)}
          {summaryItem("Heartbeat age", heartbeatAgeLabel(run.last_heartbeat_at))}
          {summaryItem("Scenarios", scenarioTotal ? `${scenarioCompleted} / ${scenarioTotal}` : scenarioCompleted)}
          {summaryItem("Current scenario", currentScenarioIndex && scenarioTotal ? `${currentScenarioIndex} / ${scenarioTotal}` : currentScenarioIndex ?? "-")}
          {summaryItem("Strategy", runtimeText(run, "current_strategy") ?? "-")}
          {summaryItem("Pair", currentPair)}
          {summaryItem("Timeframe", runtimeText(run, "current_timeframe") ?? "-")}
          {summaryItem("Matrix bars", formatBarsProgress(matrixBarsProcessed, matrixBarsTotal, barsPct))}
          {summaryItem("Scenario bars", formatBarsCount(scenarioBarsProcessed, scenarioBarsTotal))}
          {summaryItem("Throughput", formatBarsPerSecond(runtimeNumber(run, "bars_per_second")))}
          {summaryItem("ETA", formatSeconds(runtimeNumber(run, "eta_seconds")))}
          {summaryItem("Signals", runtimeCounterNumber(run, "signals") ?? runtimeNumber(run, "signals_seen") ?? summaryNumber(run, "signals_seen") ?? 0)}
          {summaryItem("Execution candidates", runtimeCounterNumber(run, "execution_candidates") ?? runtimeNumber(run, "execution_candidates") ?? summaryNumber(run, "execution_candidates") ?? 0)}
          {summaryItem("Pending armed", runtimeCounterNumber(run, "pending_armed") ?? runtimeNumber(run, "pending_armed") ?? summaryNumber(run, "pending_armed") ?? 0)}
          {summaryItem("Entry touched", runtimeNumber(run, "entry_touched") ?? runtimeNumber(run, "touched") ?? summaryNumber(run, "entry_touched") ?? 0)}
          {summaryItem("Filled", runtimeCounterNumber(run, "filled") ?? runtimeNumber(run, "filled") ?? summaryNumber(run, "filled") ?? 0)}
          {summaryItem("Closed", runtimeCounterNumber(run, "closed") ?? runtimeNumber(run, "closed") ?? summaryNumber(run, "closed") ?? 0)}
          {summaryItem("No entry", runtimeCounterNumber(run, "no_entry") ?? runtimeNumber(run, "no_entry") ?? summaryNumber(run, "no_entry") ?? 0)}
          {summaryItem("Not selected", runtimeNumber(run, "not_selected") ?? summaryNumber(run, "not_selected") ?? 0)}
          {summaryItem("Pending entries", runtimeCounterNumber(run, "pending_entries") ?? runtimeNumber(run, "pending_entries_count") ?? 0)}
          {summaryItem("Trades", runtimeNumber(run, "trades_count") ?? summaryNumber(run, "trades_count") ?? 0)}
          {summaryItem("Risk rejections", runtimeCounterNumber(run, "risk_rejections") ?? runtimeNumber(run, "risk_rejections") ?? summaryNumber(run, "risk_rejections") ?? 0)}
          {summaryItem("Execution rejections", runtimeCounterNumber(run, "execution_rejections") ?? runtimeNumber(run, "execution_rejections") ?? summaryNumber(run, "execution_rejections") ?? 0)}
          {summaryItem("Last progress", runtimeText(run, "last_progress_at") ?? "-")}
        </div>
        {lastError ? <p className="form-error">{lastError}</p> : null}
      </section>
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
        {summaryItem("Signals", summary.signals_count)}
        {summaryItem("Entry touch rate", summary.entry_touch_rate)}
        {summaryItem("No-entry rate", summary.no_entry_rate)}
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

function CalibrationPublicationResult({ result }: { result: StrategyTestCalibrationResponse }) {
  return (
    <section aria-label="Calibration publication result" className="strategy-test-calibration-result">
      <div className="strategy-test-adjustment-head">
        <strong>Calibration publication</strong>
        <Badge tone={calibrationTone(result.decision)}>{decisionLabel(result.decision)}</Badge>
      </div>
      <p>{result.reason}</p>
      <div className="strategy-test-report-strip">
        <Badge tone="blue">{result.profiles_count} profiles</Badge>
        <Badge tone="green">{countDecision(result, "positive")} positive</Badge>
        <Badge tone="yellow">{countDecision(result, "insufficient_sample")} insufficient</Badge>
        <Badge tone="red">{countDecision(result, "negative")} negative</Badge>
      </div>
    </section>
  );
}

function SignalFunnelSection({ report }: { report: StrategyTestReportData }) {
  const section = findSection(report, "signal_funnel");
  if (!section) return null;
  const summary = section.summary;
  const stages = arrayRows(summary.stages ?? section.metadata.stages);
  return (
    <ReportSection name={section.name}>
      <div className="strategy-test-summary-grid">
        {summaryItem("Signals", summary.signals_count)}
        {summaryItem("Execution candidates", summary.execution_candidates)}
        {summaryItem("Entry touched", summary.entry_touched)}
        {summaryItem("Filled", summary.filled)}
        {summaryItem("Closed", summary.closed)}
        {summaryItem("Wins", summary.wins)}
        {summaryItem("Losses", summary.losses)}
        {summaryItem("No entry", summary.no_entry)}
      </div>
      <StrategyTestMetricGrid limit={6} metrics={section.metrics} />
      <SectionRowsTable columns={["stage", "count", "rate"]} emptyLabel="No funnel stages" rows={stages} />
      <SectionRowsTable
        columns={[
          "synthetic_signal_id",
          "strategy_code",
          "symbol",
          "timeframe",
          "direction",
          "signal_score",
          "funnel_stage",
          "blocked_reason_code"
        ]}
        emptyLabel="No no-entry signals"
        rows={section.rows}
      />
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

function summaryFromRun(run: StrategyTestRunResponse | null): StrategyTestRunSummary {
  if (!run) return {};
  const partialSummary = run.runtime_state.partial_summary;
  const partial = isRecord(partialSummary) ? partialSummary : {};
  return {
    ...partial,
    ...run.summary
  } as StrategyTestRunSummary;
}

function summaryMetricsFromSummary(summary: StrategyTestRunSummary): StrategyTestMetric[] {
  return Object.entries(summary)
    .filter((entry): entry is [string, StrategyTestMetricValue] => isMetricValue(entry[1]))
    .slice(0, 9)
    .map(([name, value]) => ({ name, value }));
}

function fallbackReportMessage(run: StrategyTestRunResponse, summary: StrategyTestRunSummary): string {
  if (run.status === "failed") return "Report failed";
  if (run.status === "cancelled") return "Report cancelled with partial summary";
  if (run.status === "completed" && (summaryNumberValue(summary, "trades_count") ?? 0) === 0) {
    return "No trades, but test completed";
  }
  return "Report is not final yet";
}

function summaryNumberValue(summary: StrategyTestRunSummary, key: keyof StrategyTestRunSummary): number | null {
  const value = summary[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
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

function calibrationTone(decision: StrategyTestCalibrationDecision): "green" | "yellow" | "red" {
  if (decision === "positive") return "green";
  if (decision === "insufficient_sample") return "yellow";
  return "red";
}

function decisionLabel(decision: StrategyTestCalibrationDecision): string {
  return decision.replaceAll("_", " ");
}

function countDecision(result: StrategyTestCalibrationResponse, decision: StrategyTestCalibrationDecision): number {
  return (result.profiles ?? []).filter((profile) => profile.decision === decision).length;
}

function metricNumber(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function runtimeText(run: StrategyTestRunResponse, key: string): string | null {
  const value = run.runtime_state[key];
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text || null;
}

function runtimeNumber(run: StrategyTestRunResponse, key: string): number | null {
  const value = run.runtime_state[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function runtimeCounterNumber(run: StrategyTestRunResponse, key: string): number | null {
  const counters = run.runtime_state.counters;
  if (!counters || typeof counters !== "object" || Array.isArray(counters)) return null;
  const value = (counters as Record<string, unknown>)[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function summaryNumber(run: StrategyTestRunResponse, key: keyof StrategyTestRunResponse["summary"]): number | null {
  const value = run.summary[key] ?? partialSummaryValue(run, String(key));
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function partialSummaryValue(run: StrategyTestRunResponse, key: string): unknown {
  const partialSummary = run.runtime_state.partial_summary;
  if (!partialSummary || typeof partialSummary !== "object" || Array.isArray(partialSummary)) return null;
  return (partialSummary as Record<string, unknown>)[key];
}

function requestedScenarioCount(run: StrategyTestRunResponse): number | null {
  const value = run.requested_matrix.scenario_count;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function currentPairLabel(run: StrategyTestRunResponse): string {
  const exchange = runtimeText(run, "current_exchange");
  const symbol = runtimeText(run, "current_symbol");
  if (exchange && symbol) return `${exchange}:${symbol}`;
  return exchange ?? symbol ?? "-";
}

function heartbeatAgeLabel(value: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "-";
  const seconds = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function formatBarsProgress(processed: number | null, total: number | null, pct: number | null): string {
  if (processed == null && total == null) return "-";
  const processedValue = processed ?? 0;
  const totalValue = total ?? 0;
  const computedPct = pct ?? (totalValue > 0 ? (processedValue / totalValue) * 100 : null);
  const percent = computedPct == null ? null : formatNumber(computedPct);
  return percent == null ? `${processedValue} / ${totalValue}` : `${processedValue} / ${totalValue} (${percent}%)`;
}

function formatBarsCount(processed: number | null, total: number | null): string {
  if (processed == null && total == null) return "-";
  return `${processed ?? 0} / ${total ?? 0}`;
}

function formatBarsPerSecond(value: number | null): string {
  if (value == null) return "-";
  return `${formatNumber(value)} bars/s`;
}

function formatSeconds(value: number | null): string {
  if (value == null) return "-";
  const seconds = Math.max(0, Math.round(value));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return remainingSeconds ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return "0";
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2).replace(/0+$/u, "").replace(/\.$/u, "");
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
