import type {
  AlertRule,
  AlertRuleDraft,
  MarketPairOption,
  MarketUniversePair,
  MarketUniversePairsQuery,
  MarketUniverseSyncRequest,
  MarketUniverseSyncResponse,
  StrategyConfig,
  StrategyConfigPatch,
  SubscriptionStatus,
  UserProfile,
  UserSettingsPatch,
  Watchlist
} from "@/features/server-state/types";
import type { RadarConfig, RadarStatus, RiskStateResponse } from "@/types";
import { billingApi } from "./billing.api";
import { openApiClient, request, requestJson } from "./client";
import {
  normalizeAlertRule,
  normalizeConfig,
  normalizeHealth,
  normalizeMarketPair,
  normalizeMarketUniversePair,
  normalizeRadarStatus,
  normalizeRiskState,
  normalizeStrategyConfig,
  normalizeUserProfile,
  normalizeWatchlistResponse,
} from "./mappers";

export type MarketPairsQuery = MarketUniversePairsQuery;

export const settingsApi = {
  async config(): Promise<RadarConfig> {
    return normalizeConfig(await request(() => openApiClient.GET("/api/v1/radar/config")));
  },
  async settings(): Promise<RadarConfig> {
    return settingsApi.config();
  },
  async watchlist(): Promise<Watchlist> {
    return normalizeWatchlistResponse(await request(() => openApiClient.GET("/api/v1/watchlists/default")));
  },
  async marketPairs(query: MarketPairsQuery = {}): Promise<MarketPairOption[]> {
    const params = marketUniverseQueryParams(query);
    const response = await request(() =>
      openApiClient.GET(
        "/api/v1/market-pairs",
        Object.keys(params).length ? { params: { query: params } } : undefined
      )
    );
    return response.map(normalizeMarketPair);
  },
  async marketUniversePairs(params: MarketUniversePairsQuery = {}): Promise<MarketUniversePair[]> {
    const query = marketUniverseQueryParams(params);
    const response = await request(() =>
      openApiClient.GET(
        "/api/v1/market-universe/pairs",
        Object.keys(query).length ? { params: { query } } : undefined
      )
    );
    return response.map(normalizeMarketUniversePair);
  },
  async syncMarketUniverse(body: MarketUniverseSyncRequest = {}): Promise<MarketUniverseSyncResponse> {
    const response = await request(() =>
      openApiClient.POST("/api/v1/market-universe/sync", {
        body: {
          exchange: body.exchange ?? "bybit",
          category: body.category ?? "linear",
          quote: body.quote ?? "USDT",
          limit: body.limit ?? "top_200",
          sort: body.sort ?? "turnover_24h_desc",
          persist: body.persist ?? true
        }
      })
    );
    return {
      ...response,
      warnings: response.warnings ?? []
    };
  },
  async strategyConfigs(): Promise<StrategyConfig[]> {
    const response = await fetchJson<unknown[]>("/api/v1/strategies/configs?user_id=demo_user");
    return response.map(normalizeStrategyConfig);
  },
  async updateStrategyConfig(configId: string, patch: StrategyConfigPatch): Promise<StrategyConfig> {
    return normalizeStrategyConfig(
      await fetchJson(`/api/v1/strategies/configs/${encodeURIComponent(configId)}`, {
        method: "PATCH",
        body: JSON.stringify({ user_id: "demo_user", ...patch })
      })
    );
  },
  async addWatchlistPair(pairId: string): Promise<Watchlist> {
    return normalizeWatchlistResponse(
      await request(() =>
        openApiClient.POST("/api/v1/watchlists/default/pairs", {
          body: {
            user_id: "demo_user",
            pair_id: pairId
          }
        })
      )
    );
  },
  async removeWatchlistPair(pairId: string): Promise<Watchlist> {
    return normalizeWatchlistResponse(
      await request(() =>
        openApiClient.DELETE("/api/v1/watchlists/default/pairs/{pair_id}", {
          params: {
            path: { pair_id: pairId },
            query: { user_id: "demo_user" }
          }
        })
      )
    );
  },
  async alertRules(): Promise<AlertRule[]> {
    const response = await request(() =>
      openApiClient.GET("/api/v1/alerts", {
        params: { query: { user_id: "demo_user" } }
      })
    );
    return response.map(normalizeAlertRule);
  },
  async createAlertRule(draft: AlertRuleDraft): Promise<AlertRule> {
    return normalizeAlertRule(
      await request(() =>
        openApiClient.POST("/api/v1/alerts", {
          body: {
            user_id: "demo_user",
            pair_id: draft.pair_id ?? null,
            strategy_version_id: draft.strategy_version_id ?? null,
            condition_type: draft.condition_type,
            condition_body: draft.condition_body,
            channels: draft.channels ?? ["websocket"],
            is_enabled: draft.is_enabled ?? true
          }
        })
      )
    );
  },
  async updateAlertRule(alertId: string, patch: Partial<AlertRuleDraft>): Promise<AlertRule> {
    return normalizeAlertRule(
      await request(() =>
        openApiClient.PATCH("/api/v1/alerts/{alert_id}", {
          params: { path: { alert_id: alertId } },
          body: patch
        })
      )
    );
  },
  async deleteAlertRule(alertId: string): Promise<void> {
    await openApiClient.DELETE("/api/v1/alerts/{alert_id}", {
      params: { path: { alert_id: alertId } }
    });
  },
  async testAlertRule(alertId: string) {
    return request(() =>
      openApiClient.POST("/api/v1/alerts/{alert_id}/test", {
        params: { path: { alert_id: alertId } }
      })
    );
  },
  async health() {
    return normalizeHealth(await request(() => openApiClient.GET("/health")));
  },
  async radarStatus(): Promise<RadarStatus> {
    return normalizeRadarStatus(await request(() => openApiClient.GET("/api/v1/radar/status")));
  },
  async startScanner() {
    return normalizeHealth(await request(() => openApiClient.POST("/api/v1/radar/scanner/start")));
  },
  async stopScanner() {
    return normalizeHealth(await request(() => openApiClient.POST("/api/v1/radar/scanner/stop")));
  },
  async userProfile(): Promise<UserProfile> {
    return normalizeUserProfile(
      await request(() =>
        openApiClient.GET("/api/v1/users/me", {
          params: { query: { user_id: "demo_user" } }
        })
      )
    );
  },
  async updateUserSettings(patch: UserSettingsPatch): Promise<UserProfile> {
    return normalizeUserProfile(
      await request(() =>
        openApiClient.PATCH("/api/v1/users/me/settings", {
          params: { query: { user_id: "demo_user" } },
          body: patch
        })
      )
    );
  },
  async riskState(): Promise<RiskStateResponse> {
    const state = normalizeRiskState(
      await request(() =>
        openApiClient.GET("/api/v1/risk/state", {
          params: { query: { user_id: "demo_user" } }
        })
      )
    );
    if (!state) throw new Error("API returned an empty risk state");
    return state;
  },
  async subscriptionStatus(): Promise<SubscriptionStatus> {
    return billingApi.subscription();
  }
};

function marketUniverseQueryParams(query: MarketUniversePairsQuery): Partial<MarketUniversePairsQuery> {
  return Object.fromEntries(
    Object.entries(query).filter(([, value]) => value !== undefined && value !== null && value !== "")
  ) as Partial<MarketUniversePairsQuery>;
}

async function fetchJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  return requestJson<T>(path, init);
}
