import { describe, expect, it } from "vitest";

import { describeApiRequest, formatApiTimeoutMessage } from "./client";

describe("FastAPI request diagnostics", () => {
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
});
