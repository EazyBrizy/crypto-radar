import { describe, expect, it } from "vitest";

import { normalizeExecutionReport, normalizeRadarStatus } from "./mappers";

describe("normalizeExecutionReport", () => {
  it("preserves realistic virtual fill result diagnostics", () => {
    const report = normalizeExecutionReport({
      mode: "impact_aware",
      simulation_tier: "advanced",
      status: "partially_filled",
      requested_size_usd: 1_000,
      filled_size_usd: 640,
      unfilled_size_usd: 360,
      fill_ratio: 0.64,
      reference_price: 100,
      average_price: 100.4,
      entry_slippage_bps: 40,
      exit_slippage_bps: 55,
      market_impact_percent: 0.12,
      liquidity: { impact_risk: "medium" },
      quality_gate: { status: "warning" },
      fill_result: {
        status: "partial_filled",
        requested_notional: 1_000,
        filled_notional: 640,
        avg_fill_price: 100.4,
        estimated_slippage_bps: 40,
        spread_bps: 12,
        market_impact_bps: 12,
        reason: "requested_notional_above_safe_size",
        warnings: ["Requested notional exceeds conservative safe size; virtual fill was capped."],
        raw_inputs_snapshot: {
          side: "long",
          symbol: "LOWCAPUSDT",
          market_data_status: "fresh"
        }
      },
      raw_inputs_snapshot: {
        side: "long",
        symbol: "LOWCAPUSDT",
        market_data_status: "fresh"
      }
    });

    expect(report?.fill_result?.status).toBe("partial_filled");
    expect(report?.fill_result?.filled_notional).toBe(640);
    expect(report?.fill_result?.reason).toBe("requested_notional_above_safe_size");
    expect(report?.fill_result?.raw_inputs_snapshot.symbol).toBe("LOWCAPUSDT");
    expect(report?.raw_inputs_snapshot.market_data_status).toBe("fresh");
  });
});

describe("normalizeRadarStatus", () => {
  it("preserves scanner universe diagnostics", () => {
    const status = normalizeRadarStatus({
      status: "ok",
      scanner_enabled: true,
      scanner_running: true,
      processed_signals: 0,
      scan_pairs: ["bybit:XRPUSDT", "bybit:BTCUSDT"],
      scanner_pairs_count: 2,
      scanner_universe_source: "explicit pairs",
      scanner_universe_warning: "Scanner universe has 3 pairs, max_scanner_pairs=2.",
      estimated_strategy_checks: 6,
      max_scanner_pairs: 2
    });

    expect(status.scan_pairs).toEqual(["bybit:XRPUSDT", "bybit:BTCUSDT"]);
    expect(status.scanner_pairs_count).toBe(2);
    expect(status.scanner_universe_source).toBe("explicit pairs");
    expect(status.scanner_universe_warning).toContain("max_scanner_pairs=2");
    expect(status.estimated_strategy_checks).toBe(6);
    expect(status.max_scanner_pairs).toBe(2);
  });
});
