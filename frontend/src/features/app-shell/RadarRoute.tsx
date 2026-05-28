"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { RadarPage } from "@/features/app-shell/RadarPage";
import {
  useActiveSignalsQuery,
  useConfirmVirtualMutation,
  useHealthQuery,
  useRadarStatusQuery,
  useRejectSignalMutation,
  useSignalExecutionPreviewQuery
} from "@/hooks/use-radar-queries";
import { useSignalStore } from "@/stores/signal-store";
import { useTradingActionsDisabled } from "@/stores/ui-selectors";
import { useUiStore } from "@/stores/ui-store";
import type { RadarSignal } from "@/types";

export function RadarRoute() {
  const router = useRouter();
  const selectedSignalId = useUiStore((state) => state.selectedSignalId);
  const filter = useUiStore((state) => state.signalFilter);
  const setSelectedSignalId = useUiStore((state) => state.setSelectedSignalId);
  const setFilter = useUiStore((state) => state.setSignalFilter);
  const [actionError, setActionError] = useState<string | null>(null);
  const tradingActionsDisabled = useTradingActionsDisabled();
  const signalIds = useSignalStore((state) => state.signalIds);
  const signalsById = useSignalStore((state) => state.signalsById);
  const replaceSignals = useSignalStore((state) => state.replaceSignals);

  const healthQuery = useHealthQuery();
  const radarStatusQuery = useRadarStatusQuery();
  const activeSignalsQuery = useActiveSignalsQuery();
  const confirmVirtualMutation = useConfirmVirtualMutation();
  const rejectSignalMutation = useRejectSignalMutation();

  useEffect(() => {
    if (activeSignalsQuery.data) replaceSignals(activeSignalsQuery.data);
  }, [activeSignalsQuery.data, replaceSignals]);

  const signals = useMemo(
    () => signalIds.map((signalId) => signalsById[signalId]).filter(Boolean),
    [signalIds, signalsById]
  );
  const visibleSignals = useMemo(() => {
    if (filter === "all") return signals;
    return signals.filter((signal) => signal.direction === filter);
  }, [filter, signals]);
  const visibleSignalIds = useMemo(() => visibleSignals.map((signal) => signal.id), [visibleSignals]);
  const selectedSignal = useMemo(
    () => signals.find((signal) => signal.id === selectedSignalId) ?? visibleSignals[0] ?? null,
    [selectedSignalId, signals, visibleSignals]
  );
  const executionPreviewQuery = useSignalExecutionPreviewQuery(selectedSignal?.id ?? null, {
    enabled: Boolean(selectedSignal) && !tradingActionsDisabled
  });
  const loading = [healthQuery, radarStatusQuery, activeSignalsQuery].some((query) => query.isLoading);
  const busy = confirmVirtualMutation.isPending || rejectSignalMutation.isPending || tradingActionsDisabled;

  const refreshData = useCallback(async () => {
    await Promise.all([
      healthQuery.refetch(),
      radarStatusQuery.refetch(),
      activeSignalsQuery.refetch()
    ]);
  }, [activeSignalsQuery, healthQuery, radarStatusQuery]);

  const handleSelectSignal = useCallback((signal: RadarSignal) => {
    setActionError(null);
    setSelectedSignalId(signal.id);
  }, [setSelectedSignalId]);

  async function handlePaperTrade(signal: RadarSignal) {
    try {
      if (tradingActionsDisabled) return;
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
      executionPreviewLoading={executionPreviewQuery.isFetching}
      tradingActionsDisabled={tradingActionsDisabled}
      filter={filter}
      onFilterChange={setFilter}
      onRefresh={() => void refreshData()}
      onSelectSignal={handleSelectSignal}
      onPaperTrade={handlePaperTrade}
      onReject={handleReject}
      selectedSignalId={selectedSignal?.id ?? null}
      signalIds={visibleSignalIds}
    />
  );
}

function errorMessage(exc: unknown, fallback: string): string {
  return exc instanceof Error && exc.message ? exc.message : fallback;
}
