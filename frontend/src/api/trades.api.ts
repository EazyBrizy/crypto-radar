import type { TradeJournalFilters } from "@/features/server-state/query-keys";
import type { TradeJournalResponse } from "@/types";
import { openApiClient, request } from "./client";
import { normalizeTradeResponse } from "./mappers";

export const tradesApi = {
  async list(filters?: TradeJournalFilters): Promise<TradeJournalResponse> {
    const response = await request(() =>
      openApiClient.GET("/api/v1/trades", {
        params: {
          query: {
            mode: filters?.mode ?? undefined,
            status: filters?.status ?? undefined,
            signal_id: filters?.signalId ?? undefined
          }
        }
      })
    );
    return normalizeTradeResponse(response.trades, (response as { account?: unknown }).account);
  },
  async closed(): Promise<TradeJournalResponse> {
    return tradesApi.list({ status: "closed" });
  }
};
