import type { HealthStatus, RadarConfig, RadarResponse, RadarSignal, TradeJournalResponse } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...options?.headers
    },
    ...options
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `API error ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthStatus>("/health"),
  radar: () => request<RadarResponse>("/api/v1/radar"),
  signals: () => request<RadarSignal[]>("/api/v1/signals"),
  confirmVirtual: (signalId: string) =>
    request(`/api/v1/signals/${signalId}/confirm`, {
      method: "POST",
      body: JSON.stringify({
        mode: "virtual",
        account_balance: 10_000,
        risk_percent: 1,
        leverage: 2
      })
    }),
  rejectSignal: (signalId: string) =>
    request(`/api/v1/signals/${signalId}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason: "Отклонено пользователем во frontend" })
    }),
  trades: () => request<TradeJournalResponse>("/api/v1/trades"),
  config: () => request<RadarConfig>("/api/v1/radar/config")
};
