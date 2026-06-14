import { afterEach, describe, expect, it, vi } from "vitest";

import { openApiClient } from "./client";
import { signalsApi } from "./signals.api";

describe("signalsApi.radar", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("passes user_id and radar_display_mode to the Radar endpoint", async () => {
    const getSpy = vi.spyOn(openApiClient, "GET").mockResolvedValue({
      data: { signals: [], summary: radarSummary() },
      error: undefined,
      response: new Response("{}", { status: 200 })
    } as never);

    await signalsApi.radar({
      radarDisplayMode: "execution_ready",
      userId: "user_1"
    });

    expect(getSpy).toHaveBeenCalledWith("/api/v1/radar", {
      params: {
        query: {
          user_id: "user_1",
          radar_display_mode: "execution_ready"
        }
      }
    });
  });
});

describe("signalsApi.armPendingEntry", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("sends only action intent for pending-entry requests", async () => {
    const fetchSpy = vi.fn(async (...args: Parameters<typeof fetch>) => {
      void args;
      return new Response(JSON.stringify({
        state: actionState({ primary_action: "arm_pending_entry" }),
        signal: signalDto(),
        pending_entry_intent: pendingEntryIntentDto(),
        message: "Pending entry armed"
      }), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    });
    vi.stubGlobal("fetch", fetchSpy);

    await signalsApi.armPendingEntry({ signalId: "sig_1" });

    const [, init] = fetchSpy.mock.calls[0];
    const body = JSON.parse(String(init?.body));
    expect(body).toMatchObject({ kind: "arm_pending_entry", mode: "virtual" });
    expectActionBodyOnlyIntent(body);
  });
});

describe("signalsApi.confirmReal", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("sends an explicit real confirmation without account balance override", async () => {
    const fetchSpy = vi.fn(async (...args: Parameters<typeof fetch>) => {
      void args;
      return new Response(JSON.stringify({
        state: actionState({ primary_action: "arm_pending_entry", mode: "real" }),
        signal: signalDto(),
        message: "ok"
      }), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    });
    vi.stubGlobal("fetch", fetchSpy);

    await signalsApi.confirmReal({
      signalId: "sig_1",
      connectionId: "conn_1",
      waitForConfirmation: true
    });

    const [, init] = fetchSpy.mock.calls[0];
    const body = JSON.parse(String(init?.body));
    expect(body).toMatchObject({
      kind: "arm_pending_entry",
      mode: "real",
      connection_id: "conn_1"
    });
    expectActionBodyOnlyIntent(body);
  });
});

describe("signalsApi.realExecutionPreview", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("posts real preview mode and connection id without using the virtual preview contract", async () => {
    const fetchSpy = vi.fn(async (...args: Parameters<typeof fetch>) => {
      void args;
      return new Response(JSON.stringify(realExecutionResultDto({
        connection_id: "conn_1",
        status: "preview"
      })), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    });
    vi.stubGlobal("fetch", fetchSpy);

    const result = await signalsApi.realExecutionPreview({
      signalId: "sig_1",
      connectionId: "conn_1"
    });

    const [url, init] = fetchSpy.mock.calls[0];
    const body = JSON.parse(String(init?.body));
    expect(String(url)).toContain("/api/v1/signals/sig_1/execution-preview");
    expect(init?.method).toBe("POST");
    expect(body).toEqual({
      mode: "real",
      connection_id: "conn_1"
    });
    expect(result).toMatchObject({
      mode: "real",
      status: "preview",
      connection_id: "conn_1"
    });
  });
});

describe("signalsApi.pendingEntry", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("returns null when the active pending-entry endpoint has no active intent", async () => {
    const fetchSpy = vi.fn(async (...args: Parameters<typeof fetch>) => {
      void args;
      return new Response("null", {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    });
    vi.stubGlobal("fetch", fetchSpy);

    const result = await signalsApi.pendingEntry("sig_1", "user_1");

    expect(result).toBeNull();
    expect(String(fetchSpy.mock.calls[0][0])).toContain("/api/v1/signals/sig_1/pending-entry?user_id=user_1");
  });
});

describe("signalsApi.pendingEntryHistory", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads terminal pending-entry history records from the history endpoint", async () => {
    const fetchSpy = vi.fn(async (...args: Parameters<typeof fetch>) => {
      void args;
      return new Response(JSON.stringify([
        {
          ...pendingEntryIntentDto(),
          id: "intent_cancelled",
          status: "cancelled",
          updated_at: "2026-06-04T12:00:00.000Z"
        }
      ]), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    });
    vi.stubGlobal("fetch", fetchSpy);

    const result = await signalsApi.pendingEntryHistory("sig_1");

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ id: "intent_cancelled", status: "cancelled" });
    expect(String(fetchSpy.mock.calls[0][0])).toContain("/api/v1/signals/sig_1/pending-entry/history");
    expect(String(fetchSpy.mock.calls[0][0])).not.toContain("user_id=");
  });
});

describe("signalsApi.pendingEntries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads user-level active pending-entry queue", async () => {
    const fetchSpy = vi.fn(async (...args: Parameters<typeof fetch>) => {
      void args;
      return new Response(JSON.stringify([
        {
          ...pendingEntryIntentDto(),
          id: "intent_1",
          status: "pending",
          updated_at: "2026-06-04T12:00:00.000Z"
        }
      ]), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    });
    vi.stubGlobal("fetch", fetchSpy);

    const result = await signalsApi.pendingEntries({ userId: "user_1", scope: "active", limit: 100 });

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ id: "intent_1", status: "pending" });
    expect(String(fetchSpy.mock.calls[0][0])).toContain("/api/v1/pending-entry?user_id=user_1&scope=active&limit=100");
  });
});

function actionState(overrides: Record<string, unknown> = {}) {
  return {
    can_enter_now: false,
    can_arm_pending: true,
    can_reconfirm: false,
    can_cancel: false,
    mode: "virtual",
    environment: "virtual",
    primary_action: null,
    disabled_reason_code: null,
    blockers: [],
    warnings: [],
    accepted_trade_plan_snapshot: null,
    display_labels: {},
    ...overrides
  };
}

function signalDto() {
  return {
    id: "sig_1",
    symbol: "BTCUSDT",
    exchange: "bybit",
    strategy: "trend_pullback_continuation",
    direction: "long",
    confidence: 0.8,
    status: "ready",
    score: 80,
    created_at: "2026-06-04T12:00:00.000Z",
    updated_at: "2026-06-04T12:00:00.000Z"
  };
}

function pendingEntryIntentDto(overrides: Record<string, unknown> = {}) {
  return {
    id: "intent_1",
    user_id: "user_1",
    signal_id: "sig_1",
    strategy_id: null,
    mode: "virtual",
    status: "pending",
    exchange: "bybit",
    symbol: "BTCUSDT",
    side: "long",
    entry_min: "67100",
    entry_max: "67200",
    entry_price_policy: "accepted_entry_zone",
    stop_loss: "66500",
    targets_snapshot: [{ label: "TP1", price: "68100" }],
    accepted_trade_plan_snapshot: {},
    accepted_trade_plan_hash: "plan_hash",
    accepted_signal_status: "ready",
    accepted_signal_version: null,
    accepted_signal_fingerprint: null,
    execution_profile_snapshot: {},
    request_snapshot: {},
    idempotency_key: "idem_1",
    expires_at: null,
    created_at: "2026-06-04T12:00:00.000Z",
    updated_at: "2026-06-04T12:00:00.000Z",
    triggered_at: null,
    filled_at: null,
    filled_trade_id: null,
    failure_reason: null,
    current_price: null,
    reason_code: null,
    localized_reason: null,
    view: {
      status_label: "Waiting entry",
      status_tone: "yellow",
      reason_code: null,
      reason: "Backend is waiting for entry.",
      entry_zone: "67100 - 67200",
      current_price: null
    },
    ...overrides
  };
}

function realExecutionResultDto(overrides: Record<string, unknown> = {}) {
  return {
    mode: "real",
    status: "preview",
    signal_valid: true,
    execution_allowed: true,
    exchange: "bybit",
    symbol: "BTCUSDT",
    message: "Real execution preview is ready.",
    risk_decision: null,
    execution_plan: {
      symbol: "BTCUSDT",
      side: "buy",
      order_type: "market",
      size: "0.1",
      price: null,
      stop_loss: "66500",
      take_profit: "68100",
      reduce_only: false,
      leverage: 2,
      margin_mode: "cross",
      planned_orders: []
    },
    planned_orders: [],
    idempotency_key: "real-preview:sig_1",
    adapter: "bybit",
    blockers: [],
    connection_id: "conn_1",
    environment: "testnet",
    order_placement_mode: "dry_run",
    reason_code: null,
    reason_codes: [],
    warnings: [],
    validation_errors: [],
    ...overrides
  };
}

function radarSummary() {
  return {
    total_signals: 0,
    execution_ready_signals: 0,
    high_confidence_signals: 0,
    positive_edge_signals: 0,
    blocked_ideas: 0
  };
}

function expectActionBodyOnlyIntent(body: Record<string, unknown>) {
  for (const field of [
    "user_id",
    "account_balance",
    "leverage",
    "fee_rate",
    "slippage_bps",
    "max_virtual_slippage_bps",
    "min_fill_ratio",
    "max_open_positions"
  ]) {
    expect(body).not.toHaveProperty(field);
  }
  const serialized = JSON.stringify(body);
  expect(serialized).not.toContain("demo_user");
  expect(serialized).not.toContain("usr_demo");
}
