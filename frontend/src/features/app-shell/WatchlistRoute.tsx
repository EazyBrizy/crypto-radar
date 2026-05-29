"use client";

import { useEffect, useMemo, useState } from "react";

import { WatchlistPage } from "@/features/app-shell/WatchlistPage";
import {
  useAddWatchlistPairMutation,
  useMarketPairsQuery,
  useOpenSignalsQuery,
  useRemoveWatchlistPairMutation,
  useWatchlistQuery
} from "@/hooks/use-radar-queries";
import { useSignalStore } from "@/stores/signal-store";
import type { RadarSignal } from "@/types";
import { isOpenFeedSignal } from "@/utils";

export function WatchlistRoute() {
  const openSignalsQuery = useOpenSignalsQuery();
  const watchlistQuery = useWatchlistQuery();
  const marketPairsQuery = useMarketPairsQuery();
  const addPairMutation = useAddWatchlistPairMutation();
  const removePairMutation = useRemoveWatchlistPairMutation();
  const [nowMs, setNowMs] = useState(() => Date.now());
  const signalIds = useSignalStore((state) => state.signalIds);
  const signalsById = useSignalStore((state) => state.signalsById);
  const replaceSignals = useSignalStore((state) => state.replaceSignals);

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

  return (
    <WatchlistPage
      signals={signals}
      watchlist={watchlistQuery.data ?? null}
      availablePairs={marketPairsQuery.data ?? []}
      loading={watchlistQuery.isLoading || marketPairsQuery.isLoading}
      busy={addPairMutation.isPending || removePairMutation.isPending}
      onAddPair={(pairId) => addPairMutation.mutateAsync(pairId)}
      onRemovePair={(pairId) => removePairMutation.mutateAsync(pairId)}
    />
  );
}
