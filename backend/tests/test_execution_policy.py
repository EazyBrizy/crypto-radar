from __future__ import annotations

import unittest

from app.services.execution_policy import ExecutionPolicyContext, ExecutionPolicyResolver


class ExecutionPolicyResolverTest(unittest.TestCase):
    def test_late_entry_is_skipped_when_rr_cannot_be_recalculated(self) -> None:
        decision = ExecutionPolicyResolver().resolve(
            ExecutionPolicyContext(
                side="long",
                current_price=105,
                entry_min=100,
                entry_max=101,
                min_rr_ratio=2,
                allow_pending_retest=False,
            )
        )

        self.assertEqual(decision.mode, "skip")
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "late_entry_rr_recalculation_required")

    def test_missed_entry_zone_waits_for_retest_when_policy_allows_it(self) -> None:
        decision = ExecutionPolicyResolver().resolve(
            ExecutionPolicyContext(
                side="long",
                current_price=105,
                entry_min=100,
                entry_max=101,
                stop_loss=99,
                take_profit=110,
                min_rr_ratio=2,
                allow_pending_retest=True,
            )
        )

        self.assertEqual(decision.mode, "pending_retest")
        self.assertFalse(decision.can_execute)
        self.assertTrue(decision.should_wait)
        self.assertEqual(decision.reason_code, "entry_zone_missed_wait_for_retest")

    def test_late_entry_requires_recalculated_rr_to_meet_minimum(self) -> None:
        decision = ExecutionPolicyResolver().resolve(
            ExecutionPolicyContext(
                side="long",
                current_price=102,
                entry_min=100,
                entry_max=101,
                stop_loss=99,
                take_profit=108,
                min_rr_ratio=2,
                allow_pending_retest=False,
                max_late_entry_deviation_bps=150,
            )
        )

        self.assertEqual(decision.mode, "late_entry")
        self.assertTrue(decision.can_execute)
        self.assertAlmostEqual(decision.recalculated_rr or 0, 2.0)
        self.assertEqual(decision.reason_code, "late_entry_rr_recalculated")

    def test_probe_entry_is_available_for_small_deviation_with_recalculated_rr(self) -> None:
        decision = ExecutionPolicyResolver().resolve(
            ExecutionPolicyContext(
                side="long",
                current_price=101.05,
                entry_min=100,
                entry_max=101,
                stop_loss=99,
                take_profit=106,
                min_rr_ratio=2,
                allow_pending_retest=False,
                allow_probe=True,
                max_probe_deviation_bps=10,
            )
        )

        self.assertEqual(decision.mode, "probe")
        self.assertTrue(decision.can_execute)
        self.assertEqual(decision.reason_code, "probe_entry_rr_recalculated")

    def test_in_zone_entries_resolve_to_requested_limit_or_market_mode(self) -> None:
        limit_decision = ExecutionPolicyResolver().resolve(
            ExecutionPolicyContext(
                side="long",
                current_price=100.5,
                entry_min=100,
                entry_max=101,
                preferred_mode="limit",
            )
        )
        market_decision = ExecutionPolicyResolver().resolve(
            ExecutionPolicyContext(
                side="long",
                current_price=100.5,
                entry_min=100,
                entry_max=101,
            )
        )

        self.assertEqual(limit_decision.mode, "limit")
        self.assertTrue(limit_decision.can_execute)
        self.assertEqual(market_decision.mode, "market")
        self.assertTrue(market_decision.can_execute)

    def test_market_quality_blocks_execution_before_chasing_price(self) -> None:
        decision = ExecutionPolicyResolver().resolve(
            ExecutionPolicyContext(
                side="long",
                current_price=100.5,
                entry_min=100,
                entry_max=101,
                spread_bps=35,
                max_spread_bps=25,
            )
        )

        self.assertEqual(decision.mode, "skip")
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "execution_spread_limit_exceeded")


if __name__ == "__main__":
    unittest.main()
