"use client";

import { PositionChartPanel } from "@/components/charts/PositionChartPanel";
import { useCandlesQuery } from "@/hooks/use-radar-queries";
import type { RadarSignal, Timeframe } from "@/types";

interface SignalDetailsChartProps {
  signal: RadarSignal;
}

export function SignalDetailsChart({ signal }: SignalDetailsChartProps) {
  const candlesQuery = useCandlesQuery(
    {
      exchange: signal.exchange,
      limit: 180,
      symbol: signal.symbol,
      timeframe: normalizeTimeframe(signal.timeframe)
    },
    { enabled: Boolean(signal.symbol) }
  );

  return (
    <PositionChartPanel
      candles={candlesQuery.data?.candles ?? []}
      height={320}
      signal={signal}
    />
  );
}

function normalizeTimeframe(timeframe: string): Timeframe {
  if (timeframe === "1m" || timeframe === "5m" || timeframe === "15m" || timeframe === "1h" || timeframe === "4h" || timeframe === "1d") {
    return timeframe;
  }
  return "15m";
}
