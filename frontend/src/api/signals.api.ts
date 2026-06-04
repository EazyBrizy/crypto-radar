import type { RadarDisplayMode } from "@/features/server-state/types";
import type { PendingEntryIntent, RadarResponse, RadarSignal, VirtualExecutionReport } from "@/types";
import { openApiClient, request, requestJson } from "./client";
import { normalizePendingEntryIntent, normalizeRiskPreviewResponse, normalizeSignal, riskPreviewToExecutionReport } from "./mappers";

type RadarRequestOptions = {
  radarDisplayMode?: RadarDisplayMode | null;
  userId?: string;
};

type PendingEntryInput = {
  signalId: string;
  userId?: string;
};

type RealConfirmInput = {
  signalId: string;
  userId: string;
  connectionId?: string | null;
  waitForConfirmation?: boolean;
};

type PendingEntryIntentDto = Record<string, unknown>;

export const signalsApi = {
  async list(): Promise<RadarSignal[]> {
    const response = await request(() => openApiClient.GET("/api/v1/signals"));
    return response.map(normalizeSignal);
  },
  async active(): Promise<RadarSignal[]> {
    const response = await request(() => openApiClient.GET("/api/v1/signals/active"));
    return response.map(normalizeSignal);
  },
  async open(): Promise<RadarSignal[]> {
    const response = await request(() => openApiClient.GET("/api/v1/signals/open"));
    return response.map(normalizeSignal);
  },
  async historical(): Promise<RadarSignal[]> {
    return signalsApi.list();
  },
  async radar(options: RadarRequestOptions = {}): Promise<RadarResponse> {
    const query: { user_id: string; radar_display_mode?: RadarDisplayMode } = {
      user_id: options.userId ?? "demo_user"
    };
    if (options.radarDisplayMode) {
      query.radar_display_mode = options.radarDisplayMode;
    }
    const response = await request(() =>
      openApiClient.GET("/api/v1/radar", {
        params: { query }
      })
    );
    return { signals: response.signals.map(normalizeSignal) };
  },
  async confirmVirtual(input: string | { signalId: string; waitForConfirmation?: boolean }) {
    const signalId = typeof input === "string" ? input : input.signalId;
    const waitForConfirmation = typeof input === "string" ? false : Boolean(input.waitForConfirmation);
    return request(() =>
      openApiClient.POST("/api/v1/signals/{signal_id}/confirm", {
        params: { path: { signal_id: signalId } },
        body: {
          mode: "virtual",
          user_id: "demo_user",
          auto_enter_on_confirmation: waitForConfirmation,
          account_balance: 100,
          leverage: 3,
          fee_rate: 0,
          slippage_bps: 0,
          simulation_mode: "auto",
          max_virtual_slippage_bps: 150,
          allow_partial_fill: true,
          min_fill_ratio: 0.25,
          max_open_positions: 3
        }
      })
    );
  },
  async confirmReal(input: RealConfirmInput) {
    const body: Record<string, unknown> = {
      mode: "real",
      user_id: input.userId,
      auto_enter_on_confirmation: Boolean(input.waitForConfirmation),
      metadata: {
        source: "radar_real_trade_confirmation_modal",
        ...(input.connectionId ? { connection_id: input.connectionId } : {})
      }
    };
    if (input.connectionId) {
      body.connection_id = input.connectionId;
    }
    return requestJson<unknown>(
      `/api/v1/signals/${encodeURIComponent(input.signalId)}/confirm`,
      {
        method: "POST",
        body: JSON.stringify(body)
      }
    );
  },
  async pendingEntry(signalId: string, userId = "demo_user"): Promise<PendingEntryIntent | null> {
    const params = new URLSearchParams({ user_id: userId });
    const response = await requestJson<PendingEntryIntentDto | null>(
      `/api/v1/signals/${encodeURIComponent(signalId)}/pending-entry?${params.toString()}`
    );
    return response ? normalizePendingEntryIntent(response) : null;
  },
  async pendingEntryHistory(signalId: string, userId = "demo_user"): Promise<PendingEntryIntent[]> {
    const params = new URLSearchParams({ user_id: userId });
    const response = await requestJson<PendingEntryIntentDto[]>(
      `/api/v1/signals/${encodeURIComponent(signalId)}/pending-entry/history?${params.toString()}`
    );
    return response.map(normalizePendingEntryIntent);
  },
  async armPendingEntry(input: PendingEntryInput): Promise<PendingEntryIntent> {
    const response = await requestJson<PendingEntryIntentDto>(
      `/api/v1/signals/${encodeURIComponent(input.signalId)}/pending-entry`,
      {
        method: "POST",
        body: JSON.stringify(pendingEntryRequest(input.userId))
      }
    );
    return normalizePendingEntryIntent(response);
  },
  async cancelPendingEntry(input: { intentId: string; userId?: string }): Promise<PendingEntryIntent> {
    const response = await requestJson<PendingEntryIntentDto>(
      `/api/v1/pending-entry/${encodeURIComponent(input.intentId)}/cancel`,
      {
        method: "POST",
        body: JSON.stringify({ user_id: input.userId ?? "demo_user" })
      }
    );
    return normalizePendingEntryIntent(response);
  },
  async reconfirmPendingEntry(input: { intentId: string; userId?: string }): Promise<PendingEntryIntent> {
    const response = await requestJson<PendingEntryIntentDto>(
      `/api/v1/pending-entry/${encodeURIComponent(input.intentId)}/reconfirm`,
      {
        method: "POST",
        body: JSON.stringify(pendingEntryRequest(input.userId))
      }
    );
    return normalizePendingEntryIntent(response);
  },
  async executionPreview(signalId: string): Promise<VirtualExecutionReport> {
    const response = await request(() =>
      openApiClient.POST("/api/v1/risk/preview", {
        body: {
          signal_id: signalId,
          mode: "virtual",
          user_id: "demo_user",
          instrument_type: "futures",
          account_balance: 100,
          leverage: 3,
          fee_rate: 0,
          slippage_bps: 0
        }
      })
    );
    const preview = normalizeRiskPreviewResponse(response);
    if (!preview) throw new Error("API returned an empty risk preview");
    return riskPreviewToExecutionReport(preview);
  },
  async reject(signalId: string) {
    return request(() =>
      openApiClient.POST("/api/v1/signals/{signal_id}/reject", {
        params: { path: { signal_id: signalId } },
        body: { reason: "Отклонено пользователем во frontend" }
      })
    );
  }
};

function pendingEntryRequest(userId = "demo_user") {
  return {
    mode: "virtual",
    user_id: userId,
    auto_enter_on_confirmation: true,
    account_balance: 100,
    leverage: 3,
    fee_rate: 0,
    slippage_bps: 0,
    simulation_mode: "auto",
    max_virtual_slippage_bps: 150,
    allow_partial_fill: true,
    min_fill_ratio: 0.25,
    max_open_positions: 3
  };
}
