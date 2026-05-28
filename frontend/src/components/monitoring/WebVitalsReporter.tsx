"use client";

import { useReportWebVitals } from "next/web-vitals";
import type { Metric } from "web-vitals";

export function WebVitalsReporter() {
  useReportWebVitals((metric) => {
    reportWebVital(metric as Metric);
  });

  return null;
}

function reportWebVital(metric: Metric) {
  const endpoint = process.env.NEXT_PUBLIC_WEB_VITALS_ENDPOINT;
  const payload = JSON.stringify({
    id: metric.id,
    name: metric.name,
    value: metric.value,
    rating: metric.rating,
    navigationType: metric.navigationType
  });

  if (endpoint && navigator.sendBeacon) {
    navigator.sendBeacon(endpoint, payload);
    return;
  }

  if (process.env.NODE_ENV === "development") {
    console.debug("[web-vitals]", payload);
  }
}
