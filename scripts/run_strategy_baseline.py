from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from uuid import uuid4


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.schemas.strategy_lab import StrategyLabComparisonResult, StrategyLabMatrixRequest  # noqa: E402
from app.services.strategy_test_lab import StrategyTestLabService  # noqa: E402
from app.strategies.breakout import STRATEGY_NAME as VOLATILITY_SQUEEZE_BREAKOUT  # noqa: E402
from app.strategies.liquidity_sweep import STRATEGY_NAME as LIQUIDITY_SWEEP_REVERSAL  # noqa: E402
from app.strategies.trend_pullback import STRATEGY_NAME as TREND_PULLBACK_CONTINUATION  # noqa: E402


BASELINE_VERSION = "lab-02-v1"
BASELINE_STRATEGIES: tuple[str, ...] = (
    LIQUIDITY_SWEEP_REVERSAL,
    VOLATILITY_SQUEEZE_BREAKOUT,
    TREND_PULLBACK_CONTINUATION,
)
DEFAULT_SYMBOLS: tuple[str, ...] = ("BTCUSDT",)
DEFAULT_TIMEFRAMES: tuple[str, ...] = ("1h",)
DEFAULT_START_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
DEFAULT_END_TIME = datetime(2026, 2, 1, tzinfo=timezone.utc)

BASELINE_METRIC_KEYS: tuple[str, ...] = (
    "trades_count",
    "wins",
    "losses",
    "win_rate",
    "realized_pnl",
    "expectancy_r",
    "avg_r",
    "profit_factor",
    "max_drawdown",
    "avg_bars_in_trade",
    "mfe",
    "mae",
    "tp1_rate",
    "stop_rate",
    "fees",
    "slippage",
    "funding",
    "risk_rejections",
    "execution_rejections",
)


class StrategyLabServiceProtocol(Protocol):
    def run_matrix(self, request: StrategyLabMatrixRequest) -> StrategyLabComparisonResult:
        ...


@dataclass(frozen=True)
class StrategyBaselineConfig:
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    timeframes: tuple[str, ...] = DEFAULT_TIMEFRAMES
    start_time: datetime = DEFAULT_START_TIME
    end_time: datetime = DEFAULT_END_TIME
    initial_equity: Decimal = Decimal("1000")
    fees_bps: Decimal = Decimal("10")
    slippage_bps: Decimal = Decimal("1")
    warmup_bars: int = 200
    max_bars_in_trade: int | None = 20
    strategy_params: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    output_path: Path | None = None
    exchange: str = "bybit"
    user_id: str = "demo_user"
    baseline_version: str = BASELINE_VERSION
    strategies: tuple[str, ...] = BASELINE_STRATEGIES
    label: str = "LAB-02 current-strategy baseline"


def run_strategy_baseline(
    config: StrategyBaselineConfig,
    *,
    service: StrategyLabServiceProtocol | None = None,
    baseline_id: str | None = None,
    created_at: datetime | None = None,
    code_revision: str | None = None,
) -> dict[str, Any]:
    baseline_id = baseline_id or f"baseline-{uuid4()}"
    created_at = created_at or datetime.now(timezone.utc)
    revision = code_revision if code_revision is not None else safe_code_revision(ROOT_DIR)
    revision_available = revision is not None
    lab_service = service or StrategyTestLabService()

    lab_results: list[StrategyLabComparisonResult] = []
    scenario_results: list[dict[str, Any]] = []
    for strategy in config.strategies:
        request = _lab_request_for_strategy(
            config=config,
            strategy=strategy,
            baseline_id=baseline_id,
            created_at=created_at,
            code_revision=revision,
        )
        result = lab_service.run_matrix(request)
        lab_results.append(result)
        for item in result.runs:
            scenario_results.append(
                _scenario_output(
                    item=item.model_dump(mode="python"),
                    baseline_id=baseline_id,
                    baseline_version=config.baseline_version,
                    code_revision=revision,
                    created_at=created_at,
                )
            )

    output = {
        "baseline_id": baseline_id,
        "baseline_version": config.baseline_version,
        "run_id": baseline_id,
        "lab_run_ids": [str(result.lab_run_id) for result in lab_results],
        "created_at": _isoformat(created_at),
        "code_revision": revision,
        "code_revision_available": revision_available,
        "status": _overall_status(scenario_results),
        "tags": _baseline_tags(
            baseline_id=baseline_id,
            baseline_version=config.baseline_version,
            strategy=None,
            symbol=None,
            timeframe=None,
            code_revision=revision,
            created_at=created_at,
        ),
        "config": _config_output(config),
        "summary": {
            "scenario_count": len(scenario_results),
            "completed_runs": sum(1 for item in scenario_results if item["status"] == "completed"),
            "no_data_runs": sum(1 for item in scenario_results if item["status"] == "no_data"),
            "insufficient_data_runs": sum(
                1 for item in scenario_results if item["status"] == "insufficient_data"
            ),
            "failed_runs": sum(1 for item in scenario_results if item["status"] == "failed"),
        },
        "results": scenario_results,
    }
    if config.output_path is not None:
        write_baseline_output(output, config.output_path)
    return output


def load_config(path: Path) -> StrategyBaselineConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("baseline config must be a JSON object")
    return config_from_mapping(raw)


def config_from_mapping(raw: Mapping[str, Any]) -> StrategyBaselineConfig:
    strategy_params = raw.get("strategy_params") or {}
    if not isinstance(strategy_params, Mapping):
        raise ValueError("strategy_params must be an object keyed by strategy code")
    strategies = _strategy_codes(_strings(raw.get("strategies"), BASELINE_STRATEGIES, "strategies"))
    return StrategyBaselineConfig(
        symbols=_strings(raw.get("symbols"), DEFAULT_SYMBOLS, "symbols"),
        timeframes=_strings(raw.get("timeframes"), DEFAULT_TIMEFRAMES, "timeframes"),
        start_time=_datetime_value(raw.get("start_time"), DEFAULT_START_TIME, "start_time"),
        end_time=_datetime_value(raw.get("end_time"), DEFAULT_END_TIME, "end_time"),
        initial_equity=_decimal_value(raw.get("initial_equity"), Decimal("1000"), "initial_equity"),
        fees_bps=_decimal_value(raw.get("fees_bps"), Decimal("10"), "fees_bps"),
        slippage_bps=_decimal_value(raw.get("slippage_bps"), Decimal("1"), "slippage_bps"),
        warmup_bars=_int_value(raw.get("warmup_bars"), 200, "warmup_bars"),
        max_bars_in_trade=_optional_int_value(raw.get("max_bars_in_trade"), 20, "max_bars_in_trade"),
        strategy_params=_strategy_params(strategy_params),
        output_path=_optional_path(raw.get("output_path")),
        exchange=str(raw.get("exchange") or "bybit"),
        user_id=str(raw.get("user_id") or "demo_user"),
        baseline_version=str(raw.get("baseline_version") or BASELINE_VERSION),
        strategies=strategies,
        label=str(raw.get("label") or "LAB-02 current-strategy baseline"),
    )


def write_baseline_output(output: Mapping[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def safe_code_revision(root_dir: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    revision = result.stdout.strip()
    return revision or None


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config) if args.config is not None else _config_from_args(args)
    output = run_strategy_baseline(config)
    if config.output_path is None:
        print(json.dumps(output, indent=2, sort_keys=True, default=_json_default))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run LAB-02 baseline for current strategies.")
    parser.add_argument("--config", type=Path, help="JSON baseline config path.")
    parser.add_argument("--symbols", nargs="+", help="Symbols, e.g. BTCUSDT ETHUSDT.")
    parser.add_argument("--timeframes", nargs="+", help="Timeframes, e.g. 1h 4h.")
    parser.add_argument("--start-time", help="Inclusive UTC start time.")
    parser.add_argument("--end-time", help="Inclusive UTC end time.")
    parser.add_argument("--initial-equity", default="1000")
    parser.add_argument("--fees-bps", default="10")
    parser.add_argument("--slippage-bps", default="1")
    parser.add_argument("--warmup-bars", type=int, default=200)
    parser.add_argument("--max-bars-in-trade", type=int, default=20)
    parser.add_argument("--strategy-params-json", help="JSON object keyed by strategy code.")
    parser.add_argument("--output-path", type=Path)
    parser.add_argument("--exchange", default="bybit")
    parser.add_argument("--user-id", default="demo_user")
    parser.add_argument("--baseline-version", default=BASELINE_VERSION)
    return parser


def _config_from_args(args: argparse.Namespace) -> StrategyBaselineConfig:
    strategy_params_raw: Mapping[str, Any] = {}
    if args.strategy_params_json:
        parsed = json.loads(args.strategy_params_json)
        if not isinstance(parsed, Mapping):
            raise ValueError("--strategy-params-json must be a JSON object")
        strategy_params_raw = parsed
    return StrategyBaselineConfig(
        symbols=tuple(args.symbols or DEFAULT_SYMBOLS),
        timeframes=tuple(args.timeframes or DEFAULT_TIMEFRAMES),
        start_time=_datetime_value(args.start_time, DEFAULT_START_TIME, "start_time"),
        end_time=_datetime_value(args.end_time, DEFAULT_END_TIME, "end_time"),
        initial_equity=Decimal(str(args.initial_equity)),
        fees_bps=Decimal(str(args.fees_bps)),
        slippage_bps=Decimal(str(args.slippage_bps)),
        warmup_bars=args.warmup_bars,
        max_bars_in_trade=args.max_bars_in_trade,
        strategy_params=_strategy_params(strategy_params_raw),
        output_path=args.output_path,
        exchange=args.exchange,
        user_id=args.user_id,
        baseline_version=args.baseline_version,
        strategies=BASELINE_STRATEGIES,
    )


def _lab_request_for_strategy(
    *,
    config: StrategyBaselineConfig,
    strategy: str,
    baseline_id: str,
    created_at: datetime,
    code_revision: str | None,
) -> StrategyLabMatrixRequest:
    params: dict[str, Any] = {
        "strategy_params": dict(config.strategy_params.get(strategy, {})),
    }
    tags = _baseline_tags(
        baseline_id=baseline_id,
        baseline_version=config.baseline_version,
        strategy=strategy,
        symbol=None,
        timeframe=None,
        code_revision=code_revision,
        created_at=created_at,
    )
    return StrategyLabMatrixRequest(
        user_id=config.user_id,
        exchange=config.exchange,
        strategies=[strategy],
        symbols=list(config.symbols),
        timeframes=list(config.timeframes),
        start_time=config.start_time,
        end_time=config.end_time,
        initial_equity=config.initial_equity,
        fees_bps=config.fees_bps,
        slippage_bps=config.slippage_bps,
        max_bars_in_trade=config.max_bars_in_trade,
        warmup_bars=config.warmup_bars,
        mode="baseline",
        label=config.label,
        tags=tags,
        params=params,
        strategy_version=config.baseline_version,
    )


def _scenario_output(
    *,
    item: Mapping[str, Any],
    baseline_id: str,
    baseline_version: str,
    code_revision: str | None,
    created_at: datetime,
) -> dict[str, Any]:
    strategy = str(item["strategy"])
    symbol = str(item["symbol"])
    timeframe = str(item["timeframe"])
    metrics = _baseline_metrics(
        status=str(item["status"]),
        summary=_mapping(item.get("summary")),
        metrics=_mapping(item.get("metrics")),
    )
    return {
        "run_id": str(item["lab_run_id"]),
        "baseline_id": baseline_id,
        "scenario_id": item["scenario_id"],
        "status": item["status"],
        "strategy": strategy,
        "exchange": item["exchange"],
        "symbol": symbol,
        "timeframe": timeframe,
        "tags": _baseline_tags(
            baseline_id=baseline_id,
            baseline_version=baseline_version,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            code_revision=code_revision,
            created_at=created_at,
        ),
        "metrics": metrics,
        "assumptions": item.get("assumptions") or {},
        "error": item.get("error"),
        "created_at": _isoformat(created_at),
    }


def _baseline_metrics(
    *,
    status: str,
    summary: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    if status in {"no_data", "insufficient_data", "failed"}:
        return {key: None for key in BASELINE_METRIC_KEYS}
    return {
        "trades_count": _coalesce(summary.get("total_trades"), metrics.get("trades_count")),
        "wins": metrics.get("wins"),
        "losses": metrics.get("losses"),
        "win_rate": _coalesce(summary.get("win_rate"), metrics.get("winrate")),
        "realized_pnl": _coalesce(metrics.get("realized_pnl"), metrics.get("pnl")),
        "expectancy_r": _coalesce(summary.get("expectancy_r"), metrics.get("expectancy_r")),
        "avg_r": summary.get("avg_r"),
        "profit_factor": _coalesce(summary.get("profit_factor"), metrics.get("profit_factor")),
        "max_drawdown": _coalesce(summary.get("max_drawdown"), metrics.get("max_drawdown_pct")),
        "avg_bars_in_trade": _coalesce(summary.get("avg_bars_in_trade"), metrics.get("avg_bars_in_trade")),
        "mfe": metrics.get("mfe_r_avg"),
        "mae": metrics.get("mae_r_avg"),
        "tp1_rate": _coalesce(summary.get("tp1_rate"), metrics.get("tp1_rate")),
        "stop_rate": _coalesce(summary.get("stop_rate"), metrics.get("stop_rate")),
        "fees": _coalesce(summary.get("fees_paid"), metrics.get("fees_total")),
        "slippage": _coalesce(summary.get("slippage_paid"), metrics.get("slippage_total")),
        "funding": metrics.get("funding_total"),
        "risk_rejections": _coalesce(summary.get("risk_rejections"), metrics.get("risk_rejections")),
        "execution_rejections": _coalesce(
            summary.get("execution_rejections"),
            metrics.get("execution_rejections"),
        ),
    }


def _baseline_tags(
    *,
    baseline_id: str,
    baseline_version: str,
    strategy: str | None,
    symbol: str | None,
    timeframe: str | None,
    code_revision: str | None,
    created_at: datetime,
) -> dict[str, str]:
    tags = {
        "source": "baseline",
        "baseline_id": baseline_id,
        "baseline_version": baseline_version,
        "candle_state": "closed",
        "created_at": _isoformat(created_at),
    }
    if strategy is not None:
        tags["strategy"] = strategy
    if symbol is not None:
        tags["symbol"] = symbol
    if timeframe is not None:
        tags["timeframe"] = timeframe
    if code_revision is not None:
        tags["code_revision"] = code_revision
    return tags


def _config_output(config: StrategyBaselineConfig) -> dict[str, Any]:
    return {
        "exchange": config.exchange,
        "user_id": config.user_id,
        "strategies": list(config.strategies),
        "symbols": list(config.symbols),
        "timeframes": list(config.timeframes),
        "start_time": _isoformat(config.start_time),
        "end_time": _isoformat(config.end_time),
        "initial_equity": str(config.initial_equity),
        "fees_bps": str(config.fees_bps),
        "slippage_bps": str(config.slippage_bps),
        "warmup_bars": config.warmup_bars,
        "max_bars_in_trade": config.max_bars_in_trade,
        "strategy_params": {
            strategy: dict(params) for strategy, params in config.strategy_params.items()
        },
        "output_path": str(config.output_path) if config.output_path is not None else None,
    }


def _overall_status(results: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(item.get("status")) for item in results}
    if not statuses:
        return "no_data"
    if "failed" in statuses:
        return "failed"
    if statuses == {"no_data"}:
        return "no_data"
    if statuses <= {"no_data", "insufficient_data"}:
        return "insufficient_data"
    return "completed"


def _strings(value: Any, default: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if value is None:
        return default
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    normalized = tuple(str(item).strip() for item in value if str(item).strip())
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _strategy_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    allowed = set(BASELINE_STRATEGIES)
    unknown = [value for value in values if value not in allowed]
    if unknown:
        raise ValueError(f"Unknown baseline strategies: {', '.join(unknown)}")
    return values


def _strategy_params(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for strategy, params in value.items():
        if strategy not in BASELINE_STRATEGIES:
            raise ValueError(f"Unknown strategy_params key: {strategy}")
        if not isinstance(params, Mapping):
            raise ValueError(f"strategy_params.{strategy} must be an object")
        result[str(strategy)] = dict(params)
    return result


def _datetime_value(value: Any, default: datetime, field_name: str) -> datetime:
    if value is None:
        return default
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO-8601 datetime")
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _decimal_value(value: Any, default: Decimal, field_name: str) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field_name} must be decimal-compatible") from exc


def _int_value(value: Any, default: int, field_name: str) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _optional_int_value(value: Any, default: int | None, field_name: str) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be an integer or null") from exc


def _optional_path(value: Any) -> Path | None:
    if value is None:
        return None
    return Path(str(value))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _isoformat(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


if __name__ == "__main__":
    raise SystemExit(main())
