import type { TradeJournalFilters } from "@/features/server-state/query-keys";
import type { TradeJournalResponse } from "@/types";
import { tradesApi } from "./trades.api";

export const journalApi = {
  async history(filters?: TradeJournalFilters): Promise<TradeJournalResponse> {
    return tradesApi.list(filters);
  }
};
