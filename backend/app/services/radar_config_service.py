import hashlib
import json

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
        strategy_exchanges = [
            exchange
            for config in self._strategy_runtime_configs()
            for exchange in config.exchanges
        ]
        pair_exchanges = [exchange for exchange, _ in self._strategy_scope_pairs()]
        return self._normalize_exchanges([*self._config.exchanges, *strategy_exchanges, *pair_exchanges])

    def selected_symbols(self) -> list[str]:
        if self._config.use_all_symbols:
            symbols = self._all_supported_symbols()
        else:
            symbols = self._normalize_symbols(self._config.symbols)
        strategy_symbols = [symbol for _, symbol in self._strategy_scope_pairs()]
        return self._normalize_symbols([*symbols, *strategy_symbols])

    def selected_timeframes(self) -> list[str]:
        strategy_timeframes = [
            timeframe
            for config in self._strategy_runtime_configs()
            for timeframe in config.timeframes
        ]
        strategy_context_timeframes = [
            timeframe
            for config in self._strategy_runtime_configs()
            for timeframe in _context_timeframe_values(config.params)
        ]
        return self._normalize_timeframes([*self._config.timeframes, *strategy_timeframes, *strategy_context_timeframes])

    def scanner_subscription_hash(self) -> str:
        payload = {
            "exchanges": self.selected_exchanges(),
            "symbols": self.selected_symbols(),
            "timeframes": self.selected_timeframes(),
        }
        return _short_hash(payload)

    def strategy_config_hash(self) -> str:
        try:
            from app.services.strategy_config_service import strategy_config_service

            return strategy_config_service.config_hash()
        except Exception:
            return "unavailable"

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

    @staticmethod
    def _normalize_timeframes(timeframes: list[str]) -> list[str]:
        allowed = set(DEFAULT_TIMEFRAMES)
        normalized = [timeframe.strip().lower() for timeframe in timeframes if timeframe.strip()]
        result = [timeframe for timeframe in dict.fromkeys(normalized) if timeframe in allowed]
        return result or list(DEFAULT_TIMEFRAMES)

    def _all_supported_symbols(self) -> list[str]:
        symbols: list[str] = []
        if "bybit" in self.selected_exchanges():
            try:
                symbols.extend(fetch_bybit_linear_symbols())
            except Exception:
                symbols.extend(DEFAULT_SYMBOLS)
        return list(dict.fromkeys(symbols)) or list(DEFAULT_SYMBOLS)

    @staticmethod
    def _strategy_runtime_configs():
        try:
            from app.services.strategy_config_service import strategy_config_service

            return strategy_config_service.runtime_configs()
        except Exception:
            return []

    def _strategy_scope_pairs(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for config in self._strategy_runtime_configs():
            pairs.extend(config.pairs)
        return list(dict.fromkeys(pairs))


def _short_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _context_timeframe_values(params: object) -> list[str]:
    if not isinstance(params, dict):
        return []
    raw_map = params.get("context_timeframe_map")
    if not isinstance(raw_map, dict):
        return []
    return [
        str(value).strip().lower()
        for value in raw_map.values()
        if str(value).strip().lower() not in {"", "default"}
    ]


radar_config_service = RadarConfigService()
