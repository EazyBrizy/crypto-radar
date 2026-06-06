from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
SCRIPTS_DIR = ROOT_DIR / "scripts"
for path in (BACKEND_DIR, SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core.config import settings  # noqa: E402
from run_strategy_baseline import StrategyBaselineConfig, run_strategy_baseline  # noqa: E402


@dataclass(frozen=True)
class CalibrationWindow:
    start_time: datetime
    end_time: datetime


@dataclass(frozen=True)
class CalibrationConfig:
    strategies: tuple[str, ...]
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    train: CalibrationWindow
    validation: CalibrationWindow
    exchange: str
    output_path: Path | None
    execute: bool


def main(argv: list[str] | None = None) -> int:
    config = _parse_args(argv)
    output: dict[str, Any] = {
        "status": "dry_run" if not config.execute else "completed",
        "config": _config_json(config),
        "thresholds": {
            "min_sample_size": settings.execution_edge_min_sample_size,
            "min_expectancy_after_costs_r": settings.execution_edge_min_expectancy_after_costs_r,
            "min_profit_factor": settings.execution_edge_min_profit_factor,
            "min_validation_sample_size": settings.execution_min_validation_sample_size,
            "min_validation_expectancy_r": settings.execution_min_validation_expectancy_r,
            "min_validation_profit_factor": settings.execution_min_validation_profit_factor,
            "max_validation_drawdown_r": settings.execution_max_validation_drawdown_r,
            "min_entry_touch_rate": settings.execution_min_entry_touch_rate,
            "max_no_entry_rate": settings.execution_max_no_entry_rate,
        },
        "runs": {},
    }
    if config.execute:
        output["runs"] = {
            "train": run_strategy_baseline(_baseline_config(config, config.train, "execution-gate-train")),
            "validation": run_strategy_baseline(
                _baseline_config(config, config.validation, "execution-gate-validation")
            ),
        }
    text = json.dumps(output, indent=2, sort_keys=True, default=_json_default) + "\n"
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def _parse_args(argv: list[str] | None) -> CalibrationConfig:
    parser = argparse.ArgumentParser(description="Calibrate execution-gate train/validation edge metrics.")
    parser.add_argument("--strategies", default="trend_pullback_continuation,volatility_squeeze_breakout,liquidity_sweep_reversal")
    parser.add_argument("--symbols", default="BTCUSDT")
    parser.add_argument("--timeframes", default="15m")
    parser.add_argument("--train-start", required=True)
    parser.add_argument("--train-end", required=True)
    parser.add_argument("--validation-start", required=True)
    parser.add_argument("--validation-end", required=True)
    parser.add_argument("--exchange", default="bybit")
    parser.add_argument("--output")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    return CalibrationConfig(
        strategies=_csv(args.strategies),
        symbols=_csv(args.symbols),
        timeframes=_csv(args.timeframes),
        train=CalibrationWindow(_datetime(args.train_start), _datetime(args.train_end)),
        validation=CalibrationWindow(_datetime(args.validation_start), _datetime(args.validation_end)),
        exchange=args.exchange,
        output_path=Path(args.output) if args.output else None,
        execute=bool(args.execute),
    )


def _baseline_config(config: CalibrationConfig, window: CalibrationWindow, label: str) -> StrategyBaselineConfig:
    return StrategyBaselineConfig(
        strategies=config.strategies,
        symbols=config.symbols,
        timeframes=config.timeframes,
        start_time=window.start_time,
        end_time=window.end_time,
        exchange=config.exchange,
        label=label,
    )


def _config_json(config: CalibrationConfig) -> dict[str, Any]:
    data = asdict(config)
    data["output_path"] = str(config.output_path) if config.output_path is not None else None
    return data


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
