import type { TradeJournalFilters } from "@/features/server-state/query-keys";
import type { CloseMarketTradeResponse, TradeJournalEntry, TradeJournalResponse } from "@/types";
import { openApiClient, request } from "./client";
import { normalizeTrade, normalizeTradeResponse } from "./mappers";

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
  },
  async closeMarket(trade: Pick<TradeJournalEntry, "id" | "mode">): Promise<CloseMarketTradeResponse> {
    if (trade.mode === "virtual") {
      const response = await request(() =>
        openApiClient.POST("/api/v1/trades/virtual/{trade_id}/close", {
          params: {
            path: {
              trade_id: trade.id
            }
          },
          body: {
            reason: "manual_close"
          }
        })
      );
      return {
        mode: "virtual",
        status: "closed",
        message: "Virtual position closed at market with exit fees applied.",
        trade: normalizeTrade(response)
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
          reason: "manual_close"
        }
      })
    );
    return {
      mode: response.mode,
      status: response.status,
      message: response.message,
      trade: response.trade ? normalizeTrade(response.trade) : null
    };
  }
};
