"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { RadarPage } from "@/features/app-shell/RadarPage";
import {
  useConfirmVirtualMutation,
  useHealthQuery,
  useHistoricalSignalsQuery,
  useOpenSignalsQuery,
  useRadarStatusQuery,
  useRejectSignalMutation,
  useSignalExecutionPreviewQuery
} from "@/hooks/use-radar-queries";
import { useSignalStore } from "@/stores/signal-store";
import { useTradingActionsDisabled } from "@/stores/ui-selectors";
import { useUiStore } from "@/stores/ui-store";
import type { RadarSignal, SignalStatus } from "@/types";
import { isOpenCandleActionableAllowed, isOpenFeedSignal, isSignalActionableForUi } from "@/utils";

export function RadarRoute() {
  const router = useRouter();
  const selectedSignalId = useUiStore((state) => state.selectedSignalId);
  const filter = useUiStore((state) => state.signalFilter);
  const setSelectedSignalId = useUiStore((state) => state.setSelectedSignalId);
  const setFilter = useUiStore((state) => state.setSignalFilter);
  const [actionError, setActionError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | SignalStatus>("all");
  const [signalView, setSignalView] = useState<"open" | "history">("open");
  const [nowMs, setNowMs] = useState(() => Date.now());
  const tradingActionsDisabled = useTradingActionsDisabled();
  const signalIds = useSignalStore((state) => state.signalIds);
  const signalsById = useSignalStore((state) => state.signalsById);
  const replaceSignals = useSignalStore((state) => state.replaceSignals);

  const healthQuery = useHealthQuery();
  const radarStatusQuery = useRadarStatusQuery();
  const openSignalsQuery = useOpenSignalsQuery();
  const historicalSignalsQuery = useHistoricalSignalsQuery();
  const confirmVirtualMutation = useConfirmVirtualMutation();
  const rejectSignalMutation = useRejectSignalMutation();

  useEffect(() => {
    if (openSignalsQuery.data) replaceSignals(openSignalsQuery.data.filter((signal) => isOpenFeedSignal(signal, nowMs)));
  }, [nowMs, openSignalsQuery.data, replaceSignals]);

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
  const selectedSignal = useMemo(
    () => sourceSignals.find((signal) => signal.id === selectedSignalId) ?? visibleSignals[0] ?? null,
    [selectedSignalId, sourceSignals, visibleSignals]
  );
  const executionPreviewQuery = useSignalExecutionPreviewQuery(selectedSignal?.id ?? null, {
    enabled: shouldRequestExecutionPreview(selectedSignal, signalView, tradingActionsDisabled)
  });
  const loading = [healthQuery, radarStatusQuery, openSignalsQuery].some((query) => query.isLoading)
    || (signalView === "history" && historicalSignalsQuery.isLoading);
  const busy = confirmVirtualMutation.isPending || rejectSignalMutation.isPending || tradingActionsDisabled;

  const refreshData = useCallback(async () => {
    await Promise.all([
      healthQuery.refetch(),
      radarStatusQuery.refetch(),
      openSignalsQuery.refetch(),
      historicalSignalsQuery.refetch()
    ]);
  }, [healthQuery, historicalSignalsQuery, openSignalsQuery, radarStatusQuery]);

  const handleSelectSignal = useCallback((signal: RadarSignal) => {
    setActionError(null);
    setSelectedSignalId(signal.id);
  }, [setSelectedSignalId]);

  async function handlePaperTrade(signal: RadarSignal) {
    try {
      if (tradingActionsDisabled) return;
      if (!canSendPaperTrade(signal)) {
        setActionError("Only open strategy ideas can be armed or sent to Paper Trade.");
        return;
      }
      setActionError(null);
      await confirmVirtualMutation.mutateAsync({
        signalId: signal.id,
        waitForConfirmation: !isActionableSignal(signal)
      });
      await refreshData();
      if (isActionableSignal(signal)) {
        router.push("/dashboard/trades/active");
      }
    } catch (exc) {
      setActionError(errorMessage(exc, "Virtual trade was rejected by execution quality checks."));
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
      loading={loading}
      busy={busy}
      actionError={actionError}
      executionPreview={executionPreviewQuery.data ?? null}
      executionPreviewError={executionPreviewQuery.error instanceof Error ? executionPreviewQuery.error.message : null}
      executionPreviewLoading={executionPreviewQuery.isFetching}
      tradingActionsDisabled={tradingActionsDisabled}
      filter={filter}
      statusFilter={statusFilter}
      onFilterChange={setFilter}
      onSignalViewChange={setSignalView}
      onStatusFilterChange={setStatusFilter}
      onRefresh={() => void refreshData()}
      onSelectSignal={handleSelectSignal}
      onPaperTrade={handlePaperTrade}
      onReject={handleReject}
      selectedSignalId={selectedSignal?.id ?? null}
      signalIds={visibleSignalIds}
    />
  );
}

function isActionableSignal(signal: RadarSignal): boolean {
  return isSignalActionableForUi(signal);
}

export function shouldRequestExecutionPreview(
  signal: RadarSignal | null,
  signalView: "open" | "history",
  tradingActionsDisabled: boolean
): boolean {
  return signal != null && signalView === "open" && !tradingActionsDisabled && isPreviewableSignal(signal);
}

function isPreviewableSignal(signal: RadarSignal): boolean {
  return (
    signal.status === "new"
    || signal.status === "actionable"
    || signal.status === "active"
    || signal.status === "entry_touched"
    || signal.status === "watchlist"
    || signal.status === "ready"
    || signal.status === "wait_for_pullback"
  );
}

export function canSendPaperTrade(signal: RadarSignal | null): boolean {
  return signal != null && (isActionableSignal(signal) || canArmAutoEntry(signal));
}

export function canArmAutoEntry(signal: RadarSignal | null): boolean {
  if (!signal) return false;
  if (signal.auto_entry?.status === "pending") return false;
  if (signal.candle_state === "open" && !isOpenCandleActionableAllowed(signal)) return false;
  return signal.status === "watchlist" || signal.status === "ready" || signal.status === "wait_for_pullback";
}

function errorMessage(exc: unknown, fallback: string): string {
  return exc instanceof Error && exc.message ? exc.message : fallback;
}
