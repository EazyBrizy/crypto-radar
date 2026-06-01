CREATE DATABASE IF NOT EXISTS market;

CREATE DATABASE IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS market.raw_exchange_events
(
    exchange LowCardinality(String),
    event_type LowCardinality(String),
    symbol LowCardinality(String),
    event_ts DateTime64(3, 'UTC'),
    ingest_ts DateTime64(3, 'UTC'),
    source_id String,
    sequence_id Nullable(UInt64),
    raw_payload String
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(ingest_ts)
ORDER BY (exchange, event_type, symbol, ingest_ts, source_id)
TTL ingest_ts + INTERVAL 30 DAY DELETE;

CREATE TABLE IF NOT EXISTS market.trades
(
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    trade_id String,
    side LowCardinality(String),
    price Decimal(38, 18),
    quantity Decimal(38, 18),
    trade_ts DateTime64(3, 'UTC'),
    ingest_ts DateTime64(3, 'UTC'),
    is_buyer_maker Nullable(UInt8)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(trade_ts)
ORDER BY (exchange, symbol, trade_ts, trade_id);

CREATE TABLE IF NOT EXISTS market.orderbook_l2_deltas
(
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    sequence_id UInt64,
    side LowCardinality(String),
    price Decimal(38, 18),
    quantity Decimal(38, 18),
    event_ts DateTime64(3, 'UTC'),
    ingest_ts DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(event_ts)
ORDER BY (exchange, symbol, event_ts, sequence_id, side, price)
TTL event_ts + INTERVAL 14 DAY DELETE;

CREATE TABLE IF NOT EXISTS market.orderbook_snapshots
(
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    snapshot_ts DateTime64(3, 'UTC'),
    ingest_ts DateTime64(3, 'UTC'),
    bids Array(Tuple(Decimal(38, 18), Decimal(38, 18))),
    asks Array(Tuple(Decimal(38, 18), Decimal(38, 18))),
    sequence_id Nullable(UInt64)
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(snapshot_ts)
ORDER BY (exchange, symbol, snapshot_ts);

CREATE TABLE IF NOT EXISTS market.liquidity_snapshots
(
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    snapshot_ts DateTime64(3, 'UTC'),
    ingest_ts DateTime64(3, 'UTC'),
    best_bid Nullable(Decimal(38, 18)),
    best_ask Nullable(Decimal(38, 18)),
    spread_percent Nullable(Float64),
    depth_bid_0_1 Nullable(Decimal(38, 18)),
    depth_ask_0_1 Nullable(Decimal(38, 18)),
    depth_bid_0_5 Nullable(Decimal(38, 18)),
    depth_ask_0_5 Nullable(Decimal(38, 18)),
    depth_bid_1_0 Nullable(Decimal(38, 18)),
    depth_ask_1_0 Nullable(Decimal(38, 18)),
    volume_1m Nullable(Decimal(38, 18)),
    volume_5m Nullable(Decimal(38, 18)),
    volatility_1m Nullable(Float64),
    liquidity_score Nullable(Float64),
    impact_risk LowCardinality(String)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(snapshot_ts)
ORDER BY (exchange, symbol, snapshot_ts)
TTL snapshot_ts + INTERVAL 180 DAY DELETE;

CREATE TABLE IF NOT EXISTS market.ohlcv_1m
(
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    ts DateTime('UTC'),
    open Decimal(38, 18),
    high Decimal(38, 18),
    low Decimal(38, 18),
    close Decimal(38, 18),
    volume_base Decimal(38, 18),
    volume_quote Decimal(38, 18),
    trades_count UInt64,
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (exchange, symbol, ts);

CREATE TABLE IF NOT EXISTS market.ohlcv_5m AS market.ohlcv_1m
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (exchange, symbol, ts);

CREATE TABLE IF NOT EXISTS market.ohlcv_15m AS market.ohlcv_1m
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (exchange, symbol, ts);

CREATE TABLE IF NOT EXISTS market.ohlcv_1h AS market.ohlcv_1m
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (exchange, symbol, ts);

CREATE TABLE IF NOT EXISTS market.ohlcv_4h AS market.ohlcv_1m
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (exchange, symbol, ts);

CREATE TABLE IF NOT EXISTS market.ohlcv_1d AS market.ohlcv_1m
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (exchange, symbol, ts);

CREATE TABLE IF NOT EXISTS market.indicator_values
(
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    ts DateTime('UTC'),
    rsi_14 Nullable(Float64),
    ema_20 Nullable(Decimal(38, 18)),
    ema_50 Nullable(Decimal(38, 18)),
    ema_200 Nullable(Decimal(38, 18)),
    atr_14 Nullable(Decimal(38, 18)),
    volume_sma_20 Nullable(Decimal(38, 18)),
    features_json String,
    calculated_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (exchange, symbol, timeframe, ts);

CREATE TABLE IF NOT EXISTS analytics.signal_events
(
    signal_id UUID,
    signal_key String,
    event_type LowCardinality(String),
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    strategy_code LowCardinality(String),
    strategy_version String,
    direction LowCardinality(String),
    confidence Float64,
    score Float64,
    entry_price Decimal(38, 18),
    stop_loss Nullable(Decimal(38, 18)),
    features_json String,
    event_ts DateTime64(3, 'UTC'),
    ingest_ts DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_ts)
ORDER BY (strategy_code, exchange, symbol, timeframe, event_ts);

CREATE TABLE IF NOT EXISTS analytics.strategy_performance_daily
(
    date Date,
    strategy_code LowCardinality(String),
    strategy_version String,
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    market_regime LowCardinality(String),
    score_bucket LowCardinality(String),
    direction LowCardinality(String),
    signals_count UInt64,
    wins_count UInt64,
    losses_count UInt64,
    avg_rr Float64,
    avg_pnl_pct Float64,
    max_drawdown_pct Float64,
    sample_size UInt64,
    trades_count UInt64,
    entry_touch_rate Float64,
    winrate Float64,
    tp1_rate Float64,
    tp2_rate Float64,
    stop_rate Float64,
    invalidation_rate Float64,
    avg_win_r Float64,
    avg_loss_r Float64,
    expectancy_r Float64,
    profit_factor Nullable(Float64),
    max_drawdown_r Float64,
    median_bars_to_entry Nullable(Float64),
    median_bars_to_outcome Nullable(Float64),
    avg_mfe_r Float64,
    avg_mae_r Float64,
    fees_bps Float64,
    slippage_bps Float64,
    updated_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(date)
ORDER BY (
    strategy_code,
    exchange,
    symbol,
    timeframe,
    strategy_version,
    market_regime,
    score_bucket,
    direction,
    date
);

CREATE TABLE IF NOT EXISTS analytics.virtual_trade_events
(
    user_id UUID,
    portfolio_id UUID,
    order_id UUID,
    position_id Nullable(UUID),
    signal_id Nullable(UUID),
    event_type LowCardinality(String),
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    side LowCardinality(String),
    price Decimal(38, 18),
    quantity Decimal(38, 18),
    pnl Nullable(Decimal(38, 18)),
    fee Nullable(Decimal(38, 18)),
    event_ts DateTime64(3, 'UTC'),
    ingest_ts DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_ts)
ORDER BY (user_id, portfolio_id, event_ts);

CREATE TABLE IF NOT EXISTS analytics.external_trade_events
(
    user_id UUID,
    connection_id UUID,
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    exchange_trade_id String,
    side LowCardinality(String),
    price Decimal(38, 18),
    quantity Decimal(38, 18),
    fee Nullable(Decimal(38, 18)),
    traded_at DateTime64(3, 'UTC'),
    imported_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(traded_at)
ORDER BY (user_id, exchange, symbol, traded_at);
