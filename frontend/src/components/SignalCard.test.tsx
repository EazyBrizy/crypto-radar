import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RadarSignal } from "@/types";
import { SignalCard } from "./SignalCard";

describe("SignalCard", () => {
  it("renders backend-precomputed card view", () => {
    render(<SignalCard signal={baseSignal()} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("Backend ready")).toBeInTheDocument();
    expect(screen.getByText("RR passed")).toBeInTheDocument();
    expect(screen.getByText("Backend entry | 100 - 101")).toBeInTheDocument();
    expect(screen.getByText("110 1.00R")).toBeInTheDocument();
    expect(screen.getByText("2.00R")).toBeInTheDocument();
    expect(screen.getByText("Backend selected this signal for execution.")).toBeInTheDocument();
  });

  it("shows an API contract error when SignalCardView is missing", () => {
    render(<SignalCard signal={{ ...baseSignal(), card_view: null }} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("API contract error")).toBeInTheDocument();
    expect(screen.getByText("SignalCardView is missing")).toBeInTheDocument();
  });
});

function baseSignal(overrides: Partial<RadarSignal> = {}): RadarSignal {
  return {
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
    card_view: {
      status_label: "Backend ready",
      status_tone: "green",
      opportunity_label: "Execution ready",
      opportunity_tone: "green",
      risk_label: "Risk ok",
      badges: [{ code: "rr_passed", label: "RR passed", tone: "green" }],
      entry_label: "Backend entry",
      entry_value: "100 - 101",
      stop_loss: 98,
      targets: [
        { label: "TP1", price: 110, r_multiple: 1, action: "partial_close" },
        { label: "TP2", price: 120, r_multiple: 2, action: "full_close" }
      ],
      selected_rr: 2,
      risk_meta: "Backend risk summary",
      reason: "Backend selected this signal for execution."
    },
    details_view: null,
    created_at: "2026-05-31T07:00:00.000Z",
    updated_at: "2026-05-31T07:00:00.000Z",
    expires_at: "2026-05-31T08:00:00.000Z",
    ...overrides
  };
}
