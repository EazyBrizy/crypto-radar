CREATE DATABASE IF NOT EXISTS market;

CREATE TABLE IF NOT EXISTS market.regime_snapshots
(
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    ts DateTime64(3, 'UTC'),
    primary_label LowCardinality(String),
    base_label LowCardinality(String),
    volatility_label LowCardinality(String),
    event_labels Array(String),
    direction LowCardinality(String),
    strength LowCardinality(String),
    confidence Float64,
    score_adjustment Int16,
    regime_key String,
    snapshot_json String,
    calculated_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (exchange, symbol, timeframe, ts);
