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

  it("uses demo_user for demo pending-entry requests", async () => {
    const fetchSpy = vi.fn(async () =>
      new Response(JSON.stringify({
        id: "intent_1",
        user_id: "demo_user",
        signal_id: "sig_1",
        status: "pending"
      }), {
        headers: { "Content-Type": "application/json" },
        status: 200
      })
    );
    vi.stubGlobal("fetch", fetchSpy);

    await signalsApi.armPendingEntry({ signalId: "sig_1" });

    const [, init] = fetchSpy.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({ user_id: "demo_user" });
  });
});
