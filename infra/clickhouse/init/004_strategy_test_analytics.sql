CREATE DATABASE IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.strategy_test_trades
(
    run_id UUID,
    trade_id String,
    scenario_key String,
    event_key String,
    run_attempt UInt32,
    user_id UUID,
    mode LowCardinality(String),
    strategy_code LowCardinality(String),
    strategy_version String,
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    direction LowCardinality(String),
    signal_score Nullable(Float64),
    market_regime LowCardinality(String),
    score_bucket LowCardinality(String),
    entry_time DateTime64(3, 'UTC'),
    exit_time Nullable(DateTime64(3, 'UTC')),
    entry_price Decimal(38, 18),
    exit_price Nullable(Decimal(38, 18)),
    stop_loss Nullable(Decimal(38, 18)),
    targets_json String,
    selected_rr Nullable(Float64),
    realized_r Nullable(Float64),
    pnl Decimal(38, 18),
    pnl_pct Float64,
    fees Decimal(38, 18),
    slippage Decimal(38, 18),
    mfe_r Nullable(Float64),
    mae_r Nullable(Float64),
    bars_to_entry Nullable(UInt64),
    bars_in_trade Nullable(UInt64),
    close_reason LowCardinality(String),
    outcome LowCardinality(String),
    risk_rejected UInt8,
    execution_rejected UInt8,
    warnings_json String,
    features_snapshot_json String,
    trade_plan_json String,
    tags Array(String),
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(entry_time)
ORDER BY (run_id, scenario_key, event_key, entry_time, trade_id);

CREATE TABLE IF NOT EXISTS analytics.strategy_test_metrics
(
    run_id UUID,
    scenario_key String,
    run_attempt UInt32,
    user_id UUID,
    mode LowCardinality(String),
    strategy_code LowCardinality(String),
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    market_regime LowCardinality(String),
    score_bucket LowCardinality(String),
    direction LowCardinality(String),
    metric_code LowCardinality(String),
    metric_value Nullable(Float64),
    sample_size UInt64,
    metadata_json String,
    created_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(created_at)
PARTITION BY toYYYYMM(created_at)
ORDER BY (
    run_id,
    scenario_key,
    strategy_code,
    exchange,
    symbol,
    timeframe,
    market_regime,
    score_bucket,
    direction,
    metric_code
);

CREATE TABLE IF NOT EXISTS analytics.strategy_test_signals
(
    run_id UUID,
    scenario_key String,
    event_key String,
    run_attempt UInt32,
    user_id UUID,
    mode LowCardinality(String),
    test_type LowCardinality(String),
    strategy_code LowCardinality(String),
    strategy_version String,
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    direction LowCardinality(String),
    signal_id Nullable(String),
    synthetic_signal_id String,
    signal_key String,
    event_time DateTime64(3, 'UTC'),
    candle_time DateTime64(3, 'UTC'),
    signal_score Nullable(Float64),
    market_regime LowCardinality(String),
    score_bucket LowCardinality(String),
    status LowCardinality(String),
    gate_status LowCardinality(String),
    feed_kind LowCardinality(String),
    trigger_passed UInt8,
    trigger_reason_code Nullable(String),
    execution_candidate UInt8,
    entry_touched UInt8,
    filled UInt8,
    closed UInt8,
    outcome Nullable(String),
    funnel_stage LowCardinality(String),
    risk_rejected UInt8,
    execution_rejected UInt8,
    no_entry UInt8,
    rejection_reason_code Nullable(String),
    blocked_reason_code Nullable(String),
    selected_rr Nullable(Float64),
    entry_min Nullable(Decimal(38, 18)),
    entry_max Nullable(Decimal(38, 18)),
    stop_loss Nullable(Decimal(38, 18)),
    features_snapshot_json String,
    trade_plan_json String,
    metadata_json String,
    tags Array(String),
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(candle_time)
ORDER BY (run_id, scenario_key, event_key, candle_time, signal_key);

ALTER TABLE analytics.strategy_test_trades ADD COLUMN IF NOT EXISTS scenario_key String DEFAULT concat(strategy_code, '::', exchange, '::', symbol, '::', timeframe);
ALTER TABLE analytics.strategy_test_trades ADD COLUMN IF NOT EXISTS event_key String DEFAULT trade_id;
ALTER TABLE analytics.strategy_test_trades ADD COLUMN IF NOT EXISTS run_attempt UInt32 DEFAULT 0;

ALTER TABLE analytics.strategy_test_signals ADD COLUMN IF NOT EXISTS scenario_key String DEFAULT concat(strategy_code, '::', exchange, '::', symbol, '::', timeframe);
ALTER TABLE analytics.strategy_test_signals ADD COLUMN IF NOT EXISTS event_key String DEFAULT coalesce(nullIf(signal_id, ''), nullIf(synthetic_signal_id, ''), signal_key);
ALTER TABLE analytics.strategy_test_signals ADD COLUMN IF NOT EXISTS run_attempt UInt32 DEFAULT 0;

ALTER TABLE analytics.strategy_test_metrics ADD COLUMN IF NOT EXISTS scenario_key String DEFAULT concat(strategy_code, '::', exchange, '::', symbol, '::', timeframe);
ALTER TABLE analytics.strategy_test_metrics ADD COLUMN IF NOT EXISTS run_attempt UInt32 DEFAULT 0;
