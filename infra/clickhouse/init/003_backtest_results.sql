CREATE DATABASE IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.backtest_results
(
    run_id UUID,
    user_id UUID,
    strategy_code LowCardinality(String),
    strategy_version String,
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    start_ts DateTime64(3, 'UTC'),
    end_ts DateTime64(3, 'UTC'),
    initial_capital Decimal(38, 18),
    final_equity Decimal(38, 18),
    pnl Decimal(38, 18),
    pnl_pct Float64,
    max_drawdown_pct Float64,
    trades_count UInt64,
    wins_count UInt64,
    losses_count UInt64,
    metrics_json String,
    equity_curve_json String,
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (user_id, strategy_code, exchange, symbol, timeframe, created_at, run_id);
