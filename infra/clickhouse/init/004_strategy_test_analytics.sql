CREATE DATABASE IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.strategy_test_trades
(
    run_id UUID,
    trade_id String,
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
ORDER BY (run_id, strategy_code, exchange, symbol, timeframe, entry_time, trade_id);

CREATE TABLE IF NOT EXISTS analytics.strategy_test_metrics
(
    run_id UUID,
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
    strategy_code,
    exchange,
    symbol,
    timeframe,
    market_regime,
    score_bucket,
    direction,
    metric_code
);
