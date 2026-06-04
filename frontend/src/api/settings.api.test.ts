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

  it("passes filters to the market universe pairs endpoint", async () => {
    const getSpy = vi.spyOn(openApiClient, "GET").mockResolvedValue({
      data: [],
      error: undefined,
      response: new Response("[]", { status: 200 })
    } as never);

    await settingsApi.marketUniversePairs({
      exchange: "bybit",
      category: "linear",
      quote: "USDT",
      limit: "top_200",
      search: "ETH",
      sort: "turnover_24h_desc",
      liquidity_tier: "medium",
      status: "active/trading"
    });

    expect(getSpy).toHaveBeenCalledWith("/api/v1/market-universe/pairs", {
      params: {
        query: {
          exchange: "bybit",
          category: "linear",
          quote: "USDT",
          limit: "top_200",
          search: "ETH",
          sort: "turnover_24h_desc",
          liquidity_tier: "medium",
          status: "active/trading"
        }
      }
    });
  });

  it("syncs the market universe with default-safe request fields", async () => {
    const postSpy = vi.spyOn(openApiClient, "POST").mockResolvedValue({
      data: {
        category: "linear",
        exchange: "bybit",
        quote: "USDT",
        requested_limit: "top_100",
        skipped_count: 0,
        synced_at: "2026-06-04T00:00:00.000Z",
        synced_count: 100,
        total_available_count: 500,
        warnings: undefined
      },
      error: undefined,
      response: new Response("{}", { status: 200 })
    } as never);

    const response = await settingsApi.syncMarketUniverse({ limit: "top_100" });

    expect(postSpy).toHaveBeenCalledWith("/api/v1/market-universe/sync", {
      body: {
        exchange: "bybit",
        category: "linear",
        quote: "USDT",
        limit: "top_100",
        sort: "turnover_24h_desc",
        persist: true
      }
    });
    expect(response.warnings).toEqual([]);
  });
});
