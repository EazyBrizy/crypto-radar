import hashlib
import json
import logging
from dataclasses import dataclass

from app.core.config import settings
from app.schemas.candle import DEFAULT_TIMEFRAMES, RadarConfig, RadarConfigUpdate
from app.exchanges.bybit import fetch_bybit_linear_symbols
from app.services.market_scanner import DEFAULT_SYMBOLS

SUPPORTED_EXCHANGES = ["bybit"]
DEFAULT_MARKET_UNIVERSE_LIMIT = "top_200"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScannerUniverse:
    pairs: tuple[tuple[str, str], ...]
    source: str
    max_pairs: int
    truncated: bool = False
    warning: str | None = None
    estimated_strategy_checks: int = 0


class ScannerUniverseLimitError(ValueError):
    pass


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

    def scanner_universe(
        self,
        *,
        runtime_configs: list[object] | None = None,
        watchlist_pairs: list[tuple[str, str]] | None = None,
        max_pairs: int | None = None,
        truncate_over_limit: bool | None = None,
    ) -> ScannerUniverse:
        configs = [
            config
            for config in (runtime_configs if runtime_configs is not None else self._strategy_runtime_configs())
            if getattr(config, "is_enabled", True)
        ]
        base_pairs, base_source = self._configured_scanner_pairs(watchlist_pairs=watchlist_pairs)
        scoped_pairs = _strategy_scope_pairs(configs)
        unscoped_configs = [config for config in configs if not getattr(config, "pairs", ())]

        if scoped_pairs:
            pairs = list(scoped_pairs)
            if unscoped_configs:
                pairs.extend(
                    pair
                    for pair in base_pairs
                    if _any_unscoped_strategy_matches_pair(unscoped_configs, pair)
                )
                source = _mixed_source(base_source)
            else:
                source = "explicit pairs"
        else:
            pairs = list(base_pairs)
            source = base_source

        normalized_pairs = _normalize_pairs(pairs)
        pair_limit = max(1, max_pairs if max_pairs is not None else settings.max_scanner_pairs)
        should_truncate = (
            settings.truncate_scanner_pairs_over_limit
            if truncate_over_limit is None
            else truncate_over_limit
        )
        truncated = False
        warning: str | None = None
        if len(normalized_pairs) > pair_limit:
            warning = (
                f"Scanner universe has {len(normalized_pairs)} pairs, "
                f"max_scanner_pairs={pair_limit}."
            )
            if not should_truncate:
                logger.warning("%s Scanner start is blocked.", warning)
                raise ScannerUniverseLimitError(f"{warning} Scanner start is blocked.")
            normalized_pairs = normalized_pairs[:pair_limit]
            truncated = True
            warning = f"{warning} Universe was truncated to {pair_limit} pairs."
            logger.warning(warning)

        timeframes = self.selected_timeframes()
        return ScannerUniverse(
            pairs=tuple(normalized_pairs),
            source=source,
            max_pairs=pair_limit,
            truncated=truncated,
            warning=warning,
            estimated_strategy_checks=_estimate_strategy_checks(
                normalized_pairs,
                timeframes,
                configs,
            ),
        )

    def scanner_subscription_hash(self, universe: ScannerUniverse | None = None) -> str:
        universe = universe or self.scanner_universe()
        payload = {
            "pairs": universe.pairs,
            "universe_source": universe.source,
            "max_pairs": universe.max_pairs,
            "truncated": universe.truncated,
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

    def _configured_scanner_pairs(
        self,
        *,
        watchlist_pairs: list[tuple[str, str]] | None = None,
    ) -> tuple[list[tuple[str, str]], str]:
        exchanges = self._normalize_exchanges(self._config.exchanges)
        if self._config.use_all_symbols:
            pairs = self._top_market_universe_pairs(exchanges)
            source = "Top 200"
            if not pairs:
                pairs = [
                    (exchange, symbol)
                    for exchange in exchanges
                    for symbol in self._all_supported_symbols()
                ]
        else:
            symbols = self._normalize_symbols(self._config.symbols)
            pairs = [(exchange, symbol) for exchange in exchanges for symbol in symbols]
            source = (
                "default"
                if exchanges == ["bybit"] and symbols == list(DEFAULT_SYMBOLS)
                else "scanner config"
            )

        resolved_watchlist_pairs = (
            watchlist_pairs
            if watchlist_pairs is not None
            else self._default_watchlist_pairs()
        )
        if resolved_watchlist_pairs:
            before = set(_normalize_pairs(pairs))
            pairs.extend(resolved_watchlist_pairs)
            if set(_normalize_pairs(pairs)) != before and source == "default":
                source = "scanner config"
        return _normalize_pairs(pairs), source

    @staticmethod
    def _top_market_universe_pairs(exchanges: list[str]) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        try:
            from app.core.database import SessionLocal
            from app.services.market_universe_service import list_persisted_market_pairs

            with SessionLocal() as session:
                for exchange in exchanges:
                    if exchange != "bybit":
                        continue
                    pairs.extend(
                        (pair.exchange.code, pair.symbol)
                        for pair in list_persisted_market_pairs(
                            session,
                            exchange=exchange,
                            limit=DEFAULT_MARKET_UNIVERSE_LIMIT,
                        )
                    )
        except Exception as exc:
            logger.warning("Market universe lookup failed; falling back to scanner symbols: %s", exc)
        return _normalize_pairs(pairs)

    @staticmethod
    def _default_watchlist_pairs() -> list[tuple[str, str]]:
        try:
            from app.services.watchlist_service import watchlist_service

            watchlist = watchlist_service.get_default_watchlist()
        except Exception as exc:
            logger.debug("Default watchlist lookup skipped for scanner universe: %s", exc)
            return []
        return _normalize_pairs(
            [(pair.exchange, pair.symbol) for pair in watchlist.pairs]
        )


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


def _normalize_pairs(pairs: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    normalized = [
        (exchange.strip().lower(), symbol.strip().upper())
        for exchange, symbol in pairs
        if exchange.strip() and symbol.strip()
    ]
    return list(dict.fromkeys(normalized))


def _strategy_scope_pairs(configs: list[object]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for config in configs:
        pairs.extend(getattr(config, "pairs", ()) or ())
    return _normalize_pairs(pairs)


def _any_unscoped_strategy_matches_pair(
    configs: list[object],
    pair: tuple[str, str],
) -> bool:
    exchange, _ = pair
    return any(
        not getattr(config, "exchanges", ())
        or exchange in getattr(config, "exchanges", ())
        for config in configs
    )


def _estimate_strategy_checks(
    pairs: list[tuple[str, str]],
    timeframes: list[str],
    configs: list[object],
) -> int:
    if not configs:
        return 0
    checks = 0
    for exchange, symbol in pairs:
        for timeframe in timeframes:
            for config in configs:
                matches = getattr(config, "matches", None)
                if matches is None:
                    continue
                if matches(exchange=exchange, symbol=symbol, timeframe=timeframe):
                    checks += 1
    return checks


def _mixed_source(base_source: str) -> str:
    if base_source == "Top 200":
        return "explicit pairs + Top 200"
    if base_source == "default":
        return "explicit pairs + default"
    return "explicit pairs + scanner config"


radar_config_service = RadarConfigService()
