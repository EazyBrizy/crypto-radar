import type { RadarDisplayMode } from "@/features/server-state/types";
import type {
  PendingEntryIntent,
  RadarResponse,
  RadarSignal,
  SignalActionBlocker,
  SignalActionKind,
  SignalActionMode,
  SignalActionResponse,
  SignalActionState,
  VirtualExecutionReport
} from "@/types";
import { openApiClient, request, requestJson } from "./client";
import type { PendingEntryIntentReadDto } from "./generated/schemas";
import { normalizePendingEntryIntent, normalizeRiskPreviewResponse, normalizeSignal, riskPreviewToExecutionReport } from "./mappers";

type RadarRequestOptions = {
  radarDisplayMode?: RadarDisplayMode | null;
  userId?: string | null;
};

type PendingEntryInput = {
  signalId: string;
  mode?: SignalActionMode;
  connectionId?: string | null;
};

type PendingEntryListScope = "active" | "history";

type RealConfirmInput = {
  signalId: string;
  connectionId?: string | null;
  waitForConfirmation?: boolean;
};

type SignalActionInput = {
  kind: SignalActionKind;
  mode: SignalActionMode;
  connectionId?: string | null;
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
  async getSignalActionState(signalId: string, mode: SignalActionMode = "virtual", connectionId?: string | null): Promise<SignalActionState> {
    const params = new URLSearchParams({ mode });
    if (connectionId) params.set("connection_id", connectionId);
    const response = await requestJson<unknown>(
      `/api/v1/signals/${encodeURIComponent(signalId)}/action-state?${params.toString()}`
    );
    return normalizeSignalActionState(response);
  },
  async sendSignalAction(signalId: string, input: SignalActionInput): Promise<SignalActionResponse> {
    const body: Record<string, unknown> = {
      kind: input.kind,
      mode: input.mode
    };
    if (input.connectionId) {
      body.connection_id = input.connectionId;
    }
    const response = await requestJson<unknown>(
      `/api/v1/signals/${encodeURIComponent(signalId)}/actions`,
      {
        method: "POST",
        body: JSON.stringify(body)
      }
    );
    return normalizeSignalActionResponse(response);
  },
  async radar(options: RadarRequestOptions = {}): Promise<RadarResponse> {
    const query: { user_id?: string; radar_display_mode?: RadarDisplayMode } = {};
    if (options.userId) {
      query.user_id = options.userId;
    }
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
    return signalsApi.sendSignalAction(signalId, {
      kind: waitForConfirmation ? "arm_pending_entry" : "enter_now",
      mode: "virtual"
    });
  },
  async confirmReal(input: RealConfirmInput) {
    return signalsApi.sendSignalAction(input.signalId, {
      kind: input.waitForConfirmation ? "arm_pending_entry" : "enter_now",
      mode: "real",
      connectionId: input.connectionId
    });
  },
  async pendingEntry(signalId: string, userId?: string | null): Promise<PendingEntryIntent | null> {
    const params = userQuery({ userId });
    const response = await requestJson<PendingEntryIntentReadDto | null>(
      `/api/v1/signals/${encodeURIComponent(signalId)}/pending-entry${querySuffix(params)}`
    );
    return response ? normalizePendingEntryIntent(response) : null;
  },
  async pendingEntryHistory(signalId: string, userId?: string | null): Promise<PendingEntryIntent[]> {
    const params = userQuery({ userId });
    const response = await requestJson<PendingEntryIntentReadDto[]>(
      `/api/v1/signals/${encodeURIComponent(signalId)}/pending-entry/history${querySuffix(params)}`
    );
    return response.map(normalizePendingEntryIntent);
  },
  async pendingEntries(options: { userId?: string | null; scope?: PendingEntryListScope; limit?: number } = {}): Promise<PendingEntryIntent[]> {
    const params = userQuery({ userId: options.userId });
    params.set("scope", options.scope ?? "active");
    if (options.limit) params.set("limit", String(options.limit));
    const response = await requestJson<PendingEntryIntentReadDto[]>(
      `/api/v1/pending-entry${querySuffix(params)}`
    );
    return response.map(normalizePendingEntryIntent);
  },
  async armPendingEntry(input: PendingEntryInput): Promise<PendingEntryIntent> {
    const response = await signalsApi.sendSignalAction(input.signalId, {
      kind: "arm_pending_entry",
      mode: input.mode ?? "virtual",
      connectionId: input.connectionId
    });
    if (!response.pending_entry_intent) throw new Error("API returned no pending entry intent");
    return response.pending_entry_intent;
  },
  async cancelPendingEntry(input: { signalId: string; mode?: SignalActionMode; connectionId?: string | null }): Promise<PendingEntryIntent> {
    const response = await signalsApi.sendSignalAction(input.signalId, {
      kind: "cancel_pending_entry",
      mode: input.mode ?? "virtual",
      connectionId: input.connectionId
    });
    if (!response.pending_entry_intent) throw new Error("API returned no pending entry intent");
    return response.pending_entry_intent;
  },
  async reconfirmPendingEntry(input: { signalId: string; mode?: SignalActionMode; connectionId?: string | null }): Promise<PendingEntryIntent> {
    const response = await signalsApi.sendSignalAction(input.signalId, {
      kind: "reconfirm_pending_entry",
      mode: input.mode ?? "virtual",
      connectionId: input.connectionId
    });
    if (!response.pending_entry_intent) throw new Error("API returned no pending entry intent");
    return response.pending_entry_intent;
  },
  async executionPreview(signalId: string): Promise<VirtualExecutionReport> {
    const response = await requestJson<unknown>(
      `/api/v1/signals/${encodeURIComponent(signalId)}/execution-preview`,
      { method: "POST" }
    );
    if (isVirtualExecutionReport(response)) {
      return response as VirtualExecutionReport;
    }
    const preview = normalizeRiskPreviewResponse(response);
    if (!preview) throw new Error("API returned an empty execution preview");
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

function userQuery({ userId }: { userId?: string | null }) {
  const params = new URLSearchParams();
  if (userId) params.set("user_id", userId);
  return params;
}

function querySuffix(params: URLSearchParams) {
  const query = params.toString();
  return query ? `?${query}` : "";
}

function normalizeSignalActionResponse(value: unknown): SignalActionResponse {
  const payload = isRecord(value) ? value : {};
  return {
    state: normalizeSignalActionState(payload.state),
    signal: normalizeSignal(payload.signal as never),
    virtual_trade: payload.virtual_trade ?? null,
    real_execution: payload.real_execution ?? null,
    real_execution_result: payload.real_execution_result ?? payload.real_execution ?? null,
    pending_entry_intent: payload.pending_entry_intent ? normalizePendingEntryIntent(payload.pending_entry_intent) : null,
    message: String(payload.message ?? "")
  };
}

function normalizeSignalActionState(value: unknown): SignalActionState {
  const state = isRecord(value) ? value : {};
  return {
    can_enter_now: Boolean(state.can_enter_now),
    can_arm_pending: Boolean(state.can_arm_pending),
    can_reconfirm: Boolean(state.can_reconfirm),
    can_cancel: Boolean(state.can_cancel),
    mode: state.mode === "real" ? "real" : "virtual",
    environment: String(state.environment ?? (state.mode === "real" ? "real_unresolved" : "virtual")),
    primary_action: normalizeSignalActionKind(state.primary_action),
    disabled_reason_code: optionalString(state.disabled_reason_code),
    blockers: normalizeSignalActionBlockers(state.blockers),
    warnings: normalizeSignalActionBlockers(state.warnings),
    accepted_trade_plan_snapshot: isRecord(state.accepted_trade_plan_snapshot) ? { ...state.accepted_trade_plan_snapshot } : null,
    display_labels: isRecord(state.display_labels)
      ? Object.fromEntries(Object.entries(state.display_labels).map(([key, label]) => [key, String(label)]))
      : {}
  };
}

function normalizeSignalActionBlockers(value: unknown): SignalActionBlocker[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((item) => ({
    code: String(item.code ?? "action_unavailable"),
    severity: item.severity === "warning" || item.severity === "info" ? item.severity : "blocker",
    message: optionalString(item.message),
    display_label: optionalString(item.display_label),
    metadata: isRecord(item.metadata) ? { ...item.metadata } : {}
  }));
}

function normalizeSignalActionKind(value: unknown): SignalActionKind | null {
  if (
    value === "enter_now" ||
    value === "arm_pending_entry" ||
    value === "cancel_pending_entry" ||
    value === "reconfirm_pending_entry"
  ) {
    return value;
  }
  return null;
}

function isVirtualExecutionReport(value: unknown): value is VirtualExecutionReport {
  return isRecord(value) && "quality_gate" in value && "liquidity" in value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}
