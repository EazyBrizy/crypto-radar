from pathlib import Path

from app.services.reason_codes import KNOWN_REASON_CODES, normalize_reason_code, normalize_reason_codes


def test_known_reason_codes_have_frontend_translations() -> None:
    dictionary = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n" / "dictionary.ts"
    source = dictionary.read_text(encoding="utf-8")

    missing = [
        code
        for code in sorted(KNOWN_REASON_CODES)
        if f"{code}:" not in source
    ]

    assert missing == []


def test_legacy_reason_messages_normalize_to_codes() -> None:
    assert normalize_reason_code("Required margin exceeds available balance.") == "margin_exceeds_balance"
    assert normalize_reason_code("Pending entry signal is missing.") == "pending_entry_signal_missing"
    assert normalize_reason_code("Signal is terminal at trigger time: expired.") == "signal_terminal_at_trigger"
    assert normalize_reason_codes([
        "spread_above_1_percent_market_order_blocked; expected_slippage_above_1_5_percent",
        "Required margin exceeds available balance.",
    ]) == [
        "spread_above_1_percent_market_order_blocked",
        "expected_slippage_above_1_5_percent",
        "margin_exceeds_balance",
    ]
