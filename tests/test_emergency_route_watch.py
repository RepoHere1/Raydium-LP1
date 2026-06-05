"""Emergency route watchdog tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from raydium_lp1 import routes
from raydium_lp1.emergency_route_watch import (
    classify_route_probe,
    is_low_human_activity,
    should_emergency_close_on_check,
)


class HumanCycleTests(unittest.TestCase):
    def test_weekend_is_low_activity(self):
        sat = datetime(2026, 5, 30, 14, 0, tzinfo=UTC)
        self.assertTrue(is_low_human_activity(sat))

    def test_weekday_night_is_low_activity(self):
        t = datetime(2026, 5, 28, 23, 0, tzinfo=UTC)
        self.assertTrue(is_low_human_activity(t))

    def test_weekday_day_is_active(self):
        t = datetime(2026, 5, 28, 14, 0, tzinfo=UTC)
        self.assertFalse(is_low_human_activity(t))


class CloseDecisionTests(unittest.TestCase):
    def test_fifth_sketchy_active_hours_closes(self):
        checks = [{"sketchy": True}] * 4 + [{"sketchy": True}]
        fire, _ = should_emergency_close_on_check(
            checks, current_sketchy=True, current_hard=False, low_activity=False, checks_per_day=5
        )
        self.assertTrue(fire)

    def test_fifth_soft_sketchy_low_activity_defers(self):
        checks = [{"sketchy": False}] * 4 + [{"sketchy": True}]
        fire, _ = should_emergency_close_on_check(
            checks, current_sketchy=True, current_hard=False, low_activity=True, checks_per_day=5
        )
        self.assertFalse(fire)

    def test_fifth_hard_sketchy_low_activity_closes(self):
        checks = [{"sketchy": True}] * 4 + [{"sketchy": True}]
        fire, _ = should_emergency_close_on_check(
            checks, current_sketchy=True, current_hard=True, low_activity=True, checks_per_day=5
        )
        self.assertTrue(fire)


class ClassifyRouteTests(unittest.TestCase):
    def test_no_route_is_hard(self):
        sell = routes.SellabilityResult(
            ok=False,
            reasons=["no sell route"],
            token_a=routes.RouteCheck("", "ALT", "", "", False),
            token_b=routes.RouteCheck("", "USDC", "u", "USDC", True),
        )
        sketchy, hard, reasons = classify_route_probe(sell, low_activity=False)
        self.assertTrue(sketchy)
        self.assertTrue(hard)
        self.assertTrue(reasons)


if __name__ == "__main__":
    unittest.main()
