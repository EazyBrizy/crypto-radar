"use client";

import { useEffect, useMemo, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  type IPriceLine,
  type ISeriesMarkersPluginApi,
  LineSeries,
  LineStyle,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type SeriesMarker,
  type Time
} from "lightweight-charts";

import type { ChartLineOverlay, ChartRiskLine } from "./chart-overlays";

type ChartMode = "candles" | "line";

export interface ChartPanelProps {
  mode?: ChartMode;
  candles?: CandlestickData<Time>[];
  emaOverlays?: ChartLineOverlay[];
  line?: LineData<Time>[];
  markers?: SeriesMarker<Time>[];
  priceLines?: ChartRiskLine[];
  volume?: HistogramData<Time>[];
  height?: number;
}

export function ChartPanel({
  mode = "candles",
  candles = [],
  emaOverlays = [],
  line = [],
  markers = [],
  priceLines = [],
  volume = [],
  height = 360
}: ChartPanelProps) {
  const orderedCandles = useMemo(() => normalizeSeriesData(candles), [candles]);
  const orderedLine = useMemo(() => normalizeSeriesData(line), [line]);
  const orderedVolume = useMemo(() => normalizeSeriesData(volume), [volume]);
  const orderedEmaOverlays = useMemo(
    () => emaOverlays.map((overlay) => ({ ...overlay, data: normalizeSeriesData(overlay.data) })),
    [emaOverlays]
  );
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceSeriesRef = useRef<ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const overlaySeriesRef = useRef<ISeriesApi<"Line">[]>([]);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#cbd5e1"
      },
      grid: {
        vertLines: { color: "#1f2937" },
        horzLines: { color: "#1f2937" }
      },
      rightPriceScale: {
        borderColor: "#263449"
      },
      timeScale: {
        borderColor: "#263449",
        timeVisible: true
      },
      crosshair: {
        mode: 0
      }
    });

    const priceSeries =
      mode === "candles"
        ? chart.addSeries(CandlestickSeries, {
            upColor: "#22c55e",
            downColor: "#ef4444",
            borderVisible: false,
            wickUpColor: "#22c55e",
            wickDownColor: "#ef4444"
          })
        : chart.addSeries(LineSeries, {
            color: "#60a5fa",
            lineWidth: 2
          });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "#64748b",
      priceFormat: { type: "volume" },
      priceScaleId: ""
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.78,
        bottom: 0
      }
    });

    chartRef.current = chart;
    priceSeriesRef.current = priceSeries;
    volumeSeriesRef.current = volumeSeries;
    markersRef.current = createSeriesMarkers(priceSeries, []);

    const resizeObserver = new ResizeObserver(([entry]) => {
      if (!entry) return;
      chart.resize(Math.round(entry.contentRect.width), height);
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      priceSeriesRef.current = null;
      volumeSeriesRef.current = null;
      overlaySeriesRef.current = [];
      priceLinesRef.current = [];
      markersRef.current = null;
    };
  }, [height, mode]);

  useEffect(() => {
    if (!priceSeriesRef.current) return;
    if (mode === "candles") {
      (priceSeriesRef.current as ISeriesApi<"Candlestick">).setData(orderedCandles);
    } else {
      (priceSeriesRef.current as ISeriesApi<"Line">).setData(orderedLine);
    }
    chartRef.current?.timeScale().fitContent();
  }, [mode, orderedCandles, orderedLine]);

  useEffect(() => {
    volumeSeriesRef.current?.setData(orderedVolume);
  }, [orderedVolume]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    overlaySeriesRef.current.forEach((series) => chart.removeSeries(series));
    overlaySeriesRef.current = orderedEmaOverlays.map((overlay) => {
      const series = chart.addSeries(LineSeries, {
        color: overlay.color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        title: overlay.title
      });
      series.setData(overlay.data);
      return series;
    });
  }, [orderedEmaOverlays]);

  useEffect(() => {
    const series = priceSeriesRef.current;
    if (!series) return;

    priceLinesRef.current.forEach((line) => series.removePriceLine(line));
    priceLinesRef.current = priceLines.map((line) => series.createPriceLine(priceLineOptions(line)));
  }, [priceLines]);

  useEffect(() => {
    markersRef.current?.setMarkers(markers);
  }, [markers]);

  return <div className="chart-panel" ref={containerRef} style={{ height }} />;
}

function priceLineOptions(line: ChartRiskLine) {
  const color = colorForRiskLine(line.role);
  return {
    id: line.id,
    price: line.price,
    color,
    lineWidth: 2 as const,
    lineStyle: line.role === "entry-zone" ? LineStyle.Dashed : LineStyle.Solid,
    axisLabelVisible: true,
    title: line.title,
    axisLabelColor: color,
    axisLabelTextColor: "#020617"
  };
}

function colorForRiskLine(role: ChartRiskLine["role"]): string {
  if (role === "stop-loss") return "#ef4444";
  if (role === "take-profit") return "#22c55e";
  if (role === "entry-zone") return "#f59e0b";
  return "#38bdf8";
}

function normalizeSeriesData<T extends { time: Time }>(data: T[]): T[] {
  const dataByTime = new Map<string, T>();
  for (const item of data) {
    dataByTime.set(timeKey(item.time), item);
  }
  return [...dataByTime.values()].sort((left, right) => compareTime(left.time, right.time));
}

function compareTime(left: Time, right: Time): number {
  return timeValue(left) - timeValue(right);
}

function timeKey(time: Time): string {
  if (typeof time === "number") return `n:${time}`;
  if (typeof time === "string") return `s:${time}`;
  return `d:${time.year}-${time.month}-${time.day}`;
}

function timeValue(time: Time): number {
  if (typeof time === "number") return time;
  if (typeof time === "string") return Date.parse(time) / 1000;
  return Date.UTC(time.year, time.month - 1, time.day) / 1000;
}
