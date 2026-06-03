import type { RadarDisplayMode } from "@/features/server-state/types";
import type { RadarResponse, RadarSignal, VirtualExecutionReport } from "@/types";
import { openApiClient, request } from "./client";
import { normalizeRiskPreviewResponse, normalizeSignal, riskPreviewToExecutionReport } from "./mappers";

type RadarRequestOptions = {
  radarDisplayMode?: RadarDisplayMode | null;
  userId?: string;
};

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
