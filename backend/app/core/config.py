from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

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
    realtime_publish_timeout_seconds: float = 0.75

    crypto_radar_scanner_enabled: bool = False
    real_trading_mode: str = "disabled"
    real_trading_explicit_unlock: bool = False
    real_trading_mainnet_small_size_cap_usd: float = 50.0
    enable_live_trading: bool = False
    enable_bybit_live_order_placement: bool = False
    enable_bybit_mainnet_order_placement: bool = False
    bybit_http_timeout_seconds: float = 4.0
    require_protective_stop_for_live_entry: bool = True
    virtual_max_open_positions: int = 3
    virtual_max_slippage_bps: float = 150.0
    virtual_allow_partial_fill: bool = True
    virtual_min_fill_ratio: float = 0.25
    virtual_execution_profile: str = "realistic"

    exchange_instrument_sync_enabled: bool = False
    exchange_instrument_sync_interval_seconds: int = 21_600
    exchange_instrument_rules_ttl_seconds: int = 86_400
    bybit_instrument_rule_categories: str = "linear"
    derivative_snapshot_sync_enabled: bool = False
    derivative_snapshot_sync_interval_seconds: int = 60
    derivative_snapshot_ttl_seconds: int = 120
    bybit_derivative_snapshot_categories: str = "linear"
    market_universe_high_turnover_24h: Decimal = Decimal("100000000")
    market_universe_medium_turnover_24h: Decimal = Decimal("10000000")
    orderbook_snapshot_sync_enabled: bool = False
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
    scanner_open_candle_previews_enabled: bool = True
    execution_closed_candle_only: bool = True
    execution_min_score: int = 70
    virtual_pending_min_score: int = 60
    radar_min_market_idea_score: int = 50
    execution_dedup_window_seconds: int = 300
    notification_dedup_window_seconds: int = 300
    execution_edge_gate_enabled: bool = True
    execution_edge_min_sample_size: int = 50
    execution_edge_min_expectancy_after_costs_r: float = 0.05
    execution_edge_min_profit_factor: float = 1.15
    execution_edge_allow_insufficient_sample_in_learning_mode: bool = False
    execution_edge_learning_mode: bool = False
    execution_edge_min_entry_touch_rate: float = 0.25
    execution_edge_max_no_entry_rate: float = 0.60
    execution_require_walk_forward_edge: bool = False
    execution_min_validation_sample_size: int = 30
    execution_min_validation_expectancy_r: float = 0.05
    execution_min_validation_profit_factor: float = 1.15
    execution_max_validation_drawdown_r: float = 10.0
    execution_min_entry_touch_rate: float = 0.25
    execution_max_no_entry_rate: float = 0.60
    max_scanner_pairs: int = 20
    truncate_scanner_pairs_over_limit: bool = False
    scanner_warmup_concurrency: int = 2
    scanner_warmup_timeout_seconds: float = 8.0
    scanner_market_data_stale_seconds: float = 30.0
    strategy_test_max_bars_per_run: int = 1_000_000
    strategy_test_max_scenarios_per_run: int = 96
    strategy_test_worker_heartbeat_seconds: float = 5.0
    strategy_test_lease_seconds: int = 900
    strategy_test_historical_backfill_enabled: bool = True
    strategy_test_historical_backfill_concurrency: int = 2
    strategy_test_historical_backfill_batch_limit: int = 1000
    strategy_test_historical_backfill_max_candles_per_pair_timeframe: int = 500_000
    strategy_test_historical_backfill_timeout_seconds: float = 30.0


settings = Settings()
