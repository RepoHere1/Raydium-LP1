import unittest

from raydium_lp1 import strategies


class StrategyPresetTests(unittest.TestCase):
    def test_degen_preset_thresholds(self):
        preset = strategies.get_preset("degen")
        assert preset is not None
        self.assertEqual(preset.min_apr, 500)
        self.assertEqual(preset.min_liquidity_usd, 200)
        self.assertEqual(preset.min_volume_24h_usd, 50)

    def test_aggressive_preset_thresholds(self):
        preset = strategies.get_preset("aggressive")
        assert preset is not None
        self.assertEqual(preset.min_apr, 777)
        self.assertEqual(preset.min_liquidity_usd, 500)
        self.assertEqual(preset.min_volume_24h_usd, 100)

    def test_unknown_strategy_falls_back_to_custom(self):
        self.assertEqual(strategies.normalize_strategy("blastoff"), "custom")
        self.assertIsNone(strategies.get_preset("blastoff"))

    def test_apply_strategy_fills_missing_thresholds(self):
        merged = strategies.apply_strategy({"dry_run": True}, "degen")
        self.assertEqual(merged["min_apr"], 500)
        self.assertEqual(merged["min_liquidity_usd"], 200)
        self.assertEqual(merged["min_volume_24h_usd"], 50)
        self.assertEqual(merged["strategy"], "degen")
        self.assertTrue(merged["dry_run"])

    def test_apply_strategy_does_not_clobber_user_overrides(self):
        merged = strategies.apply_strategy({"min_apr": 1234}, "aggressive")
        self.assertEqual(merged["min_apr"], 1234)
        self.assertEqual(merged["min_liquidity_usd"], 500)

    def test_custom_strategy_passthrough(self):
        merged = strategies.apply_strategy({"min_apr": 50}, "custom")
        self.assertEqual(merged["min_apr"], 50)
        self.assertEqual(merged["strategy"], "custom")
        self.assertNotIn("min_liquidity_usd", merged)

    def test_momentum_preset_thresholds(self):
        preset = strategies.get_preset("momentum")
        assert preset is not None
        self.assertEqual(preset.min_liquidity_usd, 2000)

    def test_fee_rush_alias_normalizes_to_momentum(self):
        self.assertEqual(strategies.normalize_strategy("fee_rush"), "momentum")

    def test_describe_presets_mentions_all_presets(self):
        text = strategies.describe_presets()
        for name in ("conservative", "moderate", "aggressive", "degen", "momentum", "custom"):
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
