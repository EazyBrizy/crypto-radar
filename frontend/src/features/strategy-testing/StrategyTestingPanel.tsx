"use client";

import { Play, RefreshCw } from "lucide-react";
import { useMemo, useState, type FormEvent, type ReactNode } from "react";

import { Badge } from "@/components/Badge";
import type { MarketPairOption, StrategyConfig } from "@/features/server-state/types";
import {
  useRunStrategyTest,
  useStrategyTestReport,
  useStrategyTestRuns
} from "@/hooks/use-radar-queries";
import { StrategyTestReport } from "./StrategyTestReport";
import { StrategyTestRunsTable } from "./StrategyTestRunsTable";
import type {
  StrategyTestMode,
  StrategyTestPair,
  StrategyTestRunRequest,
  StrategyTestRunStatus,
  StrategyTestSameCandlePolicy,
  StrategyTestSignalSelectionPolicy
} from "./types";

interface StrategyTestingPanelProps {
  availablePairs: MarketPairOption[];
  strategyConfigs: StrategyConfig[];
}

const STRATEGY_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];
const DEFAULT_SELECTED_TIMEFRAMES = ["1m", "5m", "15m"];
const DEFAULT_MODE: StrategyTestMode = "research_virtual";
const DEFAULT_SAME_CANDLE_POLICY: StrategyTestSameCandlePolicy = "stop_first";
const DEFAULT_SIGNAL_SELECTION_POLICY: StrategyTestSignalSelectionPolicy = "all_non_overlapping";
const HISTORICAL_BACKTEST_TOOLTIP = "Historical backtest uses closed candles and does not affect live radar/trades.";

const MODE_LABELS: Record<StrategyTestMode, string> = {
  discovery: "Исследование идей",
  research_virtual: "Исторический virtual backtest",
  production_like: "Production-like backtest"
};

const POLICY_LABELS: Record<StrategyTestSameCandlePolicy, string> = {
  ignore_ambiguous: "Ignore ambiguous",
  stop_first: "Stop first",
  target_first: "Target first"
};
const SIGNAL_SELECTION_LABELS: Record<StrategyTestSignalSelectionPolicy, string> = {
  all_non_overlapping: "All non-overlapping",
  all_signals: "All signals",
  first_actionable: "First actionable",
  highest_score: "Highest score"
};
const ACTIVE_RUN_STATUSES = new Set<StrategyTestRunStatus>(["queued", "running"]);
const STRATEGY_TEST_RUN_POLL_MS = 2_500;

export function StrategyTestingPanel({
  availablePairs,
  strategyConfigs
}: StrategyTestingPanelProps) {
  const dateDefaults = useMemo(() => defaultDateRange(), []);
  const strategyOptions = useMemo(() => enabledStrategyOptions(strategyConfigs), [strategyConfigs]);
  const pairOptions = useMemo(() => availablePairs.slice(0, 50), [availablePairs]);
  const timeframeOptions = useMemo(() => availableTimeframes(strategyOptions), [strategyOptions]);
  const runsQuery = useStrategyTestRuns({ limit: 25 }, { refetchInterval: STRATEGY_TEST_RUN_POLL_MS });
  const runMutation = useRunStrategyTest();
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
  const [signalSelectionPolicy, setSignalSelectionPolicy] = useState<StrategyTestSignalSelectionPolicy>(DEFAULT_SIGNAL_SELECTION_POLICY);
  const [maxConcurrentPositions, setMaxConcurrentPositions] = useState("10");
  const [maxPositionsPerSymbol, setMaxPositionsPerSymbol] = useState("1");
  const [cooldownBarsAfterClose, setCooldownBarsAfterClose] = useState("0");
  const [allowOppositeSignalFlip, setAllowOppositeSignalFlip] = useState(false);
  const [maxBarsInTrade, setMaxBarsInTrade] = useState("48");
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
  const advancedError = validateAdvancedInputs(maxConcurrentPositions, maxPositionsPerSymbol, cooldownBarsAfterClose, maxBarsInTrade);
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
  const hasActiveRun =
    runs.some((run) => isActiveStrategyTestRun(run.status)) ||
    (mutationRunIsMissingFromList && isActiveStrategyTestRun(runMutation.data?.status));
  const canRun = scenarioEstimate > 0 && !dateError && !numberError && !advancedError && !runMutation.isPending && !hasActiveRun;
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
        advancedError ??
        (hasActiveRun ? "A strategy test run is already in progress." : "Select at least one strategy, pair, and timeframe.")
      );
      return;
    }

    try {
      const response = await runMutation.mutateAsync(buildRunRequest({
        endAt,
        feeRate,
        initialCapital,
        mode,
        advancedParams: {
          allowOppositeSignalFlip,
          cooldownBarsAfterClose,
          maxBarsInTrade,
          maxConcurrentPositions,
          maxPositionsPerSymbol,
          signalSelectionPolicy
        },
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

  return (
    <form className="strategy-testing-panel" onSubmit={handleRun}>
      <div className="strategy-test-status-strip">
        <Badge tone="blue">{scenarioEstimate} scenarios</Badge>
        <Badge tone="purple">{runs.length} recent runs</Badge>
        {runsQuery.isLoading ? <Badge tone="yellow">Loading runs</Badge> : null}
        {hasActiveRun ? <Badge tone="yellow">Run in progress</Badge> : null}
      </div>

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

      <div className="strategy-test-controls strategy-test-advanced-controls">
        <label className="strategy-test-field">
          <span>Signal selection</span>
          <select
            onChange={(event) => setSignalSelectionPolicy(event.target.value as StrategyTestSignalSelectionPolicy)}
            value={signalSelectionPolicy}
          >
            {Object.entries(SIGNAL_SELECTION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label className="strategy-test-field">
          <span>Max concurrent positions</span>
          <input inputMode="numeric" min="1" onChange={(event) => setMaxConcurrentPositions(event.target.value)} step="1" type="number" value={maxConcurrentPositions} />
        </label>
        <label className="strategy-test-field">
          <span>Max positions per symbol</span>
          <input inputMode="numeric" min="1" onChange={(event) => setMaxPositionsPerSymbol(event.target.value)} step="1" type="number" value={maxPositionsPerSymbol} />
        </label>
        <label className="strategy-test-field">
          <span>Cooldown bars after close</span>
          <input inputMode="numeric" min="0" onChange={(event) => setCooldownBarsAfterClose(event.target.value)} step="1" type="number" value={cooldownBarsAfterClose} />
        </label>
        <label className="strategy-test-field">
          <span>Max bars in trade</span>
          <input inputMode="numeric" min="1" onChange={(event) => setMaxBarsInTrade(event.target.value)} step="1" type="number" value={maxBarsInTrade} />
        </label>
        <label className="strategy-test-check-option compact">
          <input
            checked={allowOppositeSignalFlip}
            onChange={(event) => setAllowOppositeSignalFlip(event.target.checked)}
            type="checkbox"
          />
          <span><strong>Allow opposite signal flip</strong></span>
        </label>
      </div>

      <div className="strategy-test-mode-row" aria-label="Strategy test mode">
        {(Object.keys(MODE_LABELS) as StrategyTestMode[]).map((option) => (
          <button
            className={mode === option ? "active" : ""}
            key={option}
            onClick={() => setMode(option)}
            title={option === "research_virtual" ? HISTORICAL_BACKTEST_TOOLTIP : undefined}
            type="button"
          >
            {MODE_LABELS[option]}
          </button>
        ))}
      </div>

      {dateError || numberError || advancedError || formError || apiError ? (
        <p className="form-error">{formError ?? dateError ?? numberError ?? advancedError ?? apiError}</p>
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

function validateAdvancedInputs(
  maxConcurrentPositions: string,
  maxPositionsPerSymbol: string,
  cooldownBarsAfterClose: string,
  maxBarsInTrade: string
): string | null {
  if (toPositiveInteger(maxConcurrentPositions) == null) return "Max concurrent positions must be greater than zero.";
  if (toPositiveInteger(maxPositionsPerSymbol) == null) return "Max positions per symbol must be greater than zero.";
  if (toNonNegativeInteger(cooldownBarsAfterClose) == null) return "Cooldown bars after close must be zero or greater.";
  if (toPositiveInteger(maxBarsInTrade) == null) return "Max bars in trade must be greater than zero.";
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

function toNonNegativeInteger(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
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
  advancedParams,
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
  advancedParams: {
    allowOppositeSignalFlip: boolean;
    cooldownBarsAfterClose: string;
    maxBarsInTrade: string;
    maxConcurrentPositions: string;
    maxPositionsPerSymbol: string;
    signalSelectionPolicy: StrategyTestSignalSelectionPolicy;
  };
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
    params: {
      allow_opposite_signal_flip: advancedParams.allowOppositeSignalFlip,
      cooldown_bars_after_close: Number(advancedParams.cooldownBarsAfterClose),
      max_bars_in_trade: Number(advancedParams.maxBarsInTrade),
      max_concurrent_positions: Number(advancedParams.maxConcurrentPositions),
      max_positions_per_symbol: Number(advancedParams.maxPositionsPerSymbol),
      signal_selection_policy: advancedParams.signalSelectionPolicy
    },
    same_candle_policy: sameCandlePolicy,
    slippage_bps: Number(slippageBps),
    start_at: new Date(startAt).toISOString(),
    strategies: selectedStrategyCodes,
    tags: ["backtest"],
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
