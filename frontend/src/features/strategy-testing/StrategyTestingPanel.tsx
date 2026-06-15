"use client";

import { AlertTriangle, BarChart3, FlaskConical, Play, RadioTower, RefreshCw, XCircle, Zap } from "lucide-react";
import { useMemo, useState, type FormEvent, type ReactNode } from "react";

import { Badge } from "@/components/Badge";
import type { MarketPairOption, StrategyConfig } from "@/features/server-state/types";
import {
  useCancelStrategyTestRun,
  usePublishStrategyTestCalibration,
  useRunStrategyTest,
  useStrategyTestActiveRun,
  useStrategyTestRun,
  useStrategyTestReport,
  useStrategyTestRuns
} from "@/hooks/use-radar-queries";
import { StrategyTestReport } from "./StrategyTestReport";
import { StrategyTestRunsTable } from "./StrategyTestRunsTable";
import type {
  StrategyTestActiveRunResponse,
  StrategyTestMode,
  StrategyTestPair,
  StrategyTestRunRequest,
  StrategyTestRunResponse,
  StrategyTestRunStatus,
  StrategyTestSameCandlePolicy,
  StrategyTestType
} from "./types";

interface StrategyTestingPanelProps {
  availablePairs: MarketPairOption[];
  strategyConfigs: StrategyConfig[];
}

const STRATEGY_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];
const DEFAULT_SELECTED_TIMEFRAMES = ["1m", "5m", "15m"];
const DEFAULT_MODE: StrategyTestMode = "research_virtual";
const DEFAULT_TEST_TYPE: StrategyTestType = "historical_backtest";
const DEFAULT_SAME_CANDLE_POLICY: StrategyTestSameCandlePolicy = "stop_first";
const DEFAULT_PENDING_ENTRY_MAX_WAIT_BARS = "12";
const SMOKE_PRESET_DAYS = 3;
const MEDIUM_RUN_TOTAL_BARS = 50_000;
const LARGE_RUN_TOTAL_BARS = 250_000;
const MEDIUM_RUN_SCENARIOS = 8;
const LARGE_RUN_SCENARIOS = 24;

const TEST_TYPE_OPTIONS: Array<{ value: StrategyTestType; label: string }> = [
  { value: "historical_backtest", label: "Historical" },
  { value: "forward_virtual", label: "Forward virtual" }
];

const MODE_LABELS: Record<StrategyTestMode, string> = {
  discovery: "Discovery",
  research_virtual: "Research virtual",
  production_like: "Production-like"
};

const MODE_DESCRIPTIONS: Record<StrategyTestMode, string> = {
  discovery: "No trades; signal discovery only.",
  research_virtual: "Soft risk, virtual execution, pending policy.",
  production_like: "Strict checks, closer to real execution."
};

const POLICY_LABELS: Record<StrategyTestSameCandlePolicy, string> = {
  conservative_stop_first: "Conservative stop first",
  ignore_ambiguous: "Ignore ambiguous",
  intrabar_unknown: "Intrabar unknown",
  stop_first: "Stop first",
  target_first: "Target first"
};
const ACTIVE_RUN_STATUSES = new Set<StrategyTestRunStatus>(["queued", "running", "stopping"]);
const STRATEGY_TEST_RUN_POLL_MS = 2_500;

export function StrategyTestingPanel({
  availablePairs,
  strategyConfigs
}: StrategyTestingPanelProps) {
  const dateDefaults = useMemo(() => defaultDateRange(), []);
  const strategyOptions = useMemo(() => enabledStrategyOptions(strategyConfigs), [strategyConfigs]);
  const pairOptions = useMemo(() => availablePairs.slice(0, 50), [availablePairs]);
  const timeframeOptions = useMemo(() => availableTimeframes(strategyOptions), [strategyOptions]);
  const activeRunQuery = useStrategyTestActiveRun(undefined, { refetchInterval: STRATEGY_TEST_RUN_POLL_MS });
  const runsQuery = useStrategyTestRuns({ limit: 25 }, { refetchInterval: STRATEGY_TEST_RUN_POLL_MS });
  const runMutation = useRunStrategyTest();
  const cancelRunMutation = useCancelStrategyTestRun();
  const calibrationMutation = usePublishStrategyTestCalibration();
  const [selectedStrategyCodes, setSelectedStrategyCodes] = useState<string[] | null>(null);
  const [selectedPairIds, setSelectedPairIds] = useState<string[] | null>(null);
  const [selectedTimeframes, setSelectedTimeframes] = useState<string[] | null>(null);
  const [mode, setMode] = useState<StrategyTestMode>(DEFAULT_MODE);
  const [testType, setTestType] = useState<StrategyTestType>(DEFAULT_TEST_TYPE);
  const [startAt, setStartAt] = useState(dateDefaults.startAt);
  const [endAt, setEndAt] = useState(dateDefaults.endAt);
  const [initialCapital, setInitialCapital] = useState("1000");
  const [feeRate, setFeeRate] = useState("0.001");
  const [slippageBps, setSlippageBps] = useState("0");
  const [sameCandlePolicy, setSameCandlePolicy] = useState<StrategyTestSameCandlePolicy>(DEFAULT_SAME_CANDLE_POLICY);
  const [historicalPendingEntriesEnabled, setHistoricalPendingEntriesEnabled] = useState(true);
  const [pendingEntryMaxWaitBars, setPendingEntryMaxWaitBars] = useState(DEFAULT_PENDING_ENTRY_MAX_WAIT_BARS);
  const [formError, setFormError] = useState<string | null>(null);
  const [selectedReportRunId, setSelectedReportRunId] = useState<string | null>(null);
  const [largeRunConfirmation, setLargeRunConfirmation] = useState<{ confirmed: boolean; key: string | null }>({
    confirmed: false,
    key: null
  });
  const defaultStrategySelection = useMemo(() => defaultStrategyCodes(strategyOptions), [strategyOptions]);
  const defaultPairSelection = useMemo(() => defaultPairIds(pairOptions), [pairOptions]);
  const defaultTimeframeSelection = useMemo(() => defaultTimeframes(timeframeOptions), [timeframeOptions]);
  const effectiveStrategyCodes = selectedStrategyCodes ?? defaultStrategySelection;
  const effectivePairIds = selectedPairIds ?? defaultPairSelection;
  const effectiveTimeframes = selectedTimeframes ?? defaultTimeframeSelection;

  const selectedPairs = useMemo(
    () => pairOptions.filter((pair) => effectivePairIds.includes(pairKey(pair))),
    [effectivePairIds, pairOptions]
  );
  const validTimeframes = effectiveTimeframes.filter((timeframe) => timeframeOptions.includes(timeframe));
  const dateError = validateDateRange(startAt, endAt);
  const numberError = validateNumericInputs(initialCapital, feeRate, slippageBps, pendingEntryMaxWaitBars);
  const runEstimate = useMemo(() => estimateRunSize({
    endAt,
    selectedPairsCount: selectedPairs.length,
    selectedStrategyCodesCount: effectiveStrategyCodes.length,
    selectedTimeframes: validTimeframes,
    startAt
  }), [effectiveStrategyCodes.length, endAt, selectedPairs.length, startAt, validTimeframes]);
  const scenarioEstimate = runEstimate.scenarioCount;
  const requiresLargeRunConfirmation = runEstimate.level === "large";
  const runConfirmationKey = [
    effectiveStrategyCodes.join(","),
    effectivePairIds.join(","),
    validTimeframes.join(","),
    mode,
    testType,
    startAt,
    endAt,
    initialCapital,
    feeRate,
    slippageBps,
    sameCandlePolicy,
    historicalPendingEntriesEnabled,
    pendingEntryMaxWaitBars
  ].join("|");
  const largeRunConfirmed = largeRunConfirmation.confirmed && largeRunConfirmation.key === runConfirmationKey;
  const runs = runsQuery.data ?? [];
  const mutationRunIsMissingFromList = Boolean(
    runMutation.data && !runs.some((run) => run.run_id === runMutation.data?.run_id)
  );
  const recentActiveRun = runs.find((run) => isActiveStrategyTestRun(run.status)) ?? null;
  const fallbackActiveRun = recentActiveRun ??
    (mutationRunIsMissingFromList && isActiveStrategyTestRun(runMutation.data?.status) ? runMutation.data ?? null : null);
  const activeRunState = activeRunQuery.data ?? null;
  const activeRunFromState = activeRunState?.active_run ?? fallbackActiveRun;
  const activeRunDetailQuery = useStrategyTestRun(activeRunFromState?.run_id ?? null, {
    enabled: Boolean(activeRunFromState && isActiveStrategyTestRun(activeRunFromState.status)),
    refetchInterval: STRATEGY_TEST_RUN_POLL_MS
  });
  const activeRun = activeRunDetailQuery.data ?? activeRunFromState;
  const selectedRun = runs.find((run) => run.run_id === selectedReportRunId) ?? null;
  const mutationSelectedRun = runMutation.data?.run_id === selectedReportRunId ? runMutation.data : null;
  const activeSelectedRun = activeRun?.run_id === selectedReportRunId ? activeRun : null;
  const selectedRunForReport = selectedRun ?? mutationSelectedRun ?? activeSelectedRun;
  const funnelSummaryRun = selectedRunForReport ?? runs[0] ?? null;
  const selectedRunStatus = selectedRunForReport?.status ?? null;
  const selectedRunIsActive = isActiveStrategyTestRun(selectedRunStatus);
  const selectedReportIsReady = Boolean(selectedReportRunId && !selectedRunIsActive);
  const activeRunStateLoaded = activeRunState !== null;
  const activeRunBlocksRun = activeRunStateLoaded ? !activeRunState.can_run : Boolean(fallbackActiveRun);
  const activeRunIsStale = Boolean(activeRunState?.active_run && activeRunState.is_stale);
  const showRunInProgress = Boolean((activeRunState?.active_run && !activeRunState.is_stale) || (!activeRunStateLoaded && fallbackActiveRun));
  const canRun = scenarioEstimate > 0 &&
    !dateError &&
    !numberError &&
    !runMutation.isPending &&
    !cancelRunMutation.isPending &&
    !activeRunBlocksRun;
  const reportQuery = useStrategyTestReport(selectedReportRunId, {
    enabled: selectedReportIsReady,
    refetchInterval: false
  });
  const apiError = errorMessage(runMutation.error);
  const runButtonLabel = requiresLargeRunConfirmation && largeRunConfirmed ? "Confirm large run" : "Run strategy test";

  async function handleRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    if (!canRun) {
      setFormError(
        dateError ??
        numberError ??
        activeRunState?.disabled_reason ??
        (activeRunBlocksRun ? "A strategy test run is already in progress." : "Select at least one strategy, pair, and timeframe.")
      );
      return;
    }

    if (requiresLargeRunConfirmation && !largeRunConfirmed) {
      setLargeRunConfirmation({ confirmed: true, key: runConfirmationKey });
      return;
    }

    try {
      const response = await runMutation.mutateAsync(buildRunRequest({
        endAt,
        feeRate,
        initialCapital,
        mode,
        historicalPendingEntriesEnabled,
        pendingEntryMaxWaitBars,
        sameCandlePolicy,
        selectedPairs,
        selectedStrategyCodes: effectiveStrategyCodes,
        selectedTimeframes: validTimeframes,
        slippageBps,
        startAt,
        testType
      }));
      setSelectedReportRunId(response.run_id);
    } catch (error) {
      setFormError(errorMessage(error) ?? "Unable to start strategy test.");
    }
  }

  function applyPreset(preset: "smoke" | "research" | "forward_virtual") {
    setFormError(null);
    if (preset === "smoke") {
      const end = new Date();
      end.setSeconds(0, 0);
      const start = new Date(end);
      start.setDate(start.getDate() - SMOKE_PRESET_DAYS);
      setSelectedStrategyCodes(defaultStrategySelection.slice(0, 1));
      setSelectedPairIds(pairOptions[0] ? [pairKey(pairOptions[0])] : []);
      setSelectedTimeframes(timeframeOptions[0] ? [timeframeOptions[0]] : []);
      setMode("production_like");
      setTestType("historical_backtest");
      setStartAt(toDateTimeLocal(start));
      setEndAt(toDateTimeLocal(end));
      setHistoricalPendingEntriesEnabled(true);
      return;
    }

    if (preset === "forward_virtual") {
      setMode("research_virtual");
      setTestType("forward_virtual");
      return;
    }

    setMode("research_virtual");
    setTestType("historical_backtest");
    setHistoricalPendingEntriesEnabled(true);
  }

  async function handleCancelRun(runId: string) {
    setFormError(null);
    try {
      const response = await cancelRunMutation.mutateAsync(runId);
      setSelectedReportRunId(response.run_id);
    } catch (error) {
      setFormError(errorMessage(error) ?? "Unable to cancel strategy test run.");
    }
  }

  async function handlePublishCalibration(runId: string) {
    setFormError(null);
    try {
      await calibrationMutation.mutateAsync(runId);
    } catch {
      return;
    }
  }

  return (
    <form className="strategy-testing-panel" onSubmit={handleRun}>
      <div className="strategy-test-status-strip">
        <Badge tone="blue">{`${scenarioEstimate} scenarios`}</Badge>
        <Badge tone="purple">{`${runs.length} recent runs`}</Badge>
        {runsQuery.isLoading ? <Badge tone="yellow">Loading runs</Badge> : null}
        {activeRunQuery.isLoading ? <Badge tone="yellow">Loading active run</Badge> : null}
        {showRunInProgress ? <Badge tone="yellow">Run in progress</Badge> : null}
        {activeRunIsStale ? <Badge tone="yellow">Stale active run</Badge> : null}
      </div>

      <FunnelSummaryStrip run={funnelSummaryRun} />

      <div className="strategy-test-preset-row" aria-label="Strategy test presets">
        <button onClick={() => applyPreset("smoke")} type="button">
          <Zap size={16} />
          <span>
            <strong>Smoke</strong>
            <small>1 pair / 1 timeframe / 3 days / production-like</small>
          </span>
        </button>
        <button onClick={() => applyPreset("research")} type="button">
          <FlaskConical size={16} />
          <span>
            <strong>Research</strong>
            <small>Selected matrix / research virtual</small>
          </span>
        </button>
        <button onClick={() => applyPreset("forward_virtual")} type="button">
          <RadioTower size={16} />
          <span>
            <strong>Forward virtual</strong>
            <small>Selected matrix / live virtual runtime</small>
          </span>
        </button>
      </div>

      {activeRun ? (
        <ActiveRunNotice
          activeRunState={activeRunState}
          cancelPending={cancelRunMutation.isPending}
          onCancel={handleCancelRun}
          onOpenReport={(runId) => setSelectedReportRunId(runId)}
          onRefresh={() => void activeRunQuery.refetch()}
          run={activeRun}
        />
      ) : null}

      <div className="strategy-test-grid">
        <SelectionGroup title="Strategies">
          {strategyOptions.length ? strategyOptions.map((strategy) => (
            <label className="strategy-test-check-option" key={strategy.strategy_code}>
              <input
                checked={effectiveStrategyCodes.includes(strategy.strategy_code)}
                onChange={() => setSelectedStrategyCodes((current) =>
                  toggleValue(current ?? defaultStrategySelection, strategy.strategy_code)
                )}
                type="checkbox"
              />
              <span>
                <strong>{strategy.strategy_name}</strong>
                <small>{strategy.strategy_code}</small>
              </span>
            </label>
          )) : <div className="empty-state compact-empty">No enabled strategies</div>}
        </SelectionGroup>

        <SelectionGroup title="Pairs">
          {pairOptions.length ? pairOptions.map((pair) => (
            <label className="strategy-test-check-option compact" key={pairKey(pair)}>
              <input
                checked={effectivePairIds.includes(pairKey(pair))}
                onChange={() => setSelectedPairIds((current) =>
                  toggleValue(current ?? defaultPairSelection, pairKey(pair))
                )}
                type="checkbox"
              />
              <span>
                <strong>{pair.exchange}:{pair.symbol}</strong>
                <small>{pair.base_asset}/{pair.quote_asset}</small>
              </span>
            </label>
          )) : <div className="empty-state compact-empty">No pairs</div>}
        </SelectionGroup>

        <SelectionGroup title="Timeframes">
          <div className="strategy-test-timeframe-grid">
            {timeframeOptions.map((timeframe) => (
              <label className="strategy-test-check-option compact" key={timeframe}>
                <input
                  checked={effectiveTimeframes.includes(timeframe)}
                  onChange={() => setSelectedTimeframes((current) =>
                    toggleValue(current ?? defaultTimeframeSelection, timeframe)
                  )}
                  type="checkbox"
                />
                <span><strong>{timeframe}</strong></span>
              </label>
            ))}
          </div>
        </SelectionGroup>
      </div>

      <div className="strategy-test-controls">
        <label className="strategy-test-field">
          <span>Start</span>
          <input onChange={(event) => setStartAt(event.target.value)} type="datetime-local" value={startAt} />
        </label>
        <label className="strategy-test-field">
          <span>End</span>
          <input onChange={(event) => setEndAt(event.target.value)} type="datetime-local" value={endAt} />
        </label>
        <label className="strategy-test-field">
          <span>Initial capital</span>
          <input inputMode="decimal" min="1" onChange={(event) => setInitialCapital(event.target.value)} step="1" type="number" value={initialCapital} />
        </label>
        <label className="strategy-test-field">
          <span>Fee rate</span>
          <input inputMode="decimal" min="0" onChange={(event) => setFeeRate(event.target.value)} step="0.0001" type="number" value={feeRate} />
        </label>
        <label className="strategy-test-field">
          <span>Slippage bps</span>
          <input inputMode="decimal" min="0" onChange={(event) => setSlippageBps(event.target.value)} step="0.1" type="number" value={slippageBps} />
        </label>
        <label className="strategy-test-field">
          <span>Same candle</span>
          <select
            onChange={(event) => setSameCandlePolicy(event.target.value as StrategyTestSameCandlePolicy)}
            value={sameCandlePolicy}
          >
            {Object.entries(POLICY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="strategy-test-mode-row" aria-label="Strategy test mode">
        {(Object.keys(MODE_LABELS) as StrategyTestMode[]).map((option) => (
          <button
            aria-label={MODE_LABELS[option]}
            className={mode === option ? "active" : ""}
            key={option}
            onClick={() => setMode(option)}
            title={MODE_DESCRIPTIONS[option]}
            type="button"
          >
            <strong>{MODE_LABELS[option]}</strong>
            <small>{MODE_DESCRIPTIONS[option]}</small>
          </button>
        ))}
      </div>

      <div className="strategy-test-mode-row" aria-label="Strategy test type">
        {TEST_TYPE_OPTIONS.map((option) => (
          <button
            className={testType === option.value ? "active" : ""}
            key={option.value}
            onClick={() => setTestType(option.value)}
            type="button"
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="strategy-test-advanced-controls" aria-label="Historical pending entry policy">
        <label className="strategy-test-toggle" title="Replay wait-for-entry signals as pending entries during historical backtests.">
          <input
            checked={mode !== "discovery" && historicalPendingEntriesEnabled}
            disabled={mode === "discovery" || testType !== "historical_backtest"}
            onChange={(event) => setHistoricalPendingEntriesEnabled(event.target.checked)}
            type="checkbox"
          />
          <span>Historical pending entries</span>
        </label>
        <label className="strategy-test-field" title="Maximum closed candles to wait for the entry zone touch.">
          <span>Pending max wait bars</span>
          <input
            aria-label="Pending max wait bars"
            disabled={testType !== "historical_backtest"}
            inputMode="numeric"
            min="1"
            onChange={(event) => setPendingEntryMaxWaitBars(event.target.value)}
            step="1"
            type="number"
            value={pendingEntryMaxWaitBars}
          />
        </label>
      </div>

      <RunEstimatePanel confirmed={largeRunConfirmed} estimate={runEstimate} />

      {dateError || numberError || formError || apiError ? (
        <p className="form-error">{formError ?? dateError ?? numberError ?? apiError}</p>
      ) : null}

      <div className="strategy-test-actions">
        <button className="primary-action" disabled={!canRun} type="submit">
          {runMutation.isPending ? <RefreshCw size={16} /> : <Play size={16} />}
          {runButtonLabel}
        </button>
      </div>

      <StrategyTestRunsTable
        onOpenReport={(run) => setSelectedReportRunId(run.run_id)}
        runs={runs}
        selectedRunId={selectedReportRunId}
      />

      {selectedReportRunId ? (
        <StrategyTestReport
          calibrationError={calibrationMutation.error instanceof Error ? calibrationMutation.error : null}
          calibrationPending={calibrationMutation.isPending}
          calibrationResult={calibrationMutation.data?.run_id === selectedReportRunId ? calibrationMutation.data : null}
          error={reportQuery.error instanceof Error ? reportQuery.error : null}
          loading={reportQuery.isLoading}
          onClose={() => setSelectedReportRunId(null)}
          onPublishCalibration={handlePublishCalibration}
          report={reportQuery.data ?? null}
          run={selectedRunForReport}
        />
      ) : null}
    </form>
  );
}

function SelectionGroup({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section className="strategy-test-selection-group">
      <h4>{title}</h4>
      <div className="strategy-test-selection-list">{children}</div>
    </section>
  );
}

function RunEstimatePanel({
  confirmed,
  estimate
}: {
  confirmed: boolean;
  estimate: RunEstimate;
}) {
  const tone = estimate.level === "large" ? "red" : estimate.level === "medium" ? "yellow" : "green";
  return (
    <section
      aria-label="Strategy test run estimate"
      className={`strategy-test-estimate strategy-test-estimate-${estimate.level}`}
    >
      <div className="strategy-test-estimate-head">
        <div>
          <strong>Run estimate</strong>
          <span>{estimateWarningText(estimate)}</span>
        </div>
        <Badge tone={tone}>{runLevelLabel(estimate.level)}</Badge>
      </div>
      <div className="strategy-test-estimate-grid">
        {estimateItem("Scenario count", estimate.scenarioCount)}
        {estimateItem("Bars / scenario", formatBarsPerScenario(estimate.approximateBarsPerScenario))}
        {estimateItem("Approx total bars", formatTotalBars(estimate.approximateTotalBars))}
        {estimateItem("Timeframe bars", formatTimeframeBars(estimate.timeframeBars))}
      </div>
      {estimate.level === "large" ? (
        <div className="strategy-test-large-confirmation" aria-label={confirmed ? "Large run confirmation" : undefined}>
          <AlertTriangle size={16} />
          <span>
            {confirmed
              ? "Large run confirmation is armed. Click Confirm large run to start it."
              : "Large historical runs can sit on one scenario for a long time and may produce many signals without trades."}
          </span>
        </div>
      ) : null}
    </section>
  );
}

function estimateItem(label: string, value: string | number) {
  return (
    <div className="strategy-test-estimate-item" key={label}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function estimateRunSize({
  endAt,
  selectedPairsCount,
  selectedStrategyCodesCount,
  selectedTimeframes,
  startAt
}: {
  endAt: string;
  selectedPairsCount: number;
  selectedStrategyCodesCount: number;
  selectedTimeframes: string[];
  startAt: string;
}): RunEstimate {
  const scenarioCount = selectedStrategyCodesCount * selectedPairsCount * selectedTimeframes.length;
  const durationMs = dateRangeDurationMs(startAt, endAt);
  const timeframeBars = selectedTimeframes.map((timeframe) => ({
    bars: durationMs == null ? null : estimateBarsForTimeframe(durationMs, timeframe),
    timeframe
  }));
  const knownTimeframeBars = timeframeBars
    .map((entry) => entry.bars)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const approximateTotalBars = knownTimeframeBars.length === selectedTimeframes.length
    ? selectedStrategyCodesCount * selectedPairsCount * knownTimeframeBars.reduce((sum, bars) => sum + bars, 0)
    : null;
  const approximateBarsPerScenario = approximateTotalBars != null && scenarioCount > 0
    ? Math.round(approximateTotalBars / scenarioCount)
    : null;
  return {
    approximateBarsPerScenario,
    approximateTotalBars,
    level: estimateRunLevel(scenarioCount, approximateTotalBars),
    scenarioCount,
    timeframeBars
  };
}

function estimateRunLevel(scenarioCount: number, approximateTotalBars: number | null): RunEstimateLevel {
  const bars = approximateTotalBars ?? 0;
  if (bars >= LARGE_RUN_TOTAL_BARS || scenarioCount >= LARGE_RUN_SCENARIOS) return "large";
  if (bars >= MEDIUM_RUN_TOTAL_BARS || scenarioCount >= MEDIUM_RUN_SCENARIOS) return "medium";
  return "small";
}

function dateRangeDurationMs(startAt: string, endAt: string): number | null {
  const start = new Date(startAt);
  const end = new Date(endAt);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= start) return null;
  return end.getTime() - start.getTime();
}

function estimateBarsForTimeframe(durationMs: number, timeframe: string): number | null {
  const timeframeMs = timeframeToMs(timeframe);
  if (timeframeMs == null) return null;
  return Math.max(0, Math.ceil(durationMs / timeframeMs));
}

function timeframeToMs(timeframe: string): number | null {
  const match = /^(\d+)(m|h|d)$/u.exec(timeframe.trim());
  if (!match) return null;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount) || amount <= 0) return null;
  const unit = match[2];
  if (unit === "m") return amount * 60 * 1000;
  if (unit === "h") return amount * 60 * 60 * 1000;
  return amount * 24 * 60 * 60 * 1000;
}

function runLevelLabel(level: RunEstimateLevel): string {
  if (level === "large") return "Large run";
  if (level === "medium") return "Medium run";
  return "Small run";
}

function estimateWarningText(estimate: RunEstimate): string {
  if (estimate.level === "large") return "Review before launch; confirmation is required.";
  if (estimate.level === "medium") return "Reasonable for research, but watch active progress.";
  return "Fast enough for a quick validation pass.";
}

function formatBarsPerScenario(value: number | null): string {
  return value == null ? "-" : `~${formatInteger(value)} avg`;
}

function formatTotalBars(value: number | null): string {
  return value == null ? "-" : `~${formatInteger(value)} bars total`;
}

function formatTimeframeBars(timeframeBars: RunEstimate["timeframeBars"]): string {
  if (!timeframeBars.length) return "-";
  return timeframeBars
    .map((entry) => entry.bars == null ? `${entry.timeframe}: unknown` : `${entry.timeframe}: ~${formatInteger(entry.bars)}`)
    .join(" / ");
}

function FunnelSummaryStrip({ run }: { run: StrategyTestRunResponse | null }) {
  const signalsCount = numericSummary(run, "signals_count") ?? numericSummary(run, "signals_seen");
  if (signalsCount == null) return null;
  return (
    <div className="strategy-test-status-strip strategy-test-funnel-strip" aria-label="Strategy test funnel summary">
      <Badge tone="blue">{`${signalsCount} signals`}</Badge>
      <Badge tone="purple">{`${numericSummary(run, "execution_candidates") ?? 0} candidates`}</Badge>
      <Badge tone="green">{`${numericSummary(run, "entry_touched") ?? 0} touched`}</Badge>
      <Badge tone="blue">{`${numericSummary(run, "filled") ?? numericSummary(run, "trades_count") ?? 0} filled`}</Badge>
      <Badge tone="green">{`${numericSummary(run, "closed") ?? numericSummary(run, "trades_count") ?? 0} closed`}</Badge>
      <Badge tone="yellow">{`${numericSummary(run, "no_entry") ?? 0} no entry`}</Badge>
    </div>
  );
}

type RunEstimateLevel = "small" | "medium" | "large";

interface RunEstimate {
  approximateBarsPerScenario: number | null;
  approximateTotalBars: number | null;
  level: RunEstimateLevel;
  scenarioCount: number;
  timeframeBars: Array<{ timeframe: string; bars: number | null }>;
}

function enabledStrategyOptions(strategyConfigs: StrategyConfig[]): StrategyConfig[] {
  const seen = new Set<string>();
  return strategyConfigs.filter((strategy) => {
    if (!strategy.is_enabled || seen.has(strategy.strategy_code)) return false;
    seen.add(strategy.strategy_code);
    return true;
  });
}

function availableTimeframes(strategyOptions: StrategyConfig[]): string[] {
  const configured = strategyOptions.flatMap((strategy) => strategy.timeframes);
  const timeframes = configured.length ? configured : STRATEGY_TIMEFRAMES;
  const unique = Array.from(new Set(timeframes.map((timeframe) => timeframe.trim()).filter(Boolean)));
  return unique.length ? unique : STRATEGY_TIMEFRAMES;
}

function defaultStrategyCodes(strategyOptions: StrategyConfig[]): string[] {
  const first = strategyOptions[0]?.strategy_code;
  return first ? [first] : [];
}

function defaultPairIds(pairOptions: MarketPairOption[]): string[] {
  return pairOptions.slice(0, 3).map(pairKey);
}

function defaultTimeframes(timeframeOptions: string[]): string[] {
  const defaults = DEFAULT_SELECTED_TIMEFRAMES.filter((timeframe) => timeframeOptions.includes(timeframe));
  return defaults.length ? defaults : timeframeOptions.slice(0, 3);
}

function pairKey(pair: Pick<MarketPairOption, "exchange" | "symbol">): string {
  return `${pair.exchange}:${pair.symbol}`;
}

function toggleValue(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function isActiveStrategyTestRun(status: StrategyTestRunStatus | null | undefined): boolean {
  return status != null && ACTIVE_RUN_STATUSES.has(status);
}

function numericSummary(run: StrategyTestRunResponse | null, key: keyof StrategyTestRunResponse["summary"]): number | null {
  const keyText = String(key);
  const value = run?.summary[key] ?? runtimePartialValue(run, keyText) ?? run?.runtime_state[keyText];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function runtimePartialValue(run: StrategyTestRunResponse | null, key: string): unknown {
  const partialSummary = run?.runtime_state.partial_summary;
  if (!partialSummary || typeof partialSummary !== "object" || Array.isArray(partialSummary)) return null;
  return (partialSummary as Record<string, unknown>)[key];
}

function validateDateRange(startAt: string, endAt: string): string | null {
  if (!startAt || !endAt) return "Select a start and end date.";
  const start = new Date(startAt);
  const end = new Date(endAt);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "Date range is invalid.";
  if (end <= start) return "End date must be after start date.";
  return null;
}

function validateNumericInputs(initialCapital: string, feeRate: string, slippageBps: string, pendingEntryMaxWaitBars: string): string | null {
  if (toPositiveNumber(initialCapital) == null) return "Initial capital must be greater than zero.";
  if (toNonNegativeNumber(feeRate) == null) return "Fee rate must be zero or greater.";
  if (toNonNegativeNumber(slippageBps) == null) return "Slippage bps must be zero or greater.";
  if (toPositiveInteger(pendingEntryMaxWaitBars) == null) return "Pending max wait bars must be a positive integer.";
  return null;
}

function toPositiveNumber(value: string): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function toNonNegativeNumber(value: string): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function toPositiveInteger(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function defaultDateRange(): { startAt: string; endAt: string } {
  const end = new Date();
  end.setSeconds(0, 0);
  const start = new Date(end);
  start.setDate(start.getDate() - 30);
  return {
    endAt: toDateTimeLocal(end),
    startAt: toDateTimeLocal(start)
  };
}

function toDateTimeLocal(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function buildRunRequest({
  endAt,
  feeRate,
  historicalPendingEntriesEnabled,
  initialCapital,
  mode,
  pendingEntryMaxWaitBars,
  sameCandlePolicy,
  selectedPairs,
  selectedStrategyCodes,
  selectedTimeframes,
  slippageBps,
  startAt,
  testType
}: {
  endAt: string;
  feeRate: string;
  historicalPendingEntriesEnabled: boolean;
  initialCapital: string;
  mode: StrategyTestMode;
  pendingEntryMaxWaitBars: string;
  sameCandlePolicy: StrategyTestSameCandlePolicy;
  selectedPairs: MarketPairOption[];
  selectedStrategyCodes: string[];
  selectedTimeframes: string[];
  slippageBps: string;
  startAt: string;
  testType: StrategyTestType;
}): StrategyTestRunRequest {
  const params = testType === "historical_backtest"
    ? {
        historical_pending_entries_enabled: mode !== "discovery" && historicalPendingEntriesEnabled,
        pending_entry_max_wait_bars: toPositiveInteger(pendingEntryMaxWaitBars) ?? Number(DEFAULT_PENDING_ENTRY_MAX_WAIT_BARS)
      }
    : {};
  return {
    end_at: new Date(endAt).toISOString(),
    fee_rate: Number(feeRate),
    initial_capital: Number(initialCapital),
    mode,
    pairs: selectedPairs.map(toStrategyTestPair),
    params,
    same_candle_policy: sameCandlePolicy,
    slippage_bps: Number(slippageBps),
    start_at: new Date(startAt).toISOString(),
    strategies: selectedStrategyCodes,
    tags: [testType === "forward_virtual" ? "forward_virtual" : "backtest"],
    test_type: testType,
    timeframes: selectedTimeframes
  };
}

function toStrategyTestPair(pair: MarketPairOption): StrategyTestPair {
  return {
    exchange: pair.exchange,
    symbol: pair.symbol
  };
}

function errorMessage(error: unknown): string | null {
  return error instanceof Error ? error.message : null;
}

function ActiveRunNotice({
  activeRunState,
  cancelPending,
  onCancel,
  onOpenReport,
  onRefresh,
  run
}: {
  activeRunState: StrategyTestActiveRunResponse | null;
  cancelPending: boolean;
  onCancel: (runId: string) => void;
  onOpenReport: (runId: string) => void;
  onRefresh: () => void;
  run: StrategyTestRunResponse;
}) {
  const allowedActions = new Set(activeRunState?.allowed_actions ?? ["refresh"]);
  const stopping = cancelPending || (run.status === "stopping" && !activeRunState?.is_stale);
  return (
    <section aria-label="Active strategy test run" className="strategy-test-active-run">
      <div className="strategy-test-active-run-header">
        <strong>Active run {shortRunId(run.run_id)}</strong>
        <Badge tone={activeRunState?.is_stale ? "yellow" : "blue"}>{run.status}</Badge>
        {activeRunState?.is_stale ? <Badge tone="yellow">Stale active run</Badge> : null}
      </div>
      {activeRunState?.disabled_reason ? (
        <p className="strategy-test-active-run-reason">{activeRunState.disabled_reason}</p>
      ) : null}
      {run.test_type === "historical_backtest" && !activeRunState?.is_stale ? (
        <p className="strategy-test-active-run-reason">Run is receiving heartbeats. Large historical scenarios can stay on the same scenario for a while.</p>
      ) : null}
      <ActiveRunProgress run={run} />
      <dl className="strategy-test-active-run-meta">
        <div>
          <dt>Run ID</dt>
          <dd>{run.run_id}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{formatOptionalDate(run.created_at)}</dd>
        </div>
        <div>
          <dt>Started</dt>
          <dd>{formatOptionalDate(run.started_at)}</dd>
        </div>
      </dl>
      <div className="strategy-test-active-run-actions">
        <button className="secondary-action" onClick={onRefresh} type="button">
          <RefreshCw size={16} />
          Refresh active run
        </button>
        <button className="secondary-action" onClick={() => onOpenReport(run.run_id)} type="button">
          <BarChart3 size={16} />
          Open report
        </button>
        {allowedActions.has("cancel") ? (
          <button
            className="secondary-action"
            disabled={stopping}
            onClick={() => onCancel(run.run_id)}
            type="button"
          >
            <XCircle size={16} />
            {stopping ? "Stopping..." : "Cancel run"}
          </button>
        ) : null}
      </div>
    </section>
  );
}

function ActiveRunProgress({ run }: { run: StrategyTestRunResponse }) {
  const scenarioCompleted = runtimeNumber(run, "scenario_completed") ?? runSummaryNumber(run, "completed_scenarios") ?? 0;
  const scenarioTotal = runtimeNumber(run, "scenario_total") ?? requestedScenarioCount(run) ?? runSummaryNumber(run, "scenario_count") ?? 0;
  const barsProcessed = runtimeNumber(run, "bars_processed");
  const barsTotal = runtimeNumber(run, "bars_total");
  const barsPct = runtimeNumber(run, "bars_pct");
  const pendingArmed = runtimeNumber(run, "pending_armed") ?? runtimeNumber(run, "pending_entries_armed") ?? runSummaryNumber(run, "pending_armed") ?? 0;
  const filled = runtimeNumber(run, "filled") ?? runtimeNumber(run, "opened_trades") ?? runSummaryNumber(run, "filled") ?? 0;
  const noEntry = runtimeNumber(run, "no_entry") ?? runSummaryNumber(run, "no_entry") ?? 0;

  return (
    <section aria-label="Active run progress summary" className="strategy-test-active-progress">
      {activeProgressItem("Scenarios", scenarioTotal ? `${scenarioCompleted} / ${scenarioTotal}` : scenarioCompleted)}
      {activeProgressItem("Bars", formatBarsProgress(barsProcessed, barsTotal, barsPct))}
      {activeProgressItem("Throughput", formatBarsPerSecond(runtimeNumber(run, "bars_per_second")))}
      {activeProgressItem("ETA", formatSeconds(runtimeNumber(run, "eta_seconds")))}
      {activeProgressItem("Signals", runtimeNumber(run, "signals_seen") ?? runtimeNumber(run, "processed_signals") ?? runSummaryNumber(run, "signals_seen") ?? 0)}
      {activeProgressItem("Pending armed", pendingArmed)}
      {activeProgressItem("Pending entries", runtimeNumber(run, "pending_entries_count") ?? 0)}
      {activeProgressItem("No entry", noEntry)}
      {activeProgressItem("Filled", filled)}
      {activeProgressItem("Closed", runtimeNumber(run, "closed") ?? runtimeNumber(run, "closed_trades") ?? runSummaryNumber(run, "closed") ?? 0)}
    </section>
  );
}

function activeProgressItem(label: string, value: unknown) {
  return (
    <div className="strategy-test-active-progress-item" key={label}>
      <span>{label}</span>
      <strong>{formatDisplayValue(value)}</strong>
    </div>
  );
}

function shortRunId(runId: string): string {
  return runId.slice(0, 8);
}

function formatOptionalDate(value: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function runtimeNumber(run: StrategyTestRunResponse, key: string): number | null {
  const value = run.runtime_state[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function runSummaryNumber(run: StrategyTestRunResponse, key: keyof StrategyTestRunResponse["summary"]): number | null {
  const value = run.summary[key] ?? runtimePartialSummaryValue(run, String(key));
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function runtimePartialSummaryValue(run: StrategyTestRunResponse, key: string): unknown {
  const partialSummary = run.runtime_state.partial_summary;
  if (!partialSummary || typeof partialSummary !== "object" || Array.isArray(partialSummary)) return null;
  return (partialSummary as Record<string, unknown>)[key];
}

function requestedScenarioCount(run: StrategyTestRunResponse): number | null {
  const value = run.requested_matrix.scenario_count;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatBarsProgress(processed: number | null, total: number | null, pct: number | null): string {
  if (processed == null && total == null) return "-";
  const processedValue = processed ?? 0;
  const totalValue = total ?? 0;
  const computedPct = pct ?? (totalValue > 0 ? (processedValue / totalValue) * 100 : null);
  const percent = computedPct == null ? null : formatNumber(computedPct);
  return percent == null ? `${formatActiveNumber(processedValue)} / ${formatActiveNumber(totalValue)}` : `${formatActiveNumber(processedValue)} / ${formatActiveNumber(totalValue)} (${percent}%)`;
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

function formatDisplayValue(value: unknown): string {
  if (typeof value === "number") return formatActiveNumber(value);
  if (typeof value === "string" && value.trim()) return value;
  return "-";
}

function formatActiveNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : formatNumber(value);
}

function formatInteger(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return "0";
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2).replace(/0+$/u, "").replace(/\.$/u, "");
}
