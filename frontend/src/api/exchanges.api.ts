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
    const response = await request(() => openApiClient.GET("/api/v1/exchanges/connections"));
    return response.map(normalizeExchangeConnection);
  },
  async createConnection(draft: ExchangeConnectionDraft): Promise<ExchangeConnection> {
    return normalizeExchangeConnection(
      await request(() =>
        openApiClient.POST("/api/v1/exchanges/connections", {
          body: {
            exchange_code: draft.exchange_code,
            label: draft.label,
            account_type: draft.account_type ?? "spot",
            api_key: draft.api_key ?? null,
            api_secret: draft.api_secret ?? null,
            api_passphrase: draft.api_passphrase ?? null,
            permissions: draft.permissions ?? {},
            environment: draft.environment ?? "testnet",
            order_placement_mode: draft.order_placement_mode ?? "dry_run",
            mainnet_explicitly_enabled: Boolean(draft.mainnet_explicitly_enabled),
            metadata: draft.metadata ?? {}
          } as never
        })
      )
    );
  },
  async updateConnection(connectionId: string, patch: Partial<ExchangeConnectionDraft> & { status?: string }): Promise<ExchangeConnection> {
    return normalizeExchangeConnection(
      await request(() =>
        openApiClient.PATCH("/api/v1/exchanges/connections/{connection_id}", {
          params: { path: { connection_id: connectionId } },
          body: patch as never
        })
      )
    );
  },
  async deleteConnection(connectionId: string): Promise<void> {
    const result = await openApiClient.DELETE("/api/v1/exchanges/connections/{connection_id}", {
      params: { path: { connection_id: connectionId } }
    });
    if (result.error || !result.response.ok) {
      throw new Error(exchangeConnectionDeleteError(result.error, result.response.status));
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
    userId?: string | null,
    forceRefresh = false
  ): Promise<ExchangeWalletBalance> {
    const query: { user_id?: string; force_refresh: boolean } = { force_refresh: forceRefresh };
    if (userId) query.user_id = userId;
    return normalizeExchangeWalletBalance(
      await request(() =>
        openApiClient.GET("/api/v1/exchanges/connections/{connection_id}/wallet-balance", {
          params: {
            path: { connection_id: connectionId },
            query
          }
        })
      )
    );
  },
  async getConnectionAccountSnapshot(
    connectionId: string,
    userId?: string | null,
    forceRefresh = false
  ): Promise<AccountRiskSnapshot> {
    const query: { user_id?: string; force_refresh: boolean } = { force_refresh: forceRefresh };
    if (userId) query.user_id = userId;
    return normalizeAccountRiskSnapshot(
      await request(() =>
        openApiClient.GET("/api/v1/exchanges/connections/{connection_id}/account-snapshot", {
          params: {
            path: { connection_id: connectionId },
            query
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

function exchangeConnectionDeleteError(error: unknown, statusCode: number): string {
  const reasonCode = apiReasonCode(error);
  if (reasonCode === "exchange_connection_not_found") {
    return "Подключение к бирже не найдено.";
  }
  if (reasonCode === "invalid_exchange_connection_id") {
    return "Некорректный идентификатор подключения к бирже.";
  }
  if (reasonCode === "exchange_connection_has_external_history") {
    return "Подключение связано с историческими ордерами или сделками, поэтому физическое удаление недоступно.";
  }
  if (reasonCode === "exchange_connection_hard_delete_protected") {
    return "Физическое удаление доступно только внутреннему администратору.";
  }
  const message = apiErrorMessage(error);
  return message ?? `Не удалось удалить подключение к бирже: HTTP ${statusCode}`;
}

function apiReasonCode(error: unknown): string | null {
  const detail = apiErrorDetail(error);
  if (isRecord(detail) && typeof detail.reason_code === "string") return detail.reason_code;
  return null;
}

function apiErrorMessage(error: unknown): string | null {
  if (isRecord(error) && typeof error.message === "string") return error.message;
  const detail = apiErrorDetail(error);
  if (typeof detail === "string") return detail;
  if (isRecord(detail) && typeof detail.message === "string") return detail.message;
  return null;
}

function apiErrorDetail(error: unknown): unknown {
  return isRecord(error) && "detail" in error ? error.detail : error;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
