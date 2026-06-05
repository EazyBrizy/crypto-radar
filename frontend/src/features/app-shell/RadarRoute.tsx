"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { RadarPage } from "@/features/app-shell/RadarPage";
import { useAuthSessionQuery } from "@/auth/use-auth";
import {
  useExchangeConnectionAccountSnapshotsQuery,
  useExchangeConnectionsQuery,
  useHealthQuery,
  useHistoricalSignalsQuery,
  usePendingEntriesQuery,
  usePendingEntryActionStatesQuery,
  usePendingEntryHistoryQuery,
  usePendingEntryQuery,
  useRadarQuery,
  useRadarStatusQuery,
  useRejectSignalMutation,
  useRiskStateQuery,
  useSendSignalActionMutation,
  useSignalActionStateQuery,
  useSignalExecutionPreviewQuery,
  useUserProfileQuery
} from "@/hooks/use-radar-queries";
import { isActivePendingEntryStatus, isTerminalPendingEntryStatus } from "@/domain/pending-entry-status";
import { useSignalStore } from "@/stores/signal-store";
import { useTradingActionsDisabled } from "@/stores/ui-selectors";
import { useUiStore } from "@/stores/ui-store";
import type { PendingEntryIntent, RadarSignal, SignalActionState, SignalStatus } from "@/types";
import type { ExchangeConnection, RadarDisplayMode } from "@/features/server-state/types";
import { mergeRadarSnapshotWithRealtime } from "@/features/server-state/radar-cache";
import { isOpenFeedSignal } from "@/utils";

export function RadarRoute() {
  const router = useRouter();
  const selectedSignalId = useUiStore((state) => state.selectedSignalId);
  const filter = useUiStore((state) => state.signalFilter);
  const setSelectedSignalId = useUiStore((state) => state.setSelectedSignalId);
  const setFilter = useUiStore((state) => state.setSignalFilter);
  const [actionError, setActionError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | SignalStatus>("all");
  const [signalView, setSignalView] = useState<"open" | "history">("open");
  const [radarDisplayMode, setRadarDisplayMode] = useState<RadarDisplayMode>("all_market_opportunities");
  const [hasUserSelectedSignal, setHasUserSelectedSignal] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const hasAutoSelectedSignalRef = useRef(false);
  const pendingArmInFlightRef = useRef(false);
  const tradingActionsDisabled = useTradingActionsDisabled();
  const signalIds = useSignalStore((state) => state.signalIds);
  const signalsById = useSignalStore((state) => state.signalsById);
  const replaceSignals = useSignalStore((state) => state.replaceSignals);

  const sessionQuery = useAuthSessionQuery();
  const userId = sessionQuery.data?.user.id ?? null;
  const healthQuery = useHealthQuery();
  const radarStatusQuery = useRadarStatusQuery();
  const radarQuery = useRadarQuery(radarDisplayMode, userId);
  const historicalSignalsQuery = useHistoricalSignalsQuery();
  const exchangeConnectionsQuery = useExchangeConnectionsQuery();
  const userProfileQuery = useUserProfileQuery({ enabled: true });
  const riskStateQuery = useRiskStateQuery();
  const signalActionMutation = useSendSignalActionMutation();
  const rejectSignalMutation = useRejectSignalMutation();

  useEffect(() => {
    if (!radarQuery.data) return;
    const snapshotReceivedAt = radarQuery.dataUpdatedAt || Date.now();
    const signalState = useSignalStore.getState();
    const currentSignals = signalState.signalIds
      .map((signalId) => signalState.signalsById[signalId])
      .filter((signal): signal is RadarSignal => Boolean(signal));
    replaceSignals(
      mergeRadarSnapshotWithRealtime(
        currentSignals,
        radarQuery.data.signals,
        snapshotReceivedAt,
        signalState.signalReceivedAtById
      ),
      snapshotReceivedAt
    );
  }, [radarQuery.data, radarQuery.dataUpdatedAt, replaceSignals]);

  useEffect(() => {
    const intervalId = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(intervalId);
  }, []);

  const signals = useMemo(
    () => signalIds.map((signalId) => signalsById[signalId]).filter((signal): signal is RadarSignal => Boolean(signal) && isOpenFeedSignal(signal, nowMs)),
    [nowMs, signalIds, signalsById]
  );
  const historicalSignals = useMemo(
    () => (historicalSignalsQuery.data ?? []).filter((signal) => signal.status === "invalidated" || signal.status === "expired"),
    [historicalSignalsQuery.data]
  );
  const sourceSignals = signalView === "history" ? historicalSignals : signals;
  const visibleSignals = useMemo(() => {
    return sourceSignals.filter((signal) => {
      const directionMatches = filter === "all" || signal.direction === filter;
      const statusMatches = statusFilter === "all" || signal.status === statusFilter;
      return directionMatches && statusMatches;
    });
  }, [filter, sourceSignals, statusFilter]);
  const visibleSignalIds = useMemo(() => visibleSignals.map((signal) => signal.id), [visibleSignals]);
  useEffect(() => {
    if (hasUserSelectedSignal || hasAutoSelectedSignalRef.current || selectedSignalId) return;
    const firstVisibleSignalId = visibleSignalIds[0] ?? null;
    if (!firstVisibleSignalId) return;
    hasAutoSelectedSignalRef.current = true;
    setSelectedSignalId(firstVisibleSignalId);
  }, [hasUserSelectedSignal, selectedSignalId, setSelectedSignalId, visibleSignalIds]);
  const selectedSignal = useMemo(
    () => visibleSignals.find((signal) => signal.id === selectedSignalId) ?? null,
    [selectedSignalId, visibleSignals]
  );
  const missingSelectedSignalId = selectedSignalId != null && selectedSignal == null ? selectedSignalId : null;
  const selectedRealConnection = useMemo(
    () => selectRealTradeConnection(exchangeConnectionsQuery.data ?? [], selectedSignal),
    [exchangeConnectionsQuery.data, selectedSignal]
  );
  const realConnectionIds = useMemo(
    () => selectedRealConnection ? [selectedRealConnection.id] : [],
    [selectedRealConnection]
  );
  const accountSnapshotsQuery = useExchangeConnectionAccountSnapshotsQuery(realConnectionIds, userId);
  const virtualActionStateQuery = useSignalActionStateQuery(selectedSignal?.id ?? null, "virtual", null, {
    enabled: selectedSignal != null && signalView === "open"
  });
  const realActionStateQuery = useSignalActionStateQuery(selectedSignal?.id ?? null, "real", selectedRealConnection?.id ?? null, {
    enabled: selectedSignal != null && signalView === "open"
  });
  const executionPreviewQuery = useSignalExecutionPreviewQuery(selectedSignal?.id ?? null, {
    enabled: shouldRequestExecutionPreview(selectedSignal, signalView, tradingActionsDisabled)
  });
  const pendingEntryQuery = usePendingEntryQuery(selectedSignal?.id ?? null, userId, {
    enabled: selectedSignal != null && signalView === "open"
  });
  const pendingEntryHistoryQuery = usePendingEntryHistoryQuery(selectedSignal?.id ?? null, userId, {
    enabled: selectedSignal != null && signalView === "open"
  });
  const pendingEntriesQuery = usePendingEntriesQuery(userId, "active", {
    enabled: true,
    limit: 100
  });
  const pendingEntryQueueHistoryQuery = usePendingEntriesQuery(userId, "history", {
    enabled: true,
    limit: 25
  });
  const pendingEntryActionStates = usePendingEntryActionStatesQuery(pendingEntriesQuery.data ?? [], {
    enabled: Boolean(pendingEntriesQuery.data?.length)
  });
  const selectedPendingEntry = useMemo(
    () => selectPendingEntryForDetails(pendingEntryQuery.data ?? null, pendingEntryHistoryQuery.data ?? []),
    [pendingEntryHistoryQuery.data, pendingEntryQuery.data]
  );
  const selectedAccountSnapshot = selectedRealConnection
    ? accountSnapshotsQuery.dataByConnectionId[selectedRealConnection.id] ?? null
    : null;
  const realTradeContext = useMemo(() => ({
    userId,
    connection: selectedRealConnection,
    accountSnapshot: selectedAccountSnapshot,
    riskState: riskStateQuery.data ?? null,
    realExecutionEnabled: Boolean(userProfileQuery.data?.settings.risk_management.real_execution_enabled),
    loading: Boolean(
      exchangeConnectionsQuery.isFetching
      || userProfileQuery.isFetching
      || riskStateQuery.isFetching
      || (selectedRealConnection && accountSnapshotsQuery.pendingByConnectionId[selectedRealConnection.id])
    )
  }), [
    accountSnapshotsQuery.pendingByConnectionId,
    exchangeConnectionsQuery.isFetching,
    riskStateQuery.data,
    riskStateQuery.isFetching,
    selectedAccountSnapshot,
    selectedRealConnection,
    userId,
    userProfileQuery.data,
    userProfileQuery.isFetching
  ]);
  const loading = [healthQuery, radarStatusQuery, radarQuery].some((query) => query.isLoading)
    || (signalView === "history" && historicalSignalsQuery.isLoading);
  const busy = signalActionMutation.isPending
    || rejectSignalMutation.isPending
    || tradingActionsDisabled;

  const refreshData = useCallback(async () => {
    await Promise.all([
      healthQuery.refetch(),
      radarStatusQuery.refetch(),
      radarQuery.refetch(),
      historicalSignalsQuery.refetch(),
      pendingEntriesQuery.refetch(),
      pendingEntryHistoryQuery.refetch(),
      pendingEntryQueueHistoryQuery.refetch(),
      riskStateQuery.refetch(),
      userProfileQuery.refetch(),
      virtualActionStateQuery.refetch(),
      realActionStateQuery.refetch()
    ]);
  }, [healthQuery, historicalSignalsQuery, pendingEntriesQuery, pendingEntryHistoryQuery, pendingEntryQueueHistoryQuery, radarQuery, radarStatusQuery, realActionStateQuery, riskStateQuery, userProfileQuery, virtualActionStateQuery]);

  const handleSelectSignal = useCallback((signal: RadarSignal) => {
    setActionError(null);
    setHasUserSelectedSignal(true);
    setSelectedSignalId(signal.id);
  }, [setSelectedSignalId]);

  const handleSelectLatestSignal = useCallback(() => {
    const latestSignal = visibleSignals[0] ?? null;
    if (!latestSignal) return;
    setActionError(null);
    setHasUserSelectedSignal(true);
    setSelectedSignalId(latestSignal.id);
  }, [setSelectedSignalId, visibleSignals]);

  const handleSelectPendingEntrySignal = useCallback((intent: PendingEntryIntent) => {
    setActionError(null);
    setHasUserSelectedSignal(true);
    setSelectedSignalId(intent.signal_id);
  }, [setSelectedSignalId]);

  async function handlePaperTrade(signal: RadarSignal) {
    try {
      if (tradingActionsDisabled) return;
      const state = virtualActionStateQuery.data ?? null;
      const kind = state?.can_enter_now
        ? "enter_now"
        : state?.can_arm_pending
          ? "arm_pending_entry"
          : null;
      if (!kind) {
        setActionError(actionStateErrorMessage(state, "Only open strategy ideas can be armed or sent to virtual trading."));
        return;
      }
      setActionError(null);
      await signalActionMutation.mutateAsync({
        signalId: signal.id,
        kind,
        mode: "virtual"
      });
      await refreshData();
      if (kind === "enter_now") {
        router.push("/dashboard/trades/active");
      }
    } catch (exc) {
      setActionError(errorMessage(exc, "Virtual trade was rejected by execution quality checks."));
    }
  }

  async function handleConfirmRealTrade(signal: RadarSignal) {
    try {
      if (tradingActionsDisabled) return;
      setActionError(null);
      const connection = selectRealTradeConnection(exchangeConnectionsQuery.data ?? [], signal);
      const state = realActionStateQuery.data ?? null;
      const kind = state?.can_enter_now
        ? "enter_now"
        : state?.can_arm_pending
          ? "arm_pending_entry"
          : null;
      if (!kind) {
        setActionError(actionStateErrorMessage(state, "Real trade was rejected by execution safeguards."));
        return;
      }
      await signalActionMutation.mutateAsync({
        signalId: signal.id,
        kind,
        mode: "real",
        connectionId: connection?.id ?? null,
      });
      await refreshData();
      if (kind === "enter_now") {
        router.push("/dashboard/trades/active");
      }
    } catch (exc) {
      setActionError(errorMessage(exc, "Real trade was rejected by execution safeguards."));
    }
  }

  async function handleAcceptPendingEntry(signal: RadarSignal) {
    if (pendingArmInFlightRef.current) return;
    try {
      if (tradingActionsDisabled) return;
      const state = virtualActionStateQuery.data ?? null;
      if (!state?.can_arm_pending) {
        setActionError(actionStateErrorMessage(state, "This signal is not available for pending entry."));
        return;
      }
      pendingArmInFlightRef.current = true;
      setActionError(null);
      await signalActionMutation.mutateAsync({
        signalId: signal.id,
        kind: "arm_pending_entry",
        mode: "virtual"
      });
      await refreshData();
    } catch (exc) {
      setActionError(errorMessage(exc, "Pending entry was rejected."));
    } finally {
      pendingArmInFlightRef.current = false;
    }
  }

  async function handleCancelPendingEntry(intent: PendingEntryIntent) {
    try {
      if (tradingActionsDisabled) return;
      const state = pendingActionState(intent, pendingEntryActionStates.dataByIntentId, {
        real: realActionStateQuery.data ?? null,
        selectedSignalId,
        virtual: virtualActionStateQuery.data ?? null
      });
      if (!state?.can_cancel) {
        setActionError(actionStateErrorMessage(state, "Pending entry cancel failed."));
        return;
      }
      setActionError(null);
      await signalActionMutation.mutateAsync({
        signalId: intent.signal_id,
        kind: "cancel_pending_entry",
        mode: intent.mode,
        connectionId: pendingEntryConnectionId(intent)
      });
      await refreshData();
    } catch (exc) {
      setActionError(errorMessage(exc, "Pending entry cancel failed."));
    }
  }

  async function handleReconfirmPendingEntry(intent: PendingEntryIntent) {
    try {
      if (tradingActionsDisabled) return;
      const state = pendingActionState(intent, pendingEntryActionStates.dataByIntentId, {
        real: realActionStateQuery.data ?? null,
        selectedSignalId,
        virtual: virtualActionStateQuery.data ?? null
      });
      if (!state?.can_reconfirm) {
        setActionError(actionStateErrorMessage(state, "Pending entry reconfirmation failed."));
        return;
      }
      setActionError(null);
      await signalActionMutation.mutateAsync({
        signalId: intent.signal_id,
        kind: "reconfirm_pending_entry",
        mode: intent.mode,
        connectionId: pendingEntryConnectionId(intent)
      });
      await refreshData();
    } catch (exc) {
      setActionError(errorMessage(exc, "Pending entry reconfirmation failed."));
    }
  }

  async function handleReject(signal: RadarSignal) {
    try {
      if (tradingActionsDisabled) return;
      setActionError(null);
      await rejectSignalMutation.mutateAsync(signal.id);
      await refreshData();
    } catch (exc) {
      setActionError(errorMessage(exc, "Signal reject failed."));
    }
  }

  return (
    <RadarPage
      signals={visibleSignals}
      signalView={signalView}
      selectedSignal={selectedSignal}
      health={healthQuery.data ?? radarStatusQuery.data ?? null}
      radarStatus={radarStatusQuery.data ?? null}
      radarSummary={radarQuery.data?.summary ?? null}
      loading={loading}
      busy={busy}
      actionError={actionError}
      executionPreview={executionPreviewQuery.data ?? null}
      executionPreviewError={executionPreviewQuery.error instanceof Error ? executionPreviewQuery.error.message : null}
      executionPreviewLoading={executionPreviewQuery.isFetching}
      actionState={virtualActionStateQuery.data ?? null}
      actionStateLoading={virtualActionStateQuery.isFetching}
      realActionState={realActionStateQuery.data ?? null}
      selectedPendingEntry={selectedPendingEntry}
      pendingEntryLoading={pendingEntryQuery.isFetching || pendingEntryHistoryQuery.isFetching || virtualActionStateQuery.isFetching}
      pendingEntries={pendingEntriesQuery.data ?? []}
      pendingEntryHistory={pendingEntryQueueHistoryQuery.data ?? []}
      pendingEntriesLoading={pendingEntriesQuery.isFetching || pendingEntryQueueHistoryQuery.isFetching}
      pendingEntryActionStates={pendingEntryActionStates.dataByIntentId}
      pendingEntryActionStatesLoading={pendingEntryActionStates.pendingByIntentId}
      tradingActionsDisabled={tradingActionsDisabled}
      filter={filter}
      radarDisplayMode={radarDisplayMode}
      statusFilter={statusFilter}
      onFilterChange={setFilter}
      onRadarDisplayModeChange={setRadarDisplayMode}
      onSignalViewChange={setSignalView}
      onStatusFilterChange={setStatusFilter}
      onRefresh={() => void refreshData()}
      onSelectSignal={handleSelectSignal}
      onSelectPendingEntrySignal={handleSelectPendingEntrySignal}
      onSelectLatestSignal={handleSelectLatestSignal}
      onPaperTrade={handlePaperTrade}
      onConfirmRealTrade={handleConfirmRealTrade}
      onAcceptPendingEntry={handleAcceptPendingEntry}
      onCancelPendingEntry={handleCancelPendingEntry}
      onReconfirmPendingEntry={handleReconfirmPendingEntry}
      onReject={handleReject}
      realTradeContext={realTradeContext}
      realTradeBusy={signalActionMutation.isPending}
      selectedSignalId={selectedSignalId}
      missingSelectedSignalId={missingSelectedSignalId}
      signalIds={visibleSignalIds}
    />
  );
}

function isActionableSignal(signal: RadarSignal): boolean {
  return signal.details_view?.can_enter_now === true;
}

export function shouldRequestExecutionPreview(
  signal: RadarSignal | null,
  signalView: "open" | "history",
  tradingActionsDisabled: boolean
): boolean {
  return signal?.details_view?.execution_summary.preview_available === true
    && signalView === "open"
    && !tradingActionsDisabled;
}

export function canSendPaperTrade(signal: RadarSignal | null): boolean {
  return signal != null && isActionableSignal(signal);
}

export function canArmPendingEntry(signal: RadarSignal | null): boolean {
  return signal?.details_view?.primary_action_label === "Wait for entry"
    || signal?.details_view?.primary_status === "waiting_entry";
}

export function selectRealTradeConnection(
  connections: ExchangeConnection[],
  signal: RadarSignal | null
): ExchangeConnection | null {
  if (!signal) return null;
  const signalExchange = signal.exchange.trim().toLowerCase();
  return connections.find((connection) =>
    isActiveExchangeConnection(connection)
    && [connection.exchange_code, connection.exchange_name]
      .map((value) => value.trim().toLowerCase())
      .includes(signalExchange)
  ) ?? null;
}

export function selectPendingEntryForDetails(
  activeIntent: PendingEntryIntent | null,
  historyIntents: PendingEntryIntent[] = []
): PendingEntryIntent | null {
  if (activeIntent && isActivePendingEntryIntent(activeIntent)) return activeIntent;
  return latestTerminalPendingEntryIntent(historyIntents);
}

function errorMessage(exc: unknown, fallback: string): string {
  return exc instanceof Error && exc.message ? exc.message : fallback;
}

function actionStateErrorMessage(state: SignalActionState | null, fallback: string): string {
  if (!state) return fallback;
  const blocker = state.blockers[0] ?? null;
  return state.display_labels.disabled_reason
    ?? blocker?.display_label
    ?? blocker?.message
    ?? state.disabled_reason_code
    ?? fallback;
}

function pendingActionState(
  intent: PendingEntryIntent,
  actionStatesByIntentId: Record<string, SignalActionState | null>,
  selected: {
    real: SignalActionState | null;
    selectedSignalId: string | null;
    virtual: SignalActionState | null;
  }
): SignalActionState | null {
  const queuedState = actionStatesByIntentId[intent.id] ?? null;
  if (queuedState) return queuedState;
  if (selected.selectedSignalId !== intent.signal_id) return null;
  return intent.mode === "real" ? selected.real : selected.virtual;
}

function pendingEntryConnectionId(intent: PendingEntryIntent): string | null {
  const snapshot = intent.request_snapshot;
  const metadata = isRecord(snapshot.metadata) ? snapshot.metadata : {};
  for (const value of [snapshot.connection_id, snapshot.connectionId, metadata.connection_id, metadata.connectionId]) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isActivePendingEntryIntent(intent: PendingEntryIntent): boolean {
  return isActivePendingEntryStatus(intent.status);
}

function isActiveExchangeConnection(connection: ExchangeConnection): boolean {
  const status = connection.status.trim().toLowerCase();
  return status === "active" || status === "connected";
}

function latestTerminalPendingEntryIntent(intents: PendingEntryIntent[]): PendingEntryIntent | null {
  return intents
    .filter((intent) => isTerminalPendingEntryStatus(intent.status))
    .sort((left, right) => pendingEntryUpdatedAt(right) - pendingEntryUpdatedAt(left))[0] ?? null;
}

function pendingEntryUpdatedAt(intent: PendingEntryIntent): number {
  const updatedAt = Date.parse(intent.updated_at);
  if (Number.isFinite(updatedAt)) return updatedAt;
  const createdAt = Date.parse(intent.created_at);
  return Number.isFinite(createdAt) ? createdAt : 0;
}
