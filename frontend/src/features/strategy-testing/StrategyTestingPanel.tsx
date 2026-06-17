"use client";

import { AlertTriangle, BarChart3, FlaskConical, Play, RadioTower, RefreshCw, RotateCcw, XCircle, Zap } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";

import { Badge } from "@/components/Badge";
import type { MarketPairOption, StrategyConfig } from "@/features/server-state/types";
import {
  useCancelStrategyTestRun,
  usePublishStrategyTestCalibration,
  useRunStrategyTest,
  useStrategyTestActiveRun,
  useStrategyTestEstimate,
  useStrategyTestRun,
  useStrategyTestReport,
  useStrategyTestRuns
} from "@/hooks/use-radar-queries";
import { StrategyTestReport } from "./StrategyTestReport";
import { StrategyTestRunsTable } from "./StrategyTestRunsTable";
import {
  clearStrategyTestForm,
  readStrategyTestForm,
  saveStrategyTestForm,
  strategyTestFormStorageKey
} from "./strategy-test-form-storage";
import type {
  StrategyTestActiveRunResponse,
  StrategyTestEstimateResponse,
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
const LARGE_MATRIX_WARNING_SCENARIO_COUNT = 100;
const MATRIX_SELECTION_ERROR = "Select at least one strategy, pair, and timeframe.";

export function StrategyTestingPanel({
  availablePairs,
  strategyConfigs
}: StrategyTestingPanelProps) {
  const dateDefaults = useMemo(() => defaultDateRange(), []);
  const strategyOptions = useMemo(() => enabledStrategyOptions(strategyConfigs), [strategyConfigs]);
  const pairOptions = useMemo(() => availablePairs, [availablePairs]);
  const timeframeOptions = useMemo(() => availableTimeframes(strategyOptions), [strategyOptions]);
  const storageUserId = useMemo(() => firstConfiguredUserId(strategyConfigs), [strategyConfigs]);
  const formStorageKey = useMemo(() => strategyTestFormStorageKey(storageUserId), [storageUserId]);
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
  const [pairFilter, setPairFilter] = useState("");
  const [selectedReportRunId, setSelectedReportRunId] = useState<string | null>(null);
  const [largeRunConfirmation, setLargeRunConfirmation] = useState<{ confirmed: boolean; key: string | null }>({
    confirmed: false,
    key: null
  });
  const [formStorageHydrated, setFormStorageHydrated] = useState(false);
  const [storageResetVersion, setStorageResetVersion] = useState(0);
  const skipNextPersistRef = useRef(false);
  const defaultStrategySelection = useMemo(() => defaultStrategyCodes(strategyOptions), [strategyOptions]);
  const defaultPairSelection = useMemo(() => defaultPairIds(pairOptions), [pairOptions]);
  const defaultTimeframeSelection = useMemo(() => defaultTimeframes(timeframeOptions), [timeframeOptions]);
  const effectiveStrategyCodes = selectedStrategyCodes ?? defaultStrategySelection;
  const effectivePairIds = selectedPairIds ?? defaultPairSelection;
  const effectiveTimeframes = selectedTimeframes ?? defaultTimeframeSelection;
  const strategyOptionCodes = useMemo(() => strategyOptions.map((strategy) => strategy.strategy_code), [strategyOptions]);
  const pairOptionIds = useMemo(() => pairOptions.map(pairKey), [pairOptions]);
  const storableStrategyCodes = useMemo(
    () => filterKnownValues(effectiveStrategyCodes, strategyOptionCodes),
    [effectiveStrategyCodes, strategyOptionCodes]
  );
  const storablePairIds = useMemo(
    () => filterKnownValues(effectivePairIds, pairOptionIds),
    [effectivePairIds, pairOptionIds]
  );
  const visiblePairOptions = useMemo(() => filterPairOptions(pairOptions, pairFilter), [pairFilter, pairOptions]);
  const visiblePairIds = useMemo(() => visiblePairOptions.map(pairKey), [visiblePairOptions]);

  const selectedPairs = useMemo(
    () => pairOptions.filter((pair) => effectivePairIds.includes(pairKey(pair))),
    [effectivePairIds, pairOptions]
  );
  const validTimeframes = useMemo(
    () => effectiveTimeframes.filter((timeframe) => timeframeOptions.includes(timeframe)),
    [effectiveTimeframes, timeframeOptions]
  );
  const selectedStrategyCount = storableStrategyCodes.length;
  const selectedPairCount = selectedPairs.length;
  const selectedTimeframeCount = validTimeframes.length;
  const localScenarioCount = selectedStrategyCount * selectedPairCount * selectedTimeframeCount;
  const matrixSelectionError = localScenarioCount <= 0 ? MATRIX_SELECTION_ERROR : null;
  const pairFilterIsActive = pairFilter.trim().length > 0;
  const showLargeMatrixWarning = localScenarioCount >= LARGE_MATRIX_WARNING_SCENARIO_COUNT;

  /* eslint-disable react-hooks/set-state-in-effect -- Browser-only localStorage hydration has to update form state after mount. */
  useEffect(() => {
    skipNextPersistRef.current = true;
    const storedForm = readStrategyTestForm(formStorageKey);
    if (!storedForm) {
      setSelectedStrategyCodes(null);
      setSelectedPairIds(null);
      setSelectedTimeframes(null);
      setMode(DEFAULT_MODE);
      setTestType(DEFAULT_TEST_TYPE);
      setStartAt(dateDefaults.startAt);
      setEndAt(dateDefaults.endAt);
      setInitialCapital("1000");
      setFeeRate("0.001");
      setSlippageBps("0");
      setSameCandlePolicy(DEFAULT_SAME_CANDLE_POLICY);
      setHistoricalPendingEntriesEnabled(true);
      setPendingEntryMaxWaitBars(DEFAULT_PENDING_ENTRY_MAX_WAIT_BARS);
      setFormStorageHydrated(true);
      return;
    }

    setSelectedStrategyCodes(sanitizeStoredSelection(
      storedForm.selectedStrategyCodes,
      strategyOptionCodes,
      defaultStrategySelection
    ));
    setSelectedPairIds(sanitizeStoredSelection(
      storedForm.selectedPairIds,
      pairOptionIds,
      defaultPairSelection
    ));
    setSelectedTimeframes(sanitizeStoredSelection(
      storedForm.selectedTimeframes,
      timeframeOptions,
      defaultTimeframeSelection
    ));
    setMode(storedForm.mode ?? DEFAULT_MODE);
    setTestType(storedForm.testType ?? DEFAULT_TEST_TYPE);
    setStartAt(storedForm.startAt ?? dateDefaults.startAt);
    setEndAt(storedForm.endAt ?? dateDefaults.endAt);
    setInitialCapital(storedForm.initialCapital ?? "1000");
    setFeeRate(storedForm.feeRate ?? "0.001");
    setSlippageBps(storedForm.slippageBps ?? "0");
    setSameCandlePolicy(storedForm.sameCandlePolicy ?? DEFAULT_SAME_CANDLE_POLICY);
    setHistoricalPendingEntriesEnabled(storedForm.historicalPendingEntriesEnabled ?? true);
    setPendingEntryMaxWaitBars(storedForm.pendingEntryMaxWaitBars ?? DEFAULT_PENDING_ENTRY_MAX_WAIT_BARS);
    setFormStorageHydrated(true);
  }, [
    dateDefaults.endAt,
    dateDefaults.startAt,
    defaultPairSelection,
    defaultStrategySelection,
    defaultTimeframeSelection,
    formStorageKey,
    pairOptionIds,
    strategyOptionCodes,
    timeframeOptions
  ]);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    if (!formStorageHydrated) return;
    if (skipNextPersistRef.current) {
      skipNextPersistRef.current = false;
      return;
    }

    saveStrategyTestForm(formStorageKey, {
      endAt,
      feeRate,
      historicalPendingEntriesEnabled,
      initialCapital,
      mode,
      pendingEntryMaxWaitBars,
      sameCandlePolicy,
      selectedPairIds: storablePairIds,
      selectedStrategyCodes: storableStrategyCodes,
      selectedTimeframes: validTimeframes,
      slippageBps,
      startAt,
      testType
    });
  }, [
    endAt,
    feeRate,
    formStorageHydrated,
    formStorageKey,
    historicalPendingEntriesEnabled,
    initialCapital,
    mode,
    pendingEntryMaxWaitBars,
    sameCandlePolicy,
    selectedPairIds,
    selectedStrategyCodes,
    selectedTimeframes,
    slippageBps,
    startAt,
    storablePairIds,
    storableStrategyCodes,
    storageResetVersion,
    testType,
    validTimeframes
  ]);
  const dateError = validateDateRange(startAt, endAt);
  const numberError = validateNumericInputs(initialCapital, feeRate, slippageBps, pendingEntryMaxWaitBars, testType);
  const estimateRequest = useMemo(() => {
    if (localScenarioCount <= 0 || dateError || numberError) return null;
    return buildRunRequest({
      endAt,
      feeRate,
      historicalPendingEntriesEnabled,
      initialCapital,
      mode,
      pendingEntryMaxWaitBars,
      sameCandlePolicy,
      selectedPairs,
      selectedStrategyCodes: effectiveStrategyCodes,
      selectedTimeframes: validTimeframes,
      slippageBps,
      startAt,
      testType
    });
  }, [
    dateError,
    effectiveStrategyCodes,
    endAt,
    feeRate,
    historicalPendingEntriesEnabled,
    initialCapital,
    localScenarioCount,
    mode,
    numberError,
    pendingEntryMaxWaitBars,
    sameCandlePolicy,
    selectedPairs,
    slippageBps,
    startAt,
    testType,
    validTimeframes
  ]);
  const estimateQuery = useStrategyTestEstimate(estimateRequest, {
    enabled: Boolean(estimateRequest && testType === "historical_backtest")
  });
  const runEstimate = testType === "historical_backtest" && estimateRequest ? estimateQuery.data ?? null : null;
  const scenarioEstimate = runEstimate?.scenario_count ?? localScenarioCount;
  const requiresLargeRunConfirmation = runEstimate?.size_level === "large";
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
  const canRun = localScenarioCount > 0 &&
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
        (activeRunBlocksRun ? "A strategy test run is already in progress." : MATRIX_SELECTION_ERROR)
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

  function handleResetForm() {
    skipNextPersistRef.current = true;
    clearStrategyTestForm(formStorageKey);
    setStorageResetVersion((current) => current + 1);
    setFormError(null);
    setLargeRunConfirmation({ confirmed: false, key: null });
    setSelectedStrategyCodes(defaultStrategySelection);
    setSelectedPairIds(defaultPairSelection);
    setSelectedTimeframes(defaultTimeframeSelection);
    setMode(DEFAULT_MODE);
    setTestType(DEFAULT_TEST_TYPE);
    setStartAt(dateDefaults.startAt);
    setEndAt(dateDefaults.endAt);
    setInitialCapital("1000");
    setFeeRate("0.001");
    setSlippageBps("0");
    setSameCandlePolicy(DEFAULT_SAME_CANDLE_POLICY);
    setHistoricalPendingEntriesEnabled(true);
    setPendingEntryMaxWaitBars(DEFAULT_PENDING_ENTRY_MAX_WAIT_BARS);
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

  function updateStrategySelection(values: string[]) {
    setFormError(null);
    setSelectedStrategyCodes(values);
  }

  function updatePairSelection(values: string[]) {
    setFormError(null);
    setSelectedPairIds(values);
  }

  function updateTimeframeSelection(values: string[]) {
    setFormError(null);
    setSelectedTimeframes(values);
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
        <SelectionGroup
          actions={(
            <>
              <button onClick={() => updateStrategySelection(strategyOptionCodes)} type="button">
                Select all strategies
              </button>
              <button onClick={() => updateStrategySelection([])} type="button">
                Clear strategies
              </button>
            </>
          )}
          meta={`${selectedStrategyCount} / ${strategyOptions.length} selected`}
          title="Strategies"
        >
          {strategyOptions.length ? strategyOptions.map((strategy) => (
            <label className="strategy-test-check-option" key={strategy.strategy_code}>
              <input
                checked={effectiveStrategyCodes.includes(strategy.strategy_code)}
                onChange={() => {
                  setFormError(null);
                  setSelectedStrategyCodes((current) =>
                    toggleValue(current ?? defaultStrategySelection, strategy.strategy_code)
                  );
                }}
                type="checkbox"
              />
              <span>
                <strong>{strategy.strategy_name}</strong>
                <small>{strategy.strategy_code}</small>
              </span>
            </label>
          )) : <div className="empty-state compact-empty">No enabled strategies</div>}
        </SelectionGroup>

        <SelectionGroup
          actions={(
            <>
              <button onClick={() => updatePairSelection(pairOptionIds)} type="button">
                Select all pairs
              </button>
              <button onClick={() => updatePairSelection([])} type="button">
                Clear pairs
              </button>
              {pairFilterIsActive ? (
                <button
                  disabled={!visiblePairIds.length}
                  onClick={() => updatePairSelection(visiblePairIds)}
                  type="button"
                >
                  Select visible pairs
                </button>
              ) : null}
            </>
          )}
          filter={(
            <label className="strategy-test-pair-filter">
              <span>Filter pairs</span>
              <input
                aria-label="Filter pairs"
                onChange={(event) => setPairFilter(event.target.value)}
                placeholder="Symbol, base, quote, exchange"
                type="search"
                value={pairFilter}
              />
            </label>
          )}
          meta={`${selectedPairCount} / ${pairOptions.length} selected`}
          title="Pairs"
        >
          {pairOptions.length && !visiblePairOptions.length ? (
            <div className="empty-state compact-empty">No pairs match the filter</div>
          ) : null}
          {visiblePairOptions.length ? visiblePairOptions.map((pair) => (
            <label className="strategy-test-check-option compact" key={pairKey(pair)}>
              <input
                checked={effectivePairIds.includes(pairKey(pair))}
                onChange={() => {
                  setFormError(null);
                  setSelectedPairIds((current) =>
                    toggleValue(current ?? defaultPairSelection, pairKey(pair))
                  );
                }}
                type="checkbox"
              />
              <span>
                <strong>{pair.exchange}:{pair.symbol}</strong>
                <small>{pair.base_asset}/{pair.quote_asset}</small>
              </span>
            </label>
          )) : null}
          {!pairOptions.length ? <div className="empty-state compact-empty">No pairs</div> : null}
        </SelectionGroup>

        <SelectionGroup
          actions={(
            <>
              <button onClick={() => updateTimeframeSelection(timeframeOptions)} type="button">
                Select all timeframes
              </button>
              <button onClick={() => updateTimeframeSelection([])} type="button">
                Clear timeframes
              </button>
            </>
          )}
          meta={`${selectedTimeframeCount} / ${timeframeOptions.length} selected`}
          title="Timeframes"
        >
          <div className="strategy-test-timeframe-grid">
            {timeframeOptions.map((timeframe) => (
              <label className="strategy-test-check-option compact" key={timeframe}>
                <input
                  checked={effectiveTimeframes.includes(timeframe)}
                  onChange={() => {
                    setFormError(null);
                    setSelectedTimeframes((current) =>
                      toggleValue(current ?? defaultTimeframeSelection, timeframe)
                    );
                  }}
                  type="checkbox"
                />
                <span><strong>{timeframe}</strong></span>
              </label>
            ))}
          </div>
        </SelectionGroup>
      </div>

      <div className="strategy-test-matrix-summary">
        <Badge tone={showLargeMatrixWarning ? "yellow" : "blue"}>
          {`${formatInteger(localScenarioCount)} scenarios selected`}
        </Badge>
        {showLargeMatrixWarning ? (
          <span>Large matrix: worker will process scenarios gradually. Data will be backfilled and cached.</span>
        ) : null}
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
      {testType === "forward_virtual" ? (
        <p className="strategy-test-type-hint">Forward virtual needs scanner market data; with scanner disabled it will wait for ticks.</p>
      ) : null}

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

      <RunEstimatePanel
        confirmed={largeRunConfirmed}
        estimate={runEstimate}
        loading={testType === "historical_backtest" && (estimateQuery.isLoading || estimateQuery.isFetching)}
        scenarioCount={scenarioEstimate}
      />

      {dateError || numberError || matrixSelectionError || formError || apiError ? (
        <p className="form-error">{formError ?? dateError ?? numberError ?? matrixSelectionError ?? apiError}</p>
      ) : null}

      <div className="strategy-test-actions">
        <button className="secondary-action" onClick={handleResetForm} type="button">
          <RotateCcw size={16} />
          Reset form
        </button>
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

function SelectionGroup({
  actions,
  children,
  filter,
  meta,
  title
}: {
  actions?: ReactNode;
  children: ReactNode;
  filter?: ReactNode;
  meta?: ReactNode;
  title: string;
}) {
  return (
    <section aria-label={title} className="strategy-test-selection-group" role="region">
      <div className="strategy-test-selection-head">
        <div>
          <h4>{title}</h4>
          {meta ? <span>{meta}</span> : null}
        </div>
        {actions ? <div className="strategy-test-selection-actions">{actions}</div> : null}
      </div>
      {filter ? <div className="strategy-test-selection-filter">{filter}</div> : null}
      <div className="strategy-test-selection-list">{children}</div>
    </section>
  );
}

function RunEstimatePanel({
  confirmed,
  estimate,
  loading,
  scenarioCount
}: {
  confirmed: boolean;
  estimate: StrategyTestEstimateResponse | null;
  loading: boolean;
  scenarioCount: number;
}) {
  const level = estimate?.size_level ?? "small";
  const tone = level === "large" ? "red" : level === "medium" ? "yellow" : "green";
  const scenarios = estimate?.scenarios ?? [];
  const warnings = estimate?.warnings ?? [];
  return (
    <section
      aria-label="Strategy test run estimate"
      className={`strategy-test-estimate strategy-test-estimate-${level}`}
    >
      <div className="strategy-test-estimate-head">
        <div>
          <strong>Run estimate</strong>
          <span>{loading ? "Loading market-data estimate..." : estimateWarningText(level, warnings.length)}</span>
        </div>
        <Badge tone={tone}>{runLevelLabel(level)}</Badge>
      </div>
      <div className="strategy-test-estimate-grid">
        {estimateItem("Scenario count", estimate?.scenario_count ?? scenarioCount)}
        {estimateItem("Bars / scenario", formatBarsPerScenario(estimate?.average_bars_per_scenario ?? null))}
        {estimateItem("Total bars", formatTotalBars(estimate?.total_bars ?? null))}
        {estimateItem("Scenario bars", formatScenarioBars(scenarios))}
      </div>
      {warnings.length ? (
        <div className="strategy-test-estimate-warnings" aria-label="Estimate validation warnings">
          {warnings.map((warning) => {
            const warningTone = estimateWarningTone(warning.code);
            return (
              <div
                className={`strategy-test-estimate-warning strategy-test-estimate-warning-${warningTone}`}
                key={`${warning.code}:${warning.exchange}:${warning.symbol}:${warning.timeframe}`}
              >
                <AlertTriangle size={16} />
                <span>{warning.message}</span>
                {warning.timeframe ? <Badge tone="yellow">{warning.timeframe}</Badge> : null}
              </div>
            );
          })}
        </div>
      ) : null}
      {level === "large" ? (
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

function runLevelLabel(level: RunEstimateLevel): string {
  if (level === "large") return "Large run";
  if (level === "medium") return "Medium run";
  return "Small run";
}

function estimateWarningText(level: RunEstimateLevel, warningsCount: number): string {
  if (warningsCount > 0) return "Review backend market-data warnings before launch.";
  if (level === "large") return "Review before launch; confirmation is required.";
  if (level === "medium") return "Reasonable for research, but watch active progress.";
  return "Fast enough for a quick validation pass.";
}

function estimateWarningTone(code: StrategyTestEstimateWarning["code"]): EstimateWarningTone {
  if (code === "market_data_duplicates") return "yellow";
  if (code === "market_data_missing") return "red";
  if (code === "market_data_below_warmup") return "yellow";
  return "red";
}

function formatBarsPerScenario(value: number | null): string {
  return value == null ? "-" : `${formatInteger(value)} avg`;
}

function formatTotalBars(value: number | null): string {
  return value == null ? "-" : `${formatInteger(value)} bars total`;
}

function formatScenarioBars(scenarios: NonNullable<StrategyTestEstimateResponse["scenarios"]>): string {
  if (!scenarios.length) return "-";
  const visible = scenarios.slice(0, 4).map((scenario) =>
    `${scenario.strategy} ${scenario.exchange}:${scenario.symbol} ${scenario.timeframe}: ${formatInteger(scenario.bars_total)}`
  );
  const remaining = scenarios.length - visible.length;
  return remaining > 0 ? `${visible.join(" / ")} / +${remaining} more` : visible.join(" / ");
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

type StrategyTestEstimateWarning = NonNullable<StrategyTestEstimateResponse["warnings"]>[number];
type EstimateWarningTone = "red" | "yellow";
type RunEstimateLevel = "small" | "medium" | "large";

function firstConfiguredUserId(strategyConfigs: StrategyConfig[]): string | null {
  const config = strategyConfigs.find((strategy) => typeof strategy.user_id === "string" && strategy.user_id.trim());
  return config?.user_id.trim() ?? null;
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

function sanitizeStoredSelection(
  storedValues: string[] | undefined,
  availableValues: string[],
  fallbackValues: string[]
): string[] {
  if (!storedValues) return [...fallbackValues];
  const sanitized = filterKnownValues(storedValues, availableValues);
  return sanitized.length ? sanitized : [...fallbackValues];
}

function filterKnownValues(values: string[], availableValues: string[]): string[] {
  const available = new Set(availableValues);
  const seen = new Set<string>();
  return values.filter((value) => {
    if (!available.has(value) || seen.has(value)) return false;
    seen.add(value);
    return true;
  });
}

function filterPairOptions(pairOptions: MarketPairOption[], filterText: string): MarketPairOption[] {
  const query = filterText.trim().toLowerCase();
  if (!query) return pairOptions;
  return pairOptions.filter((pair) => [
    pair.symbol,
    pair.base_asset,
    pair.quote_asset,
    pair.exchange
  ].some((value) => value.toLowerCase().includes(query)));
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

function validateNumericInputs(
  initialCapital: string,
  feeRate: string,
  slippageBps: string,
  pendingEntryMaxWaitBars: string,
  testType: StrategyTestType
): string | null {
  if (toPositiveNumber(initialCapital) == null) return "Initial capital must be greater than zero.";
  if (toNonNegativeNumber(feeRate) == null) return "Fee rate must be zero or greater.";
  if (toNonNegativeNumber(slippageBps) == null) return "Slippage bps must be zero or greater.";
  if (testType === "historical_backtest" && toPositiveInteger(pendingEntryMaxWaitBars) == null) {
    return "Pending max wait bars must be a positive integer.";
  }
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
  const heartbeatReason = runtimeText(run, "last_heartbeat_reason");
  const runtimeStatus = runtimeText(run, "status");
  const displayedRuntimeStatus = runtimeStatus && runtimeStatus !== run.status ? runtimeStatus : null;
  const marketDataWaiting = isWaitingForMarketData(run);
  const historicalRunHasHeartbeat =
    run.test_type === "historical_backtest" &&
    run.status === "running" &&
    Boolean(run.last_heartbeat_at) &&
    !activeRunState?.is_stale;
  const queuedRunNeedsWorkerStartHint = run.status === "queued" && run.worker_attempt === 0 && !run.claimed_at;
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
      {historicalRunHasHeartbeat ? (
        <p className="strategy-test-active-run-reason">Run is receiving heartbeats. Large historical scenarios can stay on the same scenario for a while.</p>
      ) : null}
      {run.status === "queued" ? (
        <p className="strategy-test-active-run-reason">Queued; waiting for strategy-test worker to claim this run.</p>
      ) : null}
      {queuedRunNeedsWorkerStartHint ? (
        <p className="strategy-test-active-run-reason">If this does not change, start strategy-test-worker.</p>
      ) : null}
      {marketDataWaiting ? (
        <p className="strategy-test-active-run-reason">Waiting for market data</p>
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
        <div>
          <dt>Worker lease</dt>
          <dd>{workerLeaseLabel(run)}</dd>
        </div>
        <div>
          <dt>Worker attempt</dt>
          <dd>{formatDisplayValue(run.worker_attempt ?? 0)}</dd>
        </div>
        <div>
          <dt>Claimed</dt>
          <dd>{formatOptionalDate(run.claimed_at ?? null)}</dd>
        </div>
        <div>
          <dt>Lease expires</dt>
          <dd>{formatOptionalDate(run.lease_expires_at ?? null)}</dd>
        </div>
        <div>
          <dt>Last heartbeat</dt>
          <dd>{formatOptionalDate(run.last_heartbeat_at)}</dd>
        </div>
        {displayedRuntimeStatus ? (
          <div>
            <dt>Runtime status</dt>
            <dd>{displayedRuntimeStatus}</dd>
          </div>
        ) : null}
        {heartbeatReason ? (
          <div>
            <dt>Heartbeat reason</dt>
            <dd>{heartbeatReason}</dd>
          </div>
        ) : null}
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
  const phase = runtimeText(run, "phase");
  const displayedPhase = phase && phase !== run.status ? phase : null;
  const scenarioCompleted = runtimeNumber(run, "scenarios_completed") ?? runtimeNumber(run, "scenario_completed") ?? runSummaryNumber(run, "completed_scenarios") ?? 0;
  const scenarioTotal = runtimeNumber(run, "scenarios_total") ?? runtimeNumber(run, "scenario_total") ?? requestedScenarioCount(run) ?? runSummaryNumber(run, "scenario_count") ?? 0;
  const currentScenarioIndex = runtimeNumber(run, "current_scenario_index");
  const currentScenarioKey = runtimeText(run, "current_scenario_key");
  const matrixBarsProcessed = runtimeNumber(run, "matrix_bars_processed") ?? runtimeNumber(run, "bars_processed");
  const matrixBarsTotal = runtimeNumber(run, "matrix_bars_total") ?? runtimeNumber(run, "bars_total");
  const scenarioBarsProcessed = runtimeNumber(run, "current_scenario_bars_processed") ?? runtimeNumber(run, "scenario_bars_processed");
  const scenarioBarsTotal = runtimeNumber(run, "current_scenario_bars_total") ?? runtimeNumber(run, "scenario_bars_total");
  const barsPct = runtimeNumber(run, "bars_pct");
  const pendingArmed = runtimeCounterNumber(run, "pending_armed") ?? runtimeNumber(run, "pending_armed") ?? runtimeNumber(run, "pending_entries_armed") ?? runSummaryNumber(run, "pending_armed") ?? 0;
  const filled = runtimeCounterNumber(run, "filled") ?? runtimeNumber(run, "filled") ?? runtimeNumber(run, "opened_trades") ?? runSummaryNumber(run, "filled") ?? 0;
  const noEntry = runtimeCounterNumber(run, "no_entry") ?? runtimeNumber(run, "no_entry") ?? runSummaryNumber(run, "no_entry") ?? 0;
  const signals = runtimeCounterNumber(run, "signals") ?? runtimeNumber(run, "signals_seen") ?? runtimeNumber(run, "processed_signals") ?? runSummaryNumber(run, "signals_seen") ?? 0;
  const pendingEntries = runtimeCounterNumber(run, "pending_entries") ?? runtimeNumber(run, "pending_entries_count") ?? 0;
  const closed = runtimeCounterNumber(run, "closed") ?? runtimeNumber(run, "closed") ?? runtimeNumber(run, "closed_trades") ?? runSummaryNumber(run, "closed") ?? 0;

  return (
    <section aria-label="Active run progress summary" className="strategy-test-active-progress">
      {displayedPhase ? activeProgressItem("Phase", displayedPhase) : null}
      {activeProgressItem("Scenarios", scenarioTotal ? `${scenarioCompleted} / ${scenarioTotal}` : scenarioCompleted)}
      {activeProgressItem("Current scenario", currentScenarioIndex && scenarioTotal ? `${currentScenarioIndex} / ${scenarioTotal}` : currentScenarioIndex ?? "-")}
      {currentScenarioKey ? activeProgressItem("Scenario key", currentScenarioKey) : null}
      {activeProgressItem("Matrix bars", formatBarsProgress(matrixBarsProcessed, matrixBarsTotal, barsPct))}
      {activeProgressItem("Scenario bars", formatBarsCount(scenarioBarsProcessed, scenarioBarsTotal))}
      {activeProgressItem("Throughput", formatBarsPerSecond(runtimeNumber(run, "bars_per_second")))}
      {activeProgressItem("ETA", formatSeconds(runtimeNumber(run, "eta_seconds")))}
      {activeProgressItem("Signals", signals)}
      {activeProgressItem("Pending armed", pendingArmed)}
      {activeProgressItem("Pending entries", pendingEntries)}
      {activeProgressItem("No entry", noEntry)}
      {activeProgressItem("Filled", filled)}
      {activeProgressItem("Closed", closed)}
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

function runtimeText(run: StrategyTestRunResponse, key: string): string | null {
  const value = run.runtime_state[key];
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text || null;
}

function workerLeaseLabel(run: StrategyTestRunResponse): string {
  if (run.worker_id) return run.worker_id;
  if (run.status === "queued") return "Waiting for worker";
  if (run.status === "running" || run.status === "stopping") return "Worker not claimed";
  return "-";
}

function isWaitingForMarketData(run: StrategyTestRunResponse): boolean {
  if (run.test_type !== "forward_virtual") return false;
  const stateValues = [
    runtimeText(run, "status"),
    runtimeText(run, "last_heartbeat_reason"),
    runtimeText(run, "last_forward_event")
  ].filter((value): value is string => Boolean(value));
  return stateValues.some((value) => value === "waiting_for_market_data" || value === "no_matching_market_data");
}

function runtimeCounterNumber(run: StrategyTestRunResponse, key: string): number | null {
  const counters = run.runtime_state.counters;
  if (!counters || typeof counters !== "object" || Array.isArray(counters)) return null;
  const value = (counters as Record<string, unknown>)[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
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

function formatBarsCount(processed: number | null, total: number | null): string {
  if (processed == null && total == null) return "-";
  return `${formatActiveNumber(processed ?? 0)} / ${formatActiveNumber(total ?? 0)}`;
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
