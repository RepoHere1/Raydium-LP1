import unittest

from raydium_lp1.rpc_health_gate import RpcHealthGateConfig, evaluate_rpc_health_gate


class RpcHealthGateTests(unittest.TestCase):
    def test_disabled_always_passes(self):
        summary = evaluate_rpc_health_gate(
            RpcHealthGateConfig(enabled=False), None, rpc_count=0
        )
        self.assertTrue(summary.passed)

    def test_no_rpcs_configured_passes_by_default(self):
        summary = evaluate_rpc_health_gate(
            RpcHealthGateConfig(enabled=True, min_healthy_rpcs=1),
            [],
            rpc_count=0,
        )
        self.assertTrue(summary.passed)

    def test_no_rpcs_configured_can_fail(self):
        summary = evaluate_rpc_health_gate(
            RpcHealthGateConfig(
                enabled=True,
                min_healthy_rpcs=1,
                require_when_no_rpc_configured=True,
            ),
            [],
            rpc_count=0,
        )
        self.assertFalse(summary.passed)

    def test_healthy_count_passes(self):
        summary = evaluate_rpc_health_gate(
            RpcHealthGateConfig(enabled=True, min_healthy_rpcs=2),
            [{"ok": True}, {"ok": False}, {"ok": True}],
            rpc_count=3,
        )
        self.assertTrue(summary.passed)
        self.assertEqual(summary.healthy, 2)
        self.assertEqual(summary.total, 3)

    def test_unhealthy_count_fails(self):
        summary = evaluate_rpc_health_gate(
            RpcHealthGateConfig(enabled=True, min_healthy_rpcs=2),
            [{"ok": True}, {"ok": False}, {"ok": False}],
            rpc_count=3,
        )
        self.assertFalse(summary.passed)
        self.assertEqual(summary.healthy, 1)

    def test_summary_as_dict_has_keys(self):
        summary = evaluate_rpc_health_gate(
            RpcHealthGateConfig(enabled=True, min_healthy_rpcs=1),
            [{"ok": True}],
            rpc_count=1,
        )
        data = summary.as_dict()
        self.assertIn("required_healthy", data)
        self.assertIn("healthy_count", data)
        self.assertIn("configured_count", data)
        self.assertIn("passed", data)


if __name__ == "__main__":
    unittest.main()
