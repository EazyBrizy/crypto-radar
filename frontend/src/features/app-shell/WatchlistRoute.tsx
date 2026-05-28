"use client";

import { useEffect, useMemo } from "react";

import { WatchlistPage } from "@/features/app-shell/WatchlistPage";
import {
  useActiveSignalsQuery,
  useAddWatchlistPairMutation,
  useMarketPairsQuery,
  useRemoveWatchlistPairMutation,
  useWatchlistQuery
} from "@/hooks/use-radar-queries";
import { useSignalStore } from "@/stores/signal-store";

export function WatchlistRoute() {
  const activeSignalsQuery = useActiveSignalsQuery();
  const watchlistQuery = useWatchlistQuery();
  const marketPairsQuery = useMarketPairsQuery();
  const addPairMutation = useAddWatchlistPairMutation();
  const removePairMutation = useRemoveWatchlistPairMutation();
  const signalIds = useSignalStore((state) => state.signalIds);
  const signalsById = useSignalStore((state) => state.signalsById);
  const replaceSignals = useSignalStore((state) => state.replaceSignals);

  useEffect(() => {
    if (activeSignalsQuery.data) replaceSignals(activeSignalsQuery.data);
  }, [activeSignalsQuery.data, replaceSignals]);

  const signals = useMemo(
    () => signalIds.map((signalId) => signalsById[signalId]).filter(Boolean),
    [signalIds, signalsById]
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
