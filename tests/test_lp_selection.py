"""LP selection mode (APR vs momentum HOT)."""

import unittest

from raydium_lp1.lp_selection import (
    LP_SELECTION_APR,
    LP_SELECTION_MOMENTUM,
    is_momentum_hot,
    pick_live_candidate,
    sort_candidates_for_display,
)


class LpSelectionTests(unittest.TestCase):
    def test_apr_picks_highest_apr(self):
        report = {
            "candidates": [
                {"id": "a", "apr": 10, "momentum": {"tier": "hot", "combined_score": 99}},
                {"id": "b", "apr": 500, "momentum": {"tier": "watch", "combined_score": 10}},
            ]
        }

        class C:
            lp_selection_mode = "apr"

        top = pick_live_candidate(report, None, config=C())
        self.assertEqual(top["id"], "b")

    def test_momentum_requires_hot(self):
        report = {
            "candidates": [
                {"id": "a", "apr": 10, "momentum": {"tier": "enter", "combined_score": 99}},
                {"id": "b", "apr": 500, "momentum": {"tier": "watch", "combined_score": 10}},
            ]
        }

        class C:
            lp_selection_mode = "momentum"

        with self.assertRaises(ValueError) as ctx:
            pick_live_candidate(report, None, config=C())
        self.assertIn("HOT", str(ctx.exception))

    def test_momentum_picks_top_hot_score(self):
        report = {
            "candidates": [
                {"id": "a", "apr": 10, "momentum": {"tier": "hot", "combined_score": 70}},
                {"id": "b", "apr": 500, "momentum": {"tier": "hot", "combined_score": 90}},
            ]
        }

        class C:
            lp_selection_mode = "momentum"

        top = pick_live_candidate(report, None, config=C())
        self.assertEqual(top["id"], "b")
        self.assertTrue(is_momentum_hot(top))


if __name__ == "__main__":
    unittest.main()
