"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { TradesPage } from "@/features/app-shell/TradesPage";
import { useCloseMarketTradeMutation, useTradeInvalidationQuery, useTradesQuery } from "@/hooks/use-radar-queries";
import { useUiStore } from "@/stores/ui-store";
import type { TradeTab } from "@/stores/ui-store";
import type { TradeCloseReason, TradeJournalEntry } from "@/types";

export function TradesRoute({ tab }: { tab: TradeTab }) {
  const router = useRouter();
  const selectedTradeId = useUiStore((state) => state.selectedTradeId);
  const setSelectedTradeId = useUiStore((state) => state.setSelectedTradeId);
  const [actionError, setActionError] = useState<string | null>(null);
  const [dismissedInvalidations, setDismissedInvalidations] = useState<Set<string>>(() => new Set());
  const tradesQuery = useTradesQuery(
    tab === "active" ? { status: "open" } : tab === "journal" ? { status: "closed" } : { status: "closed" },
    { enabled: tab === "active" || tab === "journal" || tab === "analytics" }
  );
  const closeMarketTradeMutation = useCloseMarketTradeMutation();
  const trades = useMemo(() => tradesQuery.data?.trades ?? [], [tradesQuery.data?.trades]);
  const selectedTrade = useMemo(
    () => trades.find((trade) => trade.id === selectedTradeId) ?? trades.find((trade) => trade.status === "open") ?? null,
    [selectedTradeId, trades]
  );
  const invalidationQuery = useTradeInvalidationQuery(selectedTrade?.id ?? null, {
    enabled: tab === "active" && selectedTrade?.status === "open",
    refetchInterval: 10_000
  });
  const invalidationAlert = (
    invalidationQuery.data?.invalidated && !dismissedInvalidations.has(invalidationQuery.data.trade_id)
  ) ? invalidationQuery.data : null;

  useEffect(() => {
    if (tab !== "active") return;
    if (!trades.length) {
      if (selectedTradeId) setSelectedTradeId(null);
      return;
    }

    if (!selectedTradeId || !trades.some((trade) => trade.id === selectedTradeId)) {
      setSelectedTradeId(trades[0]?.id ?? null);
    }
  }, [selectedTradeId, setSelectedTradeId, tab, trades]);

  const handleCloseMarket = useCallback(async (trade: TradeJournalEntry, reason: TradeCloseReason = "manual_close") => {
    if (trade.status !== "open") return;
    try {
      setActionError(null);
      const result = await closeMarketTradeMutation.mutateAsync({
        id: trade.id,
        mode: trade.mode,
        reason
      });
      if (result.status === "not_implemented") {
        setActionError(result.message);
      }
      await tradesQuery.refetch();
    } catch (exc) {
      setActionError(errorMessage(exc, "Market close failed."));
    }
  }, [closeMarketTradeMutation, tradesQuery]);

  const handleDismissInvalidation = useCallback((tradeId: string) => {
    setDismissedInvalidations((current) => new Set(current).add(tradeId));
  }, []);

  return (
    <TradesPage
      actionError={actionError}
      account={tradesQuery.data?.account ?? null}
      trades={trades}
      activeTab={tab}
      closingTradeId={closeMarketTradeMutation.isPending ? closeMarketTradeMutation.variables?.id ?? null : null}
      invalidationAlert={invalidationAlert}
      selectedTrade={selectedTrade}
      selectedTradeId={selectedTrade?.id ?? selectedTradeId}
      onCloseMarket={handleCloseMarket}
      onDismissInvalidation={handleDismissInvalidation}
      onSelectTrade={(trade) => setSelectedTradeId(trade.id)}
      onTabChange={(nextTab) => router.push(`/dashboard/trades/${nextTab}`)}
    />
  );
}

function errorMessage(exc: unknown, fallback: string): string {
  return exc instanceof Error && exc.message ? exc.message : fallback;
}
