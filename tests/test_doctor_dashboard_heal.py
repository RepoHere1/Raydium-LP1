"""Tests for autonomous dashboard :8844 heal."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from raydium_lp1.doctor_dashboard_heal import (
    heal_dashboard_server,
    heal_rate_limited,
    probe_dashboard,
)


class DoctorDashboardHealTests(unittest.TestCase):
    def test_probe_down_on_bad_port(self) -> None:
        ok, path, err = probe_dashboard(host="127.0.0.1", port=59998, timeout=0.5)
        self.assertFalse(ok)
        self.assertIsNone(path)
        self.assertTrue(err)

    @patch("raydium_lp1.doctor_dashboard_heal.wait_dashboard_ready", return_value=True)
    @patch("raydium_lp1.doctor_dashboard_heal.start_dashboard_process", return_value=["started"])
    @patch("raydium_lp1.doctor_dashboard_heal.stop_dashboard_port", return_value=["stopped"])
    @patch("raydium_lp1.doctor_dashboard_heal.heal_rate_limited", return_value=(True, ""))
    @patch("raydium_lp1.doctor_dashboard_heal.probe_dashboard")
    def test_heal_restarts_when_down(
        self,
        mock_probe,
        _mock_rate,
        _mock_stop,
        _mock_start,
        _mock_wait,
    ) -> None:
        mock_probe.side_effect = [
            (False, None, "connection refused"),
            (True, "/health", None),
        ]
        ok, actions, msg = heal_dashboard_server(port=8844, host="127.0.0.1", heal=True)
        self.assertTrue(ok)
        self.assertTrue(actions)
        self.assertIn("healed", msg)

    @patch("raydium_lp1.doctor_dashboard_heal.probe_dashboard", return_value=(True, "/health", None))
    def test_no_heal_when_already_up(self, _mock_probe) -> None:
        ok, actions, msg = heal_dashboard_server(port=8844, heal=True)
        self.assertTrue(ok)
        self.assertEqual(actions, [])
        self.assertIn("/health", msg)

    def test_rate_limit_blocks_rapid_retries(self) -> None:
        from raydium_lp1.doctor_dashboard_heal import STATE_PATH, _record_attempt_start

        if STATE_PATH.is_file():
            STATE_PATH.unlink()
        _record_attempt_start()
        allowed, reason = heal_rate_limited()
        self.assertFalse(allowed)
        self.assertIn("cooldown", reason)


if __name__ == "__main__":
    unittest.main()
