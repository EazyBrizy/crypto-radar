import type { CandlestickData, HistogramData, LineData, SeriesMarker, Time, UTCTimestamp } from "lightweight-charts";

import type { OhlcvCandle, RadarSignal, TradeJournalEntry } from "@/types";

export type ChartRiskLineRole = "entry" | "entry-zone" | "stop-loss" | "take-profit";

export interface ChartRiskLine {
  id: string;
  price: number;
  role: ChartRiskLineRole;
  title: string;
}

export interface ChartLineOverlay {
  color: string;
  data: LineData<Time>[];
  id: string;
  title: string;
}

export interface PositionChartOverlay {
  markers: SeriesMarker<Time>[];
  priceLines: ChartRiskLine[];
}

export function candlesToChartData(candles: OhlcvCandle[]): CandlestickData<Time>[] {
  return normalizeCandles(candles).map((candle) => ({
    time: toChartTime(candle.open_time),
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close
  }));
}

export function volumeToChartData(candles: OhlcvCandle[]): HistogramData<Time>[] {
  return normalizeCandles(candles).map((candle) => ({
    time: toChartTime(candle.open_time),
    value: candle.volume,
    color: candle.close >= candle.open ? "rgba(34, 197, 94, 0.35)" : "rgba(239, 68, 68, 0.35)"
  }));
}

export function signalToChartOverlay(signal: RadarSignal, markerTime?: Time): PositionChartOverlay {
  const priceLines: ChartRiskLine[] = [
    ...compactRiskLines([
      lineFromNullablePrice("entry-from", signal.entry_min, "entry-zone", "Entry from"),
      lineFromNullablePrice("entry-to", signal.entry_max, "entry-zone", "Entry to"),
      lineFromNullablePrice("sl", signal.stop_loss, "stop-loss", "SL"),
      lineFromNullablePrice("tp1", signal.take_profit_1, "take-profit", "TP1"),
      lineFromNullablePrice("tp2", signal.take_profit_2, "take-profit", "TP2")
    ])
  ];

  return {
    priceLines,
    markers: markerTime ? [signalMarker(signal, markerTime)] : []
  };
}

export function tradeToChartOverlay(trade: TradeJournalEntry, markerTime?: Time): PositionChartOverlay {
  const entryTime = markerTime ?? dateToChartTime(trade.opened_at);
  const exitTime = trade.closed_at ? dateToChartTime(trade.closed_at) : undefined;
  const markers = [
    entryTime ? tradeMarker(trade, entryTime) : null,
    exitTime ? tradeExitMarker(trade, exitTime) : null
  ].filter((marker): marker is SeriesMarker<Time> => marker !== null);

  return {
    priceLines: [
      { id: "entry", price: trade.entry_price, role: "entry", title: "Entry" },
      { id: "sl", price: trade.stop_loss, role: "stop-loss", title: "SL" },
      ...trade.take_profit.map((price, index) => ({
        id: `tp${index + 1}`,
        price,
        role: "take-profit" as const,
        title: `TP${index + 1}`
      }))
    ],
    markers
  };
}

export function mergePositionOverlays(...overlays: PositionChartOverlay[]): PositionChartOverlay {
  return {
    markers: overlays.flatMap((overlay) => overlay.markers),
    priceLines: overlays.flatMap((overlay) => overlay.priceLines)
  };
}

function signalMarker(signal: RadarSignal, time: Time): SeriesMarker<Time> {
  return {
    time,
    position: signal.direction === "long" ? "belowBar" : "aboveBar",
    color: signal.direction === "long" ? "#22c55e" : "#ef4444",
    shape: signal.direction === "long" ? "arrowUp" : "arrowDown",
    text: `${signal.direction.toUpperCase()} ${signal.score}`,
    size: 1.2
  };
}

function tradeMarker(trade: TradeJournalEntry, time: Time): SeriesMarker<Time> {
  return {
    time,
    position: trade.side === "long" ? "belowBar" : "aboveBar",
    color: trade.mode === "real" ? "#38bdf8" : "#a78bfa",
    shape: trade.side === "long" ? "arrowUp" : "arrowDown",
    text: `${trade.side.toUpperCase()} ${formatMarkerPrice(trade.entry_price)}`,
    size: 1.2
  };
}

function formatMarkerPrice(price: number): string {
  if (Math.abs(price) >= 1000) return price.toFixed(0);
  return price.toPrecision(5);
}

function tradeExitMarker(trade: TradeJournalEntry, time: Time): SeriesMarker<Time> {
  return {
    time,
    position: trade.side === "long" ? "aboveBar" : "belowBar",
    color: (trade.pnl ?? 0) >= 0 ? "#22c55e" : "#ef4444",
    shape: "circle",
    text: trade.close_reason ? trade.close_reason.replaceAll("_", " ").toUpperCase() : "CLOSED",
    size: 1.1
  };
}

function lineFromNullablePrice(id: string, price: number | null, role: ChartRiskLineRole, title: string): ChartRiskLine | null {
  return price == null ? null : { id, price, role, title };
}

function compactRiskLines(lines: Array<ChartRiskLine | null>): ChartRiskLine[] {
  return lines.filter((line): line is ChartRiskLine => line !== null);
}

function normalizeCandles(candles: OhlcvCandle[]): OhlcvCandle[] {
  const candlesByOpenTime = new Map<number, OhlcvCandle>();
  for (const candle of candles) {
    candlesByOpenTime.set(candle.open_time, candle);
  }
  return [...candlesByOpenTime.values()].sort((left, right) => left.open_time - right.open_time);
}

function toChartTime(timestampMs: number): UTCTimestamp {
  return Math.floor(timestampMs / 1000) as UTCTimestamp;
}

function dateToChartTime(value: string | null | undefined): UTCTimestamp | undefined {
  if (!value) return undefined;
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return undefined;
  return toChartTime(timestamp);
}
