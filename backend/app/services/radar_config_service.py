from app.schemas.candle import DEFAULT_TIMEFRAMES, RadarConfig, RadarConfigUpdate
from app.exchanges.bybit import fetch_bybit_linear_symbols
from app.services.market_scanner import DEFAULT_SYMBOLS

SUPPORTED_EXCHANGES = ["bybit"]


class RadarConfigService:
    """Хранит пользовательский выбор бирж, пар и таймфреймов для Radar MVP."""

    def __init__(self) -> None:
        self._config = RadarConfig(
            exchanges=["bybit"],
            symbols=list(DEFAULT_SYMBOLS),
            use_all_symbols=False,
            timeframes=list(DEFAULT_TIMEFRAMES),
        )

    def get_config(self) -> RadarConfig:
        return self._config

    def update_config(self, update: RadarConfigUpdate) -> RadarConfig:
        values = self._config.model_dump()
        patch = update.model_dump(exclude_none=True)

        if "exchanges" in patch:
            patch["exchanges"] = self._normalize_exchanges(patch["exchanges"])
        if "symbols" in patch:
            patch["symbols"] = self._normalize_symbols(patch["symbols"])

        values.update(patch)
        self._config = RadarConfig(**values)
        return self._config

    def selected_exchanges(self) -> list[str]:
        return self._normalize_exchanges(self._config.exchanges)

    def selected_symbols(self) -> list[str]:
        if self._config.use_all_symbols:
            return self._all_supported_symbols()
        return self._normalize_symbols(self._config.symbols)

    @staticmethod
    def _normalize_exchanges(exchanges: list[str]) -> list[str]:
        normalized = [exchange.strip().lower() for exchange in exchanges if exchange.strip()]
        return [
            exchange
            for exchange in dict.fromkeys(normalized)
            if exchange in SUPPORTED_EXCHANGES
        ] or ["bybit"]

    @staticmethod
    def _normalize_symbols(symbols: list[str]) -> list[str]:
        normalized = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
        return list(dict.fromkeys(normalized)) or list(DEFAULT_SYMBOLS)

    def _all_supported_symbols(self) -> list[str]:
        symbols: list[str] = []
        if "bybit" in self.selected_exchanges():
            try:
                symbols.extend(fetch_bybit_linear_symbols())
            except Exception:
                symbols.extend(DEFAULT_SYMBOLS)
        return list(dict.fromkeys(symbols)) or list(DEFAULT_SYMBOLS)


radar_config_service = RadarConfigService()
