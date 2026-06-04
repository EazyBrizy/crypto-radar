import { afterEach, describe, expect, it, vi } from "vitest";

import { openApiClient } from "./client";
import { settingsApi } from "./settings.api";

describe("settingsApi.marketPairs", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("passes market universe filters to the legacy market-pairs endpoint", async () => {
    const getSpy = vi.spyOn(openApiClient, "GET").mockResolvedValue({
      data: [],
      error: undefined,
      response: new Response("[]", { status: 200 })
    } as never);

    await settingsApi.marketPairs({
      exchange: "bybit",
      category: "linear",
      quote: "USDT",
      limit: "top_100",
      search: "BTC",
      sort: "turnover_24h_desc",
      liquidity_tier: "high",
      status: "active/trading"
    });

    expect(getSpy).toHaveBeenCalledWith("/api/v1/market-pairs", {
      params: {
        query: {
          exchange: "bybit",
          category: "linear",
          quote: "USDT",
          limit: "top_100",
          search: "BTC",
          sort: "turnover_24h_desc",
          liquidity_tier: "high",
          status: "active/trading"
        }
      }
    });
  });
});
