"use client";

import { useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";

import { TradesPage } from "@/features/app-shell/TradesPage";
import { useTradesQuery } from "@/hooks/use-radar-queries";
import { useUiStore } from "@/stores/ui-store";
import type { TradeTab } from "@/stores/ui-store";

export function TradesRoute({ tab }: { tab: TradeTab }) {
  const router = useRouter();
  const selectedTradeId = useUiStore((state) => state.selectedTradeId);
  const setSelectedTradeId = useUiStore((state) => state.setSelectedTradeId);
  const tradesQuery = useTradesQuery(
    tab === "active" ? { status: "open" } : tab === "journal" ? { status: "closed" } : { status: "closed" },
    { enabled: tab === "active" || tab === "journal" || tab === "analytics" }
  );
  const trades = useMemo(() => tradesQuery.data?.trades ?? [], [tradesQuery.data?.trades]);
  const selectedTrade = useMemo(
    () => trades.find((trade) => trade.id === selectedTradeId) ?? trades.find((trade) => trade.status === "open") ?? null,
    [selectedTradeId, trades]
  );

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

  return (
    <TradesPage
      account={tradesQuery.data?.account ?? null}
      trades={trades}
      activeTab={tab}
      selectedTrade={selectedTrade}
      selectedTradeId={selectedTrade?.id ?? selectedTradeId}
      onSelectTrade={(trade) => setSelectedTradeId(trade.id)}
      onTabChange={(nextTab) => router.push(`/dashboard/trades/${nextTab}`)}
    />
  );
}
