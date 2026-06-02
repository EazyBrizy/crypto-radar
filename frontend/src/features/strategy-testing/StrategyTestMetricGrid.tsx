"use client";

import { Metric } from "@/components/Metric";
import type { StrategyTestMetric, StrategyTestMetricValue } from "./types";

interface StrategyTestMetricGridProps {
  emptyLabel?: string;
  limit?: number;
  metrics: StrategyTestMetric[];
}

export function StrategyTestMetricGrid({
  emptyLabel = "No report metrics",
  limit,
  metrics
}: StrategyTestMetricGridProps) {
  const visibleMetrics = limit ? metrics.slice(0, limit) : metrics;

  if (!visibleMetrics.length) {
    return <div className="empty-state compact-empty">{emptyLabel}</div>;
  }

  return (
    <div className="strategy-test-metric-grid">
      {visibleMetrics.map((metric, index) => (
        <Metric
          hint={metricHint(metric)}
          key={`${metric.code ?? metric.name ?? metric.label ?? "metric"}:${index}`}
          label={metric.label ?? metric.name ?? metric.code ?? "metric"}
          value={formatMetricValue(metric.value, metric.unit)}
        />
      ))}
    </div>
  );
}

export function formatMetricValue(value: StrategyTestMetricValue | undefined, unit?: string | null): string {
  if (value == null) return "-";
  if (typeof value === "number") {
    const formatted = Number.isInteger(value) ? String(value) : value.toFixed(3);
    return unit ? `${formatted} ${unit}` : formatted;
  }
  return String(value);
}

function metricHint(metric: StrategyTestMetric): string | undefined {
  const parts: string[] = [];
  if (typeof metric.sample_size === "number") parts.push(`n=${metric.sample_size}`);
  if (metric.warnings?.length) parts.push(metric.warnings[0]);
  return parts.length ? parts.join(" / ") : undefined;
}
