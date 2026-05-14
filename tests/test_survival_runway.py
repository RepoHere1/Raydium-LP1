import unittest

from raydium_lp1.survival_runway import SurvivalRunwayConfig, evaluate_survival_runway


def _pool(*, tvl=10_000.0, vol=1_000.0, weekly=7_000.0):
    return {
        "liquidity_usd": tvl,
        "volume_24h_usd": vol,
        "raw": {"week": {"volume": weekly}},
    }


class SurvivalRunwayTests(unittest.TestCase):
    def test_disabled_always_passes(self):
        config = SurvivalRunwayConfig(enabled=False)
        ok, reason = evaluate_survival_runway(_pool(tvl=0, vol=0, weekly=0), config, max_position_usd=25.0)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_passes_when_tvl_volume_and_weekly_are_healthy(self):
        config = SurvivalRunwayConfig(
            min_tvl_multiple_of_position=200,
            min_daily_volume_pct_of_tvl=5.0,
        )
        ok, reason = evaluate_survival_runway(
            _pool(tvl=10_000.0, vol=2_000.0, weekly=14_000.0),
            config,
            max_position_usd=25.0,
        )
        self.assertTrue(ok, msg=reason)

    def test_fails_low_tvl(self):
        config = SurvivalRunwayConfig(min_tvl_multiple_of_position=200)
        ok, reason = evaluate_survival_runway(_pool(tvl=100.0), config, max_position_usd=25.0)
        self.assertFalse(ok)
        self.assertIn("tvl", reason or "")
        self.assertIn("below survival floor", reason or "")

    def test_fails_low_daily_turnover(self):
        config = SurvivalRunwayConfig(
            min_tvl_multiple_of_position=10,
            min_daily_volume_pct_of_tvl=10.0,
        )
        ok, reason = evaluate_survival_runway(
            _pool(tvl=10_000.0, vol=100.0, weekly=14_000.0),
            config,
            max_position_usd=25.0,
        )
        self.assertFalse(ok)
        self.assertIn("vol/TVL", reason or "")

    def test_fails_zero_weekly_when_required(self):
        config = SurvivalRunwayConfig(
            min_tvl_multiple_of_position=10,
            min_daily_volume_pct_of_tvl=1.0,
            require_active_week=True,
        )
        ok, reason = evaluate_survival_runway(
            _pool(tvl=10_000.0, vol=2_000.0, weekly=0.0),
            config,
            max_position_usd=25.0,
        )
        self.assertFalse(ok)
        self.assertIn("weekly volume", reason or "")


if __name__ == "__main__":
    unittest.main()
