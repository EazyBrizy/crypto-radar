import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RadarSignal } from "@/types";
import { SignalCard } from "./SignalCard";

const baseSignal: RadarSignal = {
  id: "sig_1",
  symbol: "BTCUSDT",
  exchange: "bybit",
  strategy: "trend_pullback_continuation",
  direction: "long",
  confidence: 0.82,
  risk_reward: 2,
  first_target_rr: 1,
  final_target_rr: 2,
  selected_rr: 2,
  selected_rr_target: "final",
  min_rr_ratio: 1.5,
  urgency: "medium",
  status: "ready",
  score: 82,
  timeframe: "15m",
  entry_min: 100,
  entry_max: 101,
  stop_loss: 98,
  take_profit_1: 110,
  take_profit_2: 120,
  explanation: ["Trend pullback confirmed"],
  risks: [],
  score_breakdown: {
    trend_score: 80,
    volume_score: 80,
    liquidity_score: 80,
    orderbook_score: 80,
    risk_reward_score: 80,
    volatility_score: 80,
    overheat_penalty: 0,
    news_event_risk_penalty: 0,
    total: 82
  },
  status_reason: null,
  quality: null,
  regime: null,
  setup: null,
  confirmation: null,
  invalidation: null,
  exit_plan: null,
  auto_entry: null,
  created_at: "2026-05-31T07:00:00.000Z",
  updated_at: "2026-05-31T07:00:00.000Z",
  expires_at: "2026-05-31T08:00:00.000Z"
};

describe("SignalCard", () => {
  it("keeps old signals visible through legacy TP/SL fields", () => {
    render(<SignalCard signal={baseSignal} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText(/Legacy entry \| 100-101/u)).toBeInTheDocument();
    expect(screen.getByText("110 1.00R")).toBeInTheDocument();
    expect(screen.getByText("Edge unknown")).toBeInTheDocument();
  });

  it("shows trade plan targets, RR block, no-trade and edge status", () => {
    const signal: RadarSignal = {
      ...baseSignal,
      selected_rr: 0.8,
      min_rr_ratio: 1.5,
      confirmation: {
        passed: false,
        checks: [
          {
            name: "risk_reward_guard",
            status: "failed",
            score: 0.8,
            reason: "Risk/reward blocked: nearest target is 0.80R, minimum 1.50R",
            metadata: { risk_reward_blocked: true }
          }
        ]
      },
      trade_plan: {
        version: "v1",
        entry: {
          price: 100.5,
          min_price: 100,
          max_price: 101,
          source: "ema20_ema50_pullback_zone",
          metadata: { entry_type: "ema_pullback_zone" }
        },
        stop_loss: 97,
        targets: [
          { label: "TP1", price: 110, r_multiple: 1, action: "partial_close", close_percent: 40, source: "structure", metadata: {} },
          { label: "TP2", price: 120, r_multiple: 2, action: "reduce_runner", close_percent: 30, source: "structure", metadata: {} },
          { label: "TP3", price: 125, r_multiple: 2.5, action: "full_close", close_percent: 30, source: "measured", metadata: {} }
        ],
        invalidation: null,
        risk_rules: {
          risk_reward: 2.5,
          first_target_rr: 1,
          final_target_rr: 2.5,
          selected_rr: 0.8,
          selected_rr_target: "nearest",
          min_rr_ratio: 1.5,
          metadata: {}
        },
        metadata: {}
      },
      edge: {
        status: "positive",
        sample_size: 75,
        min_sample_size: 50,
        winrate: 0.61,
        avg_win_r: 1.8,
        avg_loss_r: -1,
        expectancy_r: 0.45,
        expectancy_after_costs_r: 0.37,
        profit_factor: 1.6,
        confidence_score: 0.72,
        source: "outcome",
        score_bucket: "80-89",
        metadata: {}
      },
      no_trade_filter: {
        enabled: true,
        blocked: true,
        hard_block: true,
        blockers: ["high_spread"],
        warnings: [],
        checks: [],
        metadata: {}
      }
    };

    render(<SignalCard signal={signal} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("Edge + 75 sample")).toBeInTheDocument();
    expect(screen.getByText("RR blocked")).toBeInTheDocument();
    expect(screen.getByText("No-trade")).toBeInTheDocument();
    expect(screen.getByText(/ema pullback zone \| 100-101/u)).toBeInTheDocument();
    expect(screen.getByText("125 2.50R")).toBeInTheDocument();
    expect(screen.getByText("0.80R")).toBeInTheDocument();
  });
});
