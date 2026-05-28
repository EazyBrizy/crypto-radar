import { describe, expect, it } from "vitest";

import type { OhlcvCandle } from "@/types";
import { candlesToChartData, volumeToChartData } from "./chart-overlays";

const baseCandle: OhlcvCandle = {
  exchange: "bybit",
  symbol: "ETHUSDT",
  timeframe: "1m",
  open_time: 1_779_796_800_000,
  close_time: 1_779_796_859_999,
  open: 2_100,
  high: 2_120,
  low: 2_090,
  close: 2_110,
  volume: 100,
  trades: 10,
  is_closed: true
};

describe("chart overlay data normalization", () => {
  it("sorts candles and keeps one item per chart time", () => {
    const candles = [
      { ...baseCandle, open_time: baseCandle.open_time + 60_000, close: 2_130 },
      baseCandle,
      { ...baseCandle, close: 2_115, volume: 120, is_closed: false }
    ];

    const chartData = candlesToChartData(candles);
    const volumeData = volumeToChartData(candles);

    expect(chartData.map((item) => item.time)).toEqual([1_779_796_800, 1_779_796_860]);
    expect(chartData[0]?.close).toBe(2_115);
    expect(volumeData.map((item) => item.time)).toEqual([1_779_796_800, 1_779_796_860]);
    expect(volumeData[0]?.value).toBe(120);
  });
});
