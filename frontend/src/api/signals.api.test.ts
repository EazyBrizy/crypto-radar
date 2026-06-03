import { afterEach, describe, expect, it, vi } from "vitest";

import { openApiClient } from "./client";
import { signalsApi } from "./signals.api";

describe("signalsApi.radar", () => {
  afterEach(() => {
    vi.restoreAllMocks();
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
