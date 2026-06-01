from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    exchange_instrument_sync_enabled: bool = True
    exchange_instrument_sync_interval_seconds: int = 21_600
    exchange_instrument_rules_ttl_seconds: int = 86_400
    bybit_instrument_rule_categories: str = "linear"
    derivative_snapshot_sync_enabled: bool = True
    derivative_snapshot_sync_interval_seconds: int = 60
    derivative_snapshot_ttl_seconds: int = 120
    bybit_derivative_snapshot_categories: str = "linear"
    signal_active_ttl_seconds: int = 3_600
    signal_outcome_tracking_min_score: int = 70
    signal_outcome_same_candle_resolution: str = "stop_first"


settings = Settings()
