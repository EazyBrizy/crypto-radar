import type { AlertRule, AlertRuleDraft, MarketPairOption, SubscriptionStatus, UserProfile, Watchlist } from "@/features/server-state/types";
import type { RadarConfig, RadarStatus } from "@/types";
import { billingApi } from "./billing.api";
import { openApiClient, request } from "./client";
import {
  normalizeAlertRule,
  normalizeConfig,
  normalizeHealth,
  normalizeMarketPair,
  normalizeRadarStatus,
  normalizeUserProfile,
  normalizeWatchlistResponse,
} from "./mappers";

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
  async marketPairs(): Promise<MarketPairOption[]> {
    const response = await request(() => openApiClient.GET("/api/v1/market-pairs"));
    return response.map(normalizeMarketPair);
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
  async subscriptionStatus(): Promise<SubscriptionStatus> {
    return billingApi.subscription();
  }
};
