import type { CandleFilters } from "@/features/server-state/query-keys";
import type { CandleResponse } from "@/types";
import { openApiClient, request } from "./client";
import { normalizeCandleResponse } from "./mappers";

export const candlesApi = {
  async list(filters: CandleFilters): Promise<CandleResponse> {
    const response = await request(() =>
      openApiClient.GET("/api/v1/candles", {
        params: {
          query: {
            exchange: filters.exchange,
            symbol: filters.symbol,
            timeframe: filters.timeframe,
            include_open: filters.includeOpen ?? true,
            limit: filters.limit ?? 250
          }
        }
      })
    );
    return normalizeCandleResponse(response.candles);
  }
};
