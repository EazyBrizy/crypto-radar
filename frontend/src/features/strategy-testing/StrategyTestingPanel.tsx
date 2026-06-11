"use client";

import { BarChart3, Play, RefreshCw, XCircle } from "lucide-react";
import { useMemo, useState, type FormEvent, type ReactNode } from "react";

import { Badge } from "@/components/Badge";
import type { MarketPairOption, StrategyConfig } from "@/features/server-state/types";
import {
  useCancelStrategyTestRun,
  useRunStrategyTest,
  useStrategyTestActiveRun,
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
  StrategyTestSameCandlePolicy
} from "./types";

interface StrategyTestingPanelProps {
  availablePairs: MarketPairOption[];
  strategyConfigs: StrategyConfig[];
}

const STRATEGY_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];
const DEFAULT_SELECTED_TIMEFRAMES = ["1m", "5m", "15m"];
const DEFAULT_MODE: StrategyTestMode = "research_virtual";
const DEFAULT_SAME_CANDLE_POLICY: StrategyTestSameCandlePolicy = "stop_first";

const MODE_LABELS: Record<StrategyTestMode, string> = {
  discovery: "Discovery",
  research_virtual: "Research virtual",
  production_like: "Production-like"
};

const POLICY_LABELS: Record<StrategyTestSameCandlePolicy, string> = {
  ignore_ambiguous: "Ignore ambiguous",
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
  const [selectedStrategyCodes, setSelectedStrategyCodes] = useState<string[] | null>(null);
  const [selectedPairIds, setSelectedPairIds] = useState<string[] | null>(null);
  const [selectedTimeframes, setSelectedTimeframes] = useState<string[] | null>(null);
  const [mode, setMode] = useState<StrategyTestMode>(DEFAULT_MODE);
  const [startAt, setStartAt] = useState(dateDefaults.startAt);
  const [endAt, setEndAt] = useState(dateDefaults.endAt);
  const [initialCapital, setInitialCapital] = useState("1000");
  const [feeRate, setFeeRate] = useState("0.001");
  const [slippageBps, setSlippageBps] = useState("0");
  const [sameCandlePolicy, setSameCandlePolicy] = useState<StrategyTestSameCandlePolicy>(DEFAULT_SAME_CANDLE_POLICY);
  const [formError, setFormError] = useState<string | null>(null);
  const [selectedReportRunId, setSelectedReportRunId] = useState<string | null>(null);
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
  const numberError = validateNumericInputs(initialCapital, feeRate, slippageBps);
  const scenarioEstimate = effectiveStrategyCodes.length * selectedPairs.length * validTimeframes.length;
  const runs = runsQuery.data ?? [];
  const selectedRun = runs.find((run) => run.run_id === selectedReportRunId) ?? null;
  const mutationSelectedRun = runMutation.data?.run_id === selectedReportRunId ? runMutation.data : null;
  const selectedRunForReport = selectedRun ?? mutationSelectedRun;
  const selectedRunStatus = selectedRunForReport?.status ?? null;
  const selectedRunIsActive = isActiveStrategyTestRun(selectedRunStatus);
  const mutationRunIsMissingFromList = Boolean(
    runMutation.data && !runs.some((run) => run.run_id === runMutation.data?.run_id)
  );
  const recentActiveRun = runs.find((run) => isActiveStrategyTestRun(run.status)) ?? null;
  const fallbackActiveRun = recentActiveRun ??
    (mutationRunIsMissingFromList && isActiveStrategyTestRun(runMutation.data?.status) ? runMutation.data ?? null : null);
  const activeRunState = activeRunQuery.data ?? null;
  const activeRun = activeRunState?.active_run ?? fallbackActiveRun;
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
    enabled: Boolean(selectedReportRunId),
    refetchInterval: selectedRunIsActive ? STRATEGY_TEST_RUN_POLL_MS : false
  });
  const apiError = errorMessage(runMutation.error);

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

    try {
      const response = await runMutation.mutateAsync(buildRunRequest({
        endAt,
        feeRate,
        initialCapital,
        mode,
        sameCandlePolicy,
        selectedPairs,
        selectedStrategyCodes: effectiveStrategyCodes,
        selectedTimeframes: validTimeframes,
        slippageBps,
        startAt
      }));
      setSelectedReportRunId(response.run_id);
    } catch (error) {
      setFormError(errorMessage(error) ?? "Unable to start strategy test.");
    }
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

  return (
    <form className="strategy-testing-panel" onSubmit={handleRun}>
      <div className="strategy-test-status-strip">
        <Badge tone="blue">{scenarioEstimate} scenarios</Badge>
        <Badge tone="purple">{runs.length} recent runs</Badge>
        {runsQuery.isLoading ? <Badge tone="yellow">Loading runs</Badge> : null}
        {activeRunQuery.isLoading ? <Badge tone="yellow">Loading active run</Badge> : null}
        {showRunInProgress ? <Badge tone="yellow">Run in progress</Badge> : null}
        {activeRunIsStale ? <Badge tone="yellow">Stale active run</Badge> : null}
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
            className={mode === option ? "active" : ""}
            key={option}
            onClick={() => setMode(option)}
            type="button"
          >
            {MODE_LABELS[option]}
          </button>
        ))}
      </div>

      {dateError || numberError || formError || apiError ? (
        <p className="form-error">{formError ?? dateError ?? numberError ?? apiError}</p>
      ) : null}

      <div className="strategy-test-actions">
        <button className="primary-action" disabled={!canRun} type="submit">
          {runMutation.isPending ? <RefreshCw size={16} /> : <Play size={16} />}
          Run strategy test
        </button>
      </div>

      <StrategyTestRunsTable
        onOpenReport={(run) => setSelectedReportRunId(run.run_id)}
        runs={runs}
        selectedRunId={selectedReportRunId}
      />

      {selectedReportRunId ? (
        <StrategyTestReport
          error={reportQuery.error instanceof Error ? reportQuery.error : null}
          loading={reportQuery.isLoading}
          onClose={() => setSelectedReportRunId(null)}
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

function validateDateRange(startAt: string, endAt: string): string | null {
  if (!startAt || !endAt) return "Select a start and end date.";
  const start = new Date(startAt);
  const end = new Date(endAt);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "Date range is invalid.";
  if (end <= start) return "End date must be after start date.";
  return null;
}

function validateNumericInputs(initialCapital: string, feeRate: string, slippageBps: string): string | null {
  if (toPositiveNumber(initialCapital) == null) return "Initial capital must be greater than zero.";
  if (toNonNegativeNumber(feeRate) == null) return "Fee rate must be zero or greater.";
  if (toNonNegativeNumber(slippageBps) == null) return "Slippage bps must be zero or greater.";
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
  initialCapital,
  mode,
  sameCandlePolicy,
  selectedPairs,
  selectedStrategyCodes,
  selectedTimeframes,
  slippageBps,
  startAt
}: {
  endAt: string;
  feeRate: string;
  initialCapital: string;
  mode: StrategyTestMode;
  sameCandlePolicy: StrategyTestSameCandlePolicy;
  selectedPairs: MarketPairOption[];
  selectedStrategyCodes: string[];
  selectedTimeframes: string[];
  slippageBps: string;
  startAt: string;
}): StrategyTestRunRequest {
  return {
    end_at: new Date(endAt).toISOString(),
    fee_rate: Number(feeRate),
    initial_capital: Number(initialCapital),
    mode,
    pairs: selectedPairs.map(toStrategyTestPair),
    params: {},
    same_candle_policy: sameCandlePolicy,
    slippage_bps: Number(slippageBps),
    start_at: new Date(startAt).toISOString(),
    strategies: selectedStrategyCodes,
    tags: ["backtest"],
    test_type: "historical_backtest",
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
            disabled={cancelPending}
            onClick={() => onCancel(run.run_id)}
            type="button"
          >
            <XCircle size={16} />
            Cancel run
          </button>
        ) : null}
      </div>
    </section>
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
