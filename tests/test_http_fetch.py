import unittest
from unittest.mock import MagicMock, patch

from raydium_lp1.http_fetch import fetch_json_get


class FetchJsonRetryTests(unittest.TestCase):
    def test_retries_transient_oserror_then_succeeds(self):
        good_resp = MagicMock()
        good_resp.read.return_value = b'{"ok": true}'
        good_resp.headers = MagicMock()
        good_resp.headers.get.return_value = None
        good_resp.__enter__ = MagicMock(return_value=good_resp)
        good_resp.__exit__ = MagicMock(return_value=False)

        calls = {"n": 0}

        def fake_urlopen(_req, timeout=0):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("ssl read interrupted")
            return good_resp

        with patch("raydium_lp1.http_fetch.urlopen", side_effect=fake_urlopen), patch(
            "raydium_lp1.http_fetch.time.sleep"
        ):
            out = fetch_json_get(
                "https://example.test/pools",
                timeout=5,
                headers={"accept": "application/json"},
                max_attempts=4,
            )
        self.assertEqual(out, {"ok": True})
        self.assertEqual(calls["n"], 3)


if __name__ == "__main__":
    unittest.main()
