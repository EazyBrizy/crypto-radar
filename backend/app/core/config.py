from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    binance_api_key: str = ""
    binance_secret: str = ""

    bybit_api_key: str = ""
    bybit_secret: str = ""

    database_url: str = "postgresql://crypto_radar:crypto_radar@localhost:5432/crypto_radar"
    redis_url: str = "redis://localhost:6379/0"
    nats_url: str = "nats://localhost:4222"

    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_database: str = "crypto_radar"
    clickhouse_user: str = "crypto_radar"
    clickhouse_password: str = "crypto_radar"

    otel_service_name: str = "crypto-radar-backend"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    prometheus_metrics_enabled: bool = True
    fastapi_slow_request_ms: int = 1000

    enable_live_trading: bool = False
    enable_bybit_live_order_placement: bool = False
    enable_bybit_mainnet_order_placement: bool = False
    require_protective_stop_for_live_entry: bool = True
    virtual_max_open_positions: int = 3
    virtual_max_slippage_bps: float = 150.0
    virtual_allow_partial_fill: bool = True
    virtual_min_fill_ratio: float = 0.25
    virtual_execution_profile: str = "realistic"

    exchange_instrument_sync_enabled: bool = True
    exchange_instrument_sync_interval_seconds: int = 21_600
    exchange_instrument_rules_ttl_seconds: int = 86_400
    bybit_instrument_rule_categories: str = "linear"
    derivative_snapshot_sync_enabled: bool = True
    derivative_snapshot_sync_interval_seconds: int = 60
    derivative_snapshot_ttl_seconds: int = 120
    bybit_derivative_snapshot_categories: str = "linear"
    market_universe_high_turnover_24h: Decimal = Decimal("100000000")
    market_universe_medium_turnover_24h: Decimal = Decimal("10000000")
    orderbook_snapshot_sync_enabled: bool = True
    orderbook_snapshot_sync_interval_seconds: int = 10
    orderbook_snapshot_ttl_seconds: int = 15
    bybit_orderbook_snapshot_categories: str = "linear"
    bybit_orderbook_snapshot_limit: int = 50
    real_position_sync_enabled: bool = False
    real_position_sync_interval_seconds: int = 30
    real_order_missing_exchange_timeout_seconds: int = 300
    exchange_account_snapshot_ttl_seconds: int = 15
    signal_active_ttl_seconds: int = 3_600
    signal_outcome_tracking_min_score: int = 70
    signal_outcome_same_candle_resolution: str = "conservative_stop_first"
    strategy_performance_min_sample_size: int = 30
    max_scanner_pairs: int = 200
    truncate_scanner_pairs_over_limit: bool = False


settings = Settings()
