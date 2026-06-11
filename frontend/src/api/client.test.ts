import { afterEach, describe, expect, it, vi } from "vitest";

import {
  describeApiRequest,
  formatApiNetworkErrorMessage,
  formatApiTimeoutMessage,
  requestJson
} from "./client";

describe("FastAPI request diagnostics", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("formats timeout errors with method, path, sanitized query, and API base", () => {
    const request = describeApiRequest(
      "http://127.0.0.1:8000/api/v1/radar?radar_display_mode=all_market_opportunities",
      { method: "GET" }
    );

    expect(formatApiTimeoutMessage(request)).toBe(
      "FastAPI request timed out after 8000ms: GET /api/v1/radar?radar_display_mode=all_market_opportunities at http://127.0.0.1:8000."
    );
  });

  it("redacts sensitive query values before formatting errors", () => {
    const request = describeApiRequest(
      "http://127.0.0.1:8000/api/v1/radar?radar_display_mode=all_market_opportunities&api_key=secret-value",
      { method: "GET" }
    );

    expect(request.path).toBe(
      "/api/v1/radar?radar_display_mode=all_market_opportunities&api_key=redacted"
    );
    expect(formatApiTimeoutMessage(request)).not.toContain("secret-value");
  });

  it("uses Request method when fetch receives a Request object", () => {
    const request = describeApiRequest(
      new Request("http://127.0.0.1:8000/api/v1/radar/scanner/start", { method: "POST" })
    );

    expect(formatApiTimeoutMessage(request)).toBe(
      "FastAPI request timed out after 8000ms: POST /api/v1/radar/scanner/start at http://127.0.0.1:8000."
    );
  });

  it("keeps HTTP failures distinct from network failures", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "report failed" }), {
      headers: { "Content-Type": "application/json" },
      status: 500
    })));

    await expect(requestJson("/api/v1/strategy-tests/reports/run_1")).rejects.toThrow(
      "FastAPI API error: GET /api/v1/strategy-tests/reports/run_1 at http://127.0.0.1:8000 returned 500: report failed"
    );
    await expect(requestJson("/api/v1/strategy-tests/reports/run_1")).rejects.not.toThrow("network error");
  });

  it("uses network wording only when fetch does not return a response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("fetch failed");
    }));

    await expect(requestJson("/api/v1/strategy-tests/reports/run_1")).rejects.toThrow(
      formatApiNetworkErrorMessage(describeApiRequest("http://127.0.0.1:8000/api/v1/strategy-tests/reports/run_1"))
    );
  });
});
