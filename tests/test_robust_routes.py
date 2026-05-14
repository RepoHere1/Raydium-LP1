import unittest
from itertools import count

from raydium_lp1 import robust_routes


def make_fetcher(out_amounts_by_source: dict[str, int | None]):
    """Build a fetcher that returns different out_amounts depending on URL."""

    def fetcher(url: str) -> dict:
        for key, value in out_amounts_by_source.items():
            if key in url:
                if value is None:
                    return {"error": "no route"}
                return {"data": {"outAmount": value, "routePlan": [{"swapInfo": {"label": "x"}}]}}
        return {"error": "unrecognized"}

    return fetcher


class CacheTests(unittest.TestCase):
    def test_cache_hit_within_ttl(self):
        clock = count(start=1000.0, step=1.0)
        cache = robust_routes.RouteCache(ttl_seconds=300, _clock=lambda: next(clock))
        cache.put("A", "B", "jupiter", {"source": "jupiter", "ok": True, "out_amount": 99})
        hit = cache.get("A", "B", "jupiter")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["out_amount"], 99)
        self.assertEqual(cache.stats()["hits"], 1)

    def test_cache_miss_after_ttl(self):
        t = [1000.0]

        def clock():
            return t[0]

        cache = robust_routes.RouteCache(ttl_seconds=300, _clock=clock)
        cache.put("A", "B", "jupiter", {"source": "jupiter", "ok": True})
        t[0] += 301
        self.assertIsNone(cache.get("A", "B", "jupiter"))
        self.assertEqual(cache.stats()["misses"], 1)


class BestRouteTests(unittest.TestCase):
    def _isolated_cache(self) -> robust_routes.RouteCache:
        return robust_routes.RouteCache()

    def test_picks_highest_out_amount(self):
        fetcher = make_fetcher({
            "quote-api.jup.ag": 100,
            "transaction-v1.raydium.io": 200,
            "api.orca.so": 150,
        })
        best = robust_routes.best_route(
            "MINTA",
            "MINTB",
            sources=("jupiter", "raydium", "orca"),
            fetcher=fetcher,
            cache=self._isolated_cache(),
        )
        self.assertEqual(best.quality["sources_priced"], 3)
        self.assertEqual(best.best_out_amount, 200)
        self.assertEqual(best.best_source, "raydium")

    def test_falls_back_when_one_source_fails(self):
        fetcher = make_fetcher({
            "quote-api.jup.ag": None,
            "transaction-v1.raydium.io": 250,
            "api.orca.so": None,
        })
        best = robust_routes.best_route(
            "MINTA", "MINTB",
            sources=("jupiter", "raydium", "orca"),
            fetcher=fetcher, cache=self._isolated_cache(),
        )
        self.assertEqual(best.best_source, "raydium")
        self.assertEqual(best.quality["sources_priced"], 1)
        self.assertEqual(best.quality["sources_attempted"], 3)

    def test_caches_repeated_calls(self):
        calls = []

        def fetcher(url):
            calls.append(url)
            return {"data": {"outAmount": 123}}

        cache = self._isolated_cache()
        first = robust_routes.best_route(
            "A", "B", sources=("jupiter",), fetcher=fetcher, cache=cache
        )
        second = robust_routes.best_route(
            "A", "B", sources=("jupiter",), fetcher=fetcher, cache=cache
        )
        self.assertEqual(len(calls), 1)  # second call hit the cache
        self.assertEqual(second.quality["cache_hits"], 1)
        self.assertEqual(first.best_out_amount, 123)

    def test_quality_dispersion_metric(self):
        fetcher = make_fetcher({
            "quote-api.jup.ag": 80,
            "transaction-v1.raydium.io": 100,
        })
        best = robust_routes.best_route(
            "A", "B", sources=("jupiter", "raydium"),
            fetcher=fetcher, cache=self._isolated_cache(),
        )
        self.assertAlmostEqual(best.quality["dispersion_pct"], 20.0)

    def test_orca_source_recognized(self):
        record = robust_routes.check_orca_route(
            "MINTA", "MINTB", fetcher=make_fetcher({"api.orca.so": 333})
        )
        self.assertEqual(record["source"], "orca")
        self.assertTrue(record["ok"])
        self.assertEqual(record["out_amount"], 333)

    def test_raydium_amm_source_recognized(self):
        record = robust_routes.check_raydium_amm_route(
            "MINTA", "MINTB", fetcher=make_fetcher({"transaction-v1.raydium.io": 444})
        )
        self.assertEqual(record["source"], "raydium_amm")
        self.assertEqual(record["out_amount"], 444)

    def test_log_route_quality_includes_dispersion(self):
        fetcher = make_fetcher({"quote-api.jup.ag": 100, "transaction-v1.raydium.io": 150})
        best = robust_routes.best_route(
            "A", "B", sources=("jupiter", "raydium"),
            fetcher=fetcher, cache=self._isolated_cache(),
        )
        line = robust_routes.log_route_quality(best)
        self.assertIn("best=raydium", line)
        self.assertIn("dispersion=", line)


if __name__ == "__main__":
    unittest.main()
