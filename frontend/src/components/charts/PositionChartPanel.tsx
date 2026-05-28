"use client";

import { useMemo } from "react";

import type { ChartLineOverlay } from "@/components/charts/chart-overlays";
import {
  candlesToChartData,
  mergePositionOverlays,
  signalToChartOverlay,
  tradeToChartOverlay,
  tradeToSimulatedImpactOverlay,
  volumeToChartData
} from "@/components/charts/chart-overlays";
import type { OhlcvCandle, RadarSignal, TradeJournalEntry } from "@/types";
import { ChartPanel } from "./ChartPanel";

interface PositionChartPanelProps {
  candles?: OhlcvCandle[];
  emaOverlays?: ChartLineOverlay[];
  height?: number;
  signal?: RadarSignal | null;
  trade?: TradeJournalEntry | null;
}

export function PositionChartPanel({
  candles = [],
  emaOverlays = [],
  height = 360,
  signal = null,
  trade = null
}: PositionChartPanelProps) {
  const chartCandles = useMemo(() => candlesToChartData(candles), [candles]);
  const chartVolume = useMemo(() => volumeToChartData(candles), [candles]);
  const impactOverlay = useMemo(() => (trade ? tradeToSimulatedImpactOverlay(trade) : null), [trade]);
  const lineOverlays = useMemo(
    () => (impactOverlay ? [...emaOverlays, impactOverlay] : emaOverlays),
    [emaOverlays, impactOverlay]
  );
  const markerTime = chartCandles[chartCandles.length - 1]?.time;
  const overlay = useMemo(
    () =>
      mergePositionOverlays(
        signal ? signalToChartOverlay(signal, markerTime) : { markers: [], priceLines: [] },
        trade ? tradeToChartOverlay(trade, markerTime) : { markers: [], priceLines: [] }
      ),
    [markerTime, signal, trade]
  );

  return (
    <ChartPanel
      candles={chartCandles}
      emaOverlays={lineOverlays}
      height={height}
      markers={overlay.markers}
      priceLines={overlay.priceLines}
      volume={chartVolume}
    />
  );
}
