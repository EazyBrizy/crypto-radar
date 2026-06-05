import { describe, expect, it } from "vitest";

import type {
  AccountRiskSnapshotDto,
  ExchangeWalletBalanceResponseDto,
  MarketUniversePairResponseDto,
  PendingEntryIntentReadDto
} from "./generated/schemas";
import {
  ApiContractError,
  normalizeAccountRiskSnapshot,
  normalizeExchangeWalletBalance,
  normalizeExecutionReport,
  normalizeMarketUniversePair,
  normalizePendingEntryIntent,
  normalizeRadarStatus,
  normalizeSignalActionState
} from "./mappers";

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
      warmup_total: 6,
      warmup_completed: 2,
      warmup_failed: 1,
      last_tick_age_seconds: null,
      scan_pairs: ["bybit:XRPUSDT", "bybit:BTCUSDT"],
      scanner_pairs_count: 2,
      scanner_universe_source: "explicit pairs",
      scanner_universe_warning: "Scanner universe has 3 pairs, max_scanner_pairs=2.",
      estimated_strategy_checks: 6,
      max_scanner_pairs: 2
    });

    expect(status.scan_pairs).toEqual(["bybit:XRPUSDT", "bybit:BTCUSDT"]);
    expect(status.market_data_status).toBe("waiting");
    expect(status.stage).toBe("starting");
    expect(status.warmup_total).toBe(6);
    expect(status.warmup_completed).toBe(2);
    expect(status.warmup_failed).toBe(1);
    expect(status.last_tick_age_seconds).toBeNull();
    expect(status.scanner_pairs_count).toBe(2);
    expect(status.scanner_universe_source).toBe("explicit pairs");
    expect(status.scanner_universe_warning).toContain("max_scanner_pairs=2");
    expect(status.estimated_strategy_checks).toBe(6);
    expect(status.max_scanner_pairs).toBe(2);
  });
});

describe("market/risk/trading OpenAPI DTO mappers", () => {
  it("throws API contract error when critical action-state fields are missing", () => {
    expect(() =>
      normalizeSignalActionState({
        can_arm_pending: true,
        can_reconfirm: false,
        can_cancel: false,
        mode: "virtual",
        environment: "virtual",
        primary_action: "arm_pending_entry",
        disabled_reason_code: null,
        blockers: [],
        warnings: [],
        accepted_trade_plan_snapshot: null,
        display_labels: {}
      })
    ).toThrow(ApiContractError);
  });

  it("accepts generated pending-entry history DTOs with Decimal strings", () => {
    const intent = {
      id: "intent_1",
      user_id: "user_1",
      signal_id: "signal_1",
      strategy_id: null,
      mode: "virtual",
      status: "requires_reconfirmation",
      exchange: "bybit",
      symbol: "BTCUSDT",
      side: "long",
      entry_min: "67123.12345678",
      entry_max: "67200.00000001",
      entry_price_policy: "accepted_entry_zone",
      stop_loss: "66500.00000001",
      targets_snapshot: [{ label: "TP1", price: "68100.25" }],
      accepted_trade_plan_snapshot: {},
      accepted_trade_plan_hash: "plan_hash",
      accepted_signal_status: "active",
      accepted_signal_version: null,
      accepted_signal_fingerprint: null,
      execution_profile_snapshot: {},
      request_snapshot: {},
      idempotency_key: "idem_1",
      expires_at: "2026-06-04T12:30:00.000Z",
      created_at: "2026-06-04T12:00:00.000Z",
      updated_at: "2026-06-04T12:05:00.000Z",
      triggered_at: null,
      filled_at: null,
      filled_trade_id: null,
      failure_reason: null
    } satisfies PendingEntryIntentReadDto;

    const normalized = normalizePendingEntryIntent(intent);

    expect(normalized.status).toBe("requires_reconfirmation");
    expect(normalized.entry_min).toBe(67123.12345678);
    expect(normalized.targets_snapshot).toEqual([{ label: "TP1", price: "68100.25" }]);
  });

  it("preserves market universe financial values as strings", () => {
    const pair = {
      id: "pair_1",
      exchange: "bybit",
      symbol: "BTCUSDT",
      base_asset: "BTC",
      quote_asset: "USDT",
      status: "Trading",
      category: "linear",
      market_type: "perpetual",
      turnover_24h: "1234567890.123456789",
      volume_24h: "98765.432109876",
      last_price: "67123.12345678",
      mark_price: "67120.87654321",
      bid_price: "67122.1",
      ask_price: "67122.2",
      spread_bps: "0.0149",
      funding_rate: "0.0001",
      liquidity_rank: 1,
      liquidity_tier: "high",
      synced_at: "2026-06-04T12:00:00.000Z"
    } satisfies MarketUniversePairResponseDto;

    const normalized = normalizeMarketUniversePair(pair);

    expect(normalized.turnover_24h).toBe("1234567890.123456789");
    expect(normalized.last_price).toBe("67123.12345678");
    expect(normalized.funding_rate).toBe("0.0001");
  });

  it("maps exchange wallet Decimal string DTOs for the existing balance view model", () => {
    const wallet = {
      exchange: "bybit",
      connection_id: "connection_1",
      account_type: "unified",
      total_equity: "10000.123456789",
      total_wallet_balance: "9999.123456789",
      total_available_balance: "8000.123456789",
      coins: [
        {
          coin: "USDT",
          equity: "10000.123456789",
          usd_value: "10000.123456789",
          wallet_balance: "9999.123456789",
          available_to_withdraw: "8000.123456789",
          locked: "0.000000001",
          borrow_amount: null,
          accrued_interest: null,
          total_order_im: "12.5",
          total_position_im: "42.5",
          total_position_mm: "4.25",
          unrealised_pnl: "-1.23456789"
        }
      ],
      fetched_at: "2026-06-04T12:00:00.000Z",
      status: "fresh",
      warnings: []
    } satisfies ExchangeWalletBalanceResponseDto;

    const normalized = normalizeExchangeWalletBalance(wallet);

    expect(normalized.total_equity).toBeCloseTo(10000.123456789);
    expect(normalized.coins[0]?.unrealised_pnl).toBeCloseTo(-1.23456789);
  });

  it("maps account snapshot Decimal string DTOs for risk cards", () => {
    const snapshot = {
      status: "fresh",
      fetched_at: "2026-06-04T12:00:00.000Z",
      account_equity: "10000.123456789",
      available_balance: "8000.123456789",
      wallet_balance: "9999.123456789",
      margin_mode: "cross",
      total_initial_margin: "100.5",
      total_maintenance_margin: "50.25",
      maintenance_margin_rate: "0.005",
      positions: [
        {
          symbol: "BTCUSDT",
          side: "long",
          quantity: "0.123456789",
          notional: "8300.123456789",
          entry_price: "67000.12345678",
          mark_price: "67123.12345678",
          unrealized_pnl: "15.123456789",
          risk_amount: "120.123456789",
          initial_margin: "100.5",
          maintenance_margin: "50.25",
          margin_mode: "cross"
        }
      ],
      open_risk_amount: "120.123456789",
      source: "exchange",
      warnings: []
    } satisfies AccountRiskSnapshotDto;

    const normalized = normalizeAccountRiskSnapshot(snapshot);

    expect(normalized.account_equity).toBeCloseTo(10000.123456789);
    expect(normalized.open_risk_amount).toBeCloseTo(120.123456789);
    expect(normalized.positions[0]?.entry_price).toBeCloseTo(67000.12345678);
  });
});
