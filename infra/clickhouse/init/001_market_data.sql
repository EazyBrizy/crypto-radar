CREATE DATABASE IF NOT EXISTS crypto_radar;

CREATE TABLE IF NOT EXISTS crypto_radar.market_trades
(
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    price Float64,
    quantity Float64,
    side LowCardinality(String),
    event_time DateTime64(3, 'UTC'),
    received_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(event_time)
ORDER BY (exchange, symbol, event_time);

CREATE TABLE IF NOT EXISTS crypto_radar.candles
(
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    open Float64,
    high Float64,
    low Float64,
    close Float64,
    volume Float64,
    trades UInt32,
    candle_time DateTime64(3, 'UTC'),
    received_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(candle_time)
ORDER BY (exchange, symbol, timeframe, candle_time);

CREATE TABLE IF NOT EXISTS crypto_radar.generated_signals
(
    signal_id String,
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    strategy LowCardinality(String),
    timeframe LowCardinality(String),
    direction LowCardinality(String),
    score UInt8,
    created_at DateTime64(3, 'UTC'),
    payload String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (exchange, symbol, strategy, created_at);
