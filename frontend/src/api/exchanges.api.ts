import type {
  AccountRiskSnapshot,
  ExchangeCatalog,
  ExchangeConnection,
  ExchangeConnectionDraft,
  ExchangeFeeRate,
  ExchangeWalletBalance
} from "@/features/server-state/types";
import { openApiClient, request } from "./client";
import {
  normalizeAccountRiskSnapshot,
  normalizeExchangeCatalog,
  normalizeExchangeConnection,
  normalizeExchangeFeeRate,
  normalizeExchangeWalletBalance
} from "./mappers";

export const exchangesApi = {
  async catalog(): Promise<ExchangeCatalog> {
    const catalog = await request(() => openApiClient.GET("/api/v1/exchanges"));
    return normalizeExchangeCatalog(catalog);
  },
  async connections(): Promise<ExchangeConnection[]> {
    const response = await request(() =>
      openApiClient.GET("/api/v1/exchanges/connections", {
        params: { query: { user_id: "demo_user" } }
      })
    );
    return response.map(normalizeExchangeConnection);
  },
  async createConnection(draft: ExchangeConnectionDraft): Promise<ExchangeConnection> {
    return normalizeExchangeConnection(
      await request(() =>
        openApiClient.POST("/api/v1/exchanges/connections", {
          body: {
            user_id: "demo_user",
            exchange_code: draft.exchange_code,
            label: draft.label,
            account_type: draft.account_type ?? "spot",
            api_key: draft.api_key ?? null,
            api_secret: draft.api_secret ?? null,
            api_passphrase: draft.api_passphrase ?? null,
            permissions: draft.permissions ?? {},
            metadata: draft.metadata ?? {}
          }
        })
      )
    );
  },
  async updateConnection(connectionId: string, patch: Partial<ExchangeConnectionDraft> & { status?: string }): Promise<ExchangeConnection> {
    return normalizeExchangeConnection(
      await request(() =>
        openApiClient.PATCH("/api/v1/exchanges/connections/{connection_id}", {
          params: { path: { connection_id: connectionId } },
          body: patch
        })
      )
    );
  },
  async deleteConnection(connectionId: string): Promise<void> {
    const result = await openApiClient.DELETE("/api/v1/exchanges/connections/{connection_id}", {
      params: { path: { connection_id: connectionId } }
    });
    if (result.error || !result.response.ok) {
      throw new Error(`Exchange connection delete failed: ${result.response.status}`);
    }
  },
  async testConnection(connectionId: string) {
    return request(() =>
      openApiClient.POST("/api/v1/exchanges/connections/{connection_id}/test", {
        params: { path: { connection_id: connectionId } }
      })
    );
  },
  async feeRates(connectionId: string, category = "linear", symbol?: string): Promise<ExchangeFeeRate[]> {
    const response = await request(() =>
      openApiClient.GET("/api/v1/exchanges/connections/{connection_id}/fees", {
        params: {
          path: { connection_id: connectionId },
          query: { category, symbol }
        }
      })
    );
    return response.map(normalizeExchangeFeeRate);
  },
  async getConnectionWalletBalance(
    connectionId: string,
    userId = "demo_user",
    forceRefresh = false
  ): Promise<ExchangeWalletBalance> {
    return normalizeExchangeWalletBalance(
      await request(() =>
        openApiClient.GET("/api/v1/exchanges/connections/{connection_id}/wallet-balance", {
          params: {
            path: { connection_id: connectionId },
            query: { user_id: userId, force_refresh: forceRefresh }
          }
        })
      )
    );
  },
  async getConnectionAccountSnapshot(
    connectionId: string,
    userId = "demo_user",
    forceRefresh = false
  ): Promise<AccountRiskSnapshot> {
    return normalizeAccountRiskSnapshot(
      await request(() =>
        openApiClient.GET("/api/v1/exchanges/connections/{connection_id}/account-snapshot", {
          params: {
            path: { connection_id: connectionId },
            query: { user_id: userId, force_refresh: forceRefresh }
          }
        })
      )
    );
  },
  async syncConnection(connectionId: string) {
    return request(() =>
      openApiClient.POST("/api/v1/exchanges/connections/{connection_id}/sync", {
        params: { path: { connection_id: connectionId } }
      })
    );
  }
};
