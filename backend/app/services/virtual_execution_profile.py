from __future__ import annotations

from typing import Any, cast

from app.core.config import settings
from app.schemas.risk import VirtualExecutionProfile, VirtualFillPolicy

_VALID_PROFILES = {"realistic", "relaxed_paper", "deterministic_test"}
_DEV_TEST_ENVS = {"dev", "development", "local", "test", "testing", "ci"}


def normalize_virtual_execution_profile(
    value: object | None = None,
    *,
    app_env: str | None = None,
) -> VirtualExecutionProfile:
    normalized = str(value or "realistic").strip().lower()
    if normalized not in _VALID_PROFILES:
        normalized = "realistic"
    if normalized == "deterministic_test" and not _is_dev_or_test(app_env or settings.app_env):
        normalized = "realistic"
    return cast(VirtualExecutionProfile, normalized)


def default_virtual_execution_profile(
    user_id: str = "demo_user",
    risk_settings: Any | None = None,
) -> VirtualExecutionProfile:
    del user_id
    configured = getattr(risk_settings, "virtual_execution_profile", None)
    if configured is None and getattr(risk_settings, "virtual_trading_uses_realistic_execution", True) is False:
        configured = "relaxed_paper"
    return normalize_virtual_execution_profile(configured or settings.virtual_execution_profile)


def fill_policy_for_profile(profile: VirtualExecutionProfile) -> VirtualFillPolicy:
    if profile == "deterministic_test":
        return "deterministic_market_fill"
    if profile == "relaxed_paper":
        return "relaxed_market_fallback"
    return "strict_orderbook"


def _is_dev_or_test(app_env: str) -> bool:
    return app_env.strip().lower() in _DEV_TEST_ENVS
