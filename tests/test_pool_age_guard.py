import unittest
from datetime import UTC, datetime, timedelta

from raydium_lp1.pool_age_guard import (
    PoolAgeGuardConfig,
    evaluate_pool_age_guard,
    extract_pool_open_time,
    pool_age_seconds,
)


def _pool(open_time):
    return {"raw": {"openTime": open_time}}


class PoolAgeGuardTests(unittest.TestCase):
    def test_disabled_always_passes(self):
        config = PoolAgeGuardConfig(enabled=False)
        ok, reason = evaluate_pool_age_guard({"raw": {}}, config)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_rejects_pool_younger_than_min_age(self):
        now = datetime.now(UTC)
        recent = (now - timedelta(minutes=5)).timestamp()
        config = PoolAgeGuardConfig(enabled=True, min_age_minutes=60)
        ok, reason = evaluate_pool_age_guard(_pool(recent), config, now=now)
        self.assertFalse(ok)
        self.assertIn("below min", reason)

    def test_passes_pool_older_than_min_age(self):
        now = datetime.now(UTC)
        older = (now - timedelta(hours=2)).timestamp()
        config = PoolAgeGuardConfig(enabled=True, min_age_minutes=60)
        ok, reason = evaluate_pool_age_guard(_pool(older), config, now=now)
        self.assertTrue(ok, msg=reason)

    def test_unknown_age_fails_closed_by_default(self):
        config = PoolAgeGuardConfig(enabled=True)
        ok, reason = evaluate_pool_age_guard({"raw": {}}, config)
        self.assertFalse(ok)
        self.assertIn("unknown", reason)

    def test_unknown_age_fail_open(self):
        config = PoolAgeGuardConfig(enabled=True, fail_open_when_unknown=True)
        ok, _ = evaluate_pool_age_guard({"raw": {}}, config)
        self.assertTrue(ok)

    def test_max_age_cap_rejects_old_pools(self):
        now = datetime.now(UTC)
        ancient = (now - timedelta(days=10)).timestamp()
        config = PoolAgeGuardConfig(enabled=True, min_age_minutes=1, max_age_days=3)
        ok, reason = evaluate_pool_age_guard(_pool(ancient), config, now=now)
        self.assertFalse(ok)
        self.assertIn("above max", reason)

    def test_ms_timestamp_accepted(self):
        now = datetime.now(UTC)
        ms = int((now - timedelta(hours=2)).timestamp() * 1000)
        seconds = extract_pool_open_time({"openTime": ms})
        self.assertIsNotNone(seconds)
        self.assertLess(abs(seconds - (ms / 1000.0)), 1.0)

    def test_pool_age_seconds_returns_none_for_unknown(self):
        self.assertIsNone(pool_age_seconds({"raw": {}}))


if __name__ == "__main__":
    unittest.main()
