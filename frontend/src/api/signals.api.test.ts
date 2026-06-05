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
      data: { signals: [] },
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
        pending_entry_intent: {
          id: "intent_1",
          user_id: "usr_demo",
          signal_id: "sig_1",
          status: "pending"
        },
        message: "Auto-entry armed"
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

    const result = await signalsApi.pendingEntry("sig_1", "usr_demo");

    expect(result).toBeNull();
    expect(String(fetchSpy.mock.calls[0][0])).toContain("/api/v1/signals/sig_1/pending-entry?user_id=usr_demo");
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
          id: "intent_cancelled",
          user_id: "demo_user",
          signal_id: "sig_1",
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
}
