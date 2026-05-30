"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { RadarPage } from "@/features/app-shell/RadarPage";
import {
  useConfirmVirtualMutation,
  useHealthQuery,
  useOpenSignalsQuery,
  useRadarStatusQuery,
  useRejectSignalMutation,
  useSignalExecutionPreviewQuery
} from "@/hooks/use-radar-queries";
import { useSignalStore } from "@/stores/signal-store";
import { useTradingActionsDisabled } from "@/stores/ui-selectors";
import { useUiStore } from "@/stores/ui-store";
import type { RadarSignal, SignalStatus } from "@/types";
import { isOpenFeedSignal } from "@/utils";

export function RadarRoute() {
  const router = useRouter();
  const selectedSignalId = useUiStore((state) => state.selectedSignalId);
  const filter = useUiStore((state) => state.signalFilter);
  const setSelectedSignalId = useUiStore((state) => state.setSelectedSignalId);
  const setFilter = useUiStore((state) => state.setSignalFilter);
  const [actionError, setActionError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | SignalStatus>("all");
  const [nowMs, setNowMs] = useState(() => Date.now());
  const tradingActionsDisabled = useTradingActionsDisabled();
  const signalIds = useSignalStore((state) => state.signalIds);
  const signalsById = useSignalStore((state) => state.signalsById);
  const replaceSignals = useSignalStore((state) => state.replaceSignals);

  const healthQuery = useHealthQuery();
  const radarStatusQuery = useRadarStatusQuery();
  const openSignalsQuery = useOpenSignalsQuery();
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
  const visibleSignals = useMemo(() => {
    return signals.filter((signal) => {
      const directionMatches = filter === "all" || signal.direction === filter;
      const statusMatches = statusFilter === "all" || signal.status === statusFilter;
      return directionMatches && statusMatches;
    });
  }, [filter, signals, statusFilter]);
  const visibleSignalIds = useMemo(() => visibleSignals.map((signal) => signal.id), [visibleSignals]);
  const selectedSignal = useMemo(
    () => signals.find((signal) => signal.id === selectedSignalId) ?? visibleSignals[0] ?? null,
    [selectedSignalId, signals, visibleSignals]
  );
  const executionPreviewQuery = useSignalExecutionPreviewQuery(selectedSignal?.id ?? null, {
    enabled: Boolean(selectedSignal) && !tradingActionsDisabled
  });
  const loading = [healthQuery, radarStatusQuery, openSignalsQuery].some((query) => query.isLoading);
  const busy = confirmVirtualMutation.isPending || rejectSignalMutation.isPending || tradingActionsDisabled;

  const refreshData = useCallback(async () => {
    await Promise.all([
      healthQuery.refetch(),
      radarStatusQuery.refetch(),
      openSignalsQuery.refetch()
    ]);
  }, [healthQuery, openSignalsQuery, radarStatusQuery]);

  const handleSelectSignal = useCallback((signal: RadarSignal) => {
    setActionError(null);
    setSelectedSignalId(signal.id);
  }, [setSelectedSignalId]);

  async function handlePaperTrade(signal: RadarSignal) {
    try {
      if (tradingActionsDisabled) return;
      if (!isActionableSignal(signal)) {
        setActionError("Only actionable strategy signals can be sent to Paper Trade.");
        return;
      }
      setActionError(null);
      await confirmVirtualMutation.mutateAsync(signal.id);
      await refreshData();
      router.push("/dashboard/trades/active");
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
  return signal.status === "actionable" || signal.status === "active" || signal.status === "entry_touched";
}

function errorMessage(exc: unknown, fallback: string): string {
  return exc instanceof Error && exc.message ? exc.message : fallback;
}
