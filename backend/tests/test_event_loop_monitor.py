import unittest

from app.core.event_loop_monitor import event_loop_lag_ms, should_warn_event_loop_lag


class EventLoopMonitorTest(unittest.TestCase):
    def test_event_loop_lag_ms_never_returns_negative_lag(self) -> None:
        self.assertEqual(event_loop_lag_ms(expected_at=10.0, observed_at=9.5), 0.0)

    def test_event_loop_lag_threshold_is_in_seconds(self) -> None:
        self.assertFalse(should_warn_event_loop_lag(lag_ms=249.0, threshold_seconds=0.25))
        self.assertTrue(should_warn_event_loop_lag(lag_ms=250.0, threshold_seconds=0.25))


if __name__ == "__main__":
    unittest.main()
