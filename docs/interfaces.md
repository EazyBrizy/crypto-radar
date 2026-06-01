# System Flow

MarketData → Features → StrategySignal → TradePlan → RiskGate → Execution

`TradePlan` is a backward-compatible v1 signal contract generated from the
legacy signal entry/stop/target fields. Existing signal fields remain available:
`entry_min`, `entry_max`, `stop_loss`, `take_profit_1`, `take_profit_2`,
`risk_reward`, `first_target_rr`, `final_target_rr`, `selected_rr`,
`selected_rr_target`, and `min_rr_ratio`.

`TradePlan` is persisted in `features_snapshot.trade_plan` and restored to
`StrategySignal.trade_plan` / `RadarSignal.trade_plan` when present. Risk gate
and execution behavior continues to read the existing legacy fields in this
patch.

---

# Rules

## run_strategies
- pure function
- no DB
- no external APIs

## calculate_features
- must use only market data
- no external calls

## execution
- must use config
- no hardcoded values

## RiskManagementSettings
- `strategy_risk_multipliers` must include current strategy keys:
  `trend_pullback_continuation`, `volatility_squeeze_breakout`,
  `liquidity_sweep_reversal`.
- Legacy strategy aliases remain supported:
  `trend_following`, `breakout`, `smart_money_setup`.
- Strategy multiplier lookup uses exact normalized strategy key first,
  then legacy alias fallback, then `1.0`.

## Strategy RR eligibility
- `risk_reward_guard` failed checks make the signal non-actionable for real
  and virtual entries.
- Failed RR snapshots expose `metadata.risk_reward_blocked = true` and
  `metadata.risk_reward_block_reason`.
- Failed RR signals expose disabled `auto_entry` metadata so auto-entry cannot
  be armed by pipeline output.
