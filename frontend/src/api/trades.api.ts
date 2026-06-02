import type { TradeJournalFilters } from "@/features/server-state/query-keys";
import type {
  CloseMarketTradeResponse,
  TradeCloseReason,
  TradeInvalidationActionResponse,
  TradeInvalidationAlert,
  TradeInvalidationUserAction,
  TradeJournalEntry,
  TradeJournalResponse
} from "@/types";
import { API_BASE, API_TIMEOUT_MS, openApiClient, request } from "./client";
import { normalizeTrade, normalizeTradeResponse } from "./mappers";

type RawTradeJournalResponse = {
  trades: Parameters<typeof normalizeTradeResponse>[0];
  account?: unknown;
};

export const tradesApi = {
  async list(filters?: TradeJournalFilters): Promise<TradeJournalResponse> {
    const response = await rawJson<RawTradeJournalResponse>(tradeJournalPath(filters));
    return normalizeTradeResponse(response.trades, response.account);
  },
  async closed(): Promise<TradeJournalResponse> {
    return tradesApi.list({ status: "closed" });
  },
  async closeMarket({
    reason = "manual_close",
    ...trade
  }: Pick<TradeJournalEntry, "id" | "mode"> & { reason?: TradeCloseReason }): Promise<CloseMarketTradeResponse> {
    if (trade.mode === "virtual") {
      const response = await request(() =>
        openApiClient.POST("/api/v1/trades/virtual/{trade_id}/close", {
          params: {
            path: {
              trade_id: trade.id
            }
          },
          body: {
            reason
          }
        })
      );
      return {
        mode: "virtual",
        status: "closed",
        message: reason === "invalidation"
          ? "Virtual position closed at market because the strategy idea was invalidated."
          : "Virtual position closed at market with exit fees applied.",
        trade: normalizeTrade({ ...response, source: "virtual" })
      };
    }

    const response = await request(() =>
      openApiClient.POST("/api/v1/trades/{trade_id}/close-market", {
        params: {
          path: {
            trade_id: trade.id
          }
        },
        body: {
          reason
        }
      })
    );
    return {
      mode: response.mode,
      status: response.status,
      message: response.message,
      trade: response.trade ? normalizeTrade(response.trade) : null
    };
  },
  async invalidation(tradeId: string): Promise<TradeInvalidationAlert> {
    return rawJson<TradeInvalidationAlert>(`/api/v1/trades/${encodeURIComponent(tradeId)}/invalidation`);
  },
  async invalidationAction({
    action,
    tradeId
  }: {
    action: TradeInvalidationUserAction;
    tradeId: string;
  }): Promise<TradeInvalidationActionResponse> {
    return rawJson<TradeInvalidationActionResponse>(`/api/v1/trades/${encodeURIComponent(tradeId)}/invalidation/actions`, {
      body: JSON.stringify({ action }),
      headers: { "content-type": "application/json" },
      method: "POST"
    });
  }
};

function tradeJournalPath(filters?: TradeJournalFilters): string {
  const query = new URLSearchParams();
  appendQuery(query, "mode", filters?.mode);
  appendQuery(query, "source", filters?.source);
  appendQuery(query, "tag", filters?.tag);
  appendQuery(query, "run_id", filters?.runId);
  appendQuery(query, "status", filters?.status);
  appendQuery(query, "signal_id", filters?.signalId);
  const queryString = query.toString();
  return queryString ? `/api/v1/trades?${queryString}` : "/api/v1/trades";
}

function appendQuery(query: URLSearchParams, key: string, value: string | undefined): void {
  if (value) query.set(key, value);
}

async function rawJson<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(apiErrorMessage(data) ?? `API error ${response.status}`);
    }
    return data as T;
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

function apiErrorMessage(value: unknown): string | null {
  if (!value || typeof value !== "object" || !("detail" in value)) return null;
  const detail = (value as { detail?: unknown }).detail;
  return typeof detail === "string" ? detail : null;
}
