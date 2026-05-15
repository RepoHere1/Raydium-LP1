import json
import unittest

from raydium_lp1 import data_provenance
from raydium_lp1.scanner import ScannerConfig


class DataProvenanceTests(unittest.TestCase):
    def test_build_provenance_lists_live_and_non_live(self):
        config = ScannerConfig()
        prov = data_provenance.build_provenance(config=config)
        self.assertIn("raydium_pool_list", prov["live_endpoints"])
        self.assertTrue(prov["non_live_components"])
        stubs = [c for c in prov["non_live_components"] if c["source"] in ("STUB", "MODELED", "DISABLED")]
        self.assertGreaterEqual(len(stubs), 3)

    def test_banner_mentions_provenance_file(self):
        text = data_provenance.print_live_sources_banner(ScannerConfig())
        self.assertIn("data_provenance.json", text)


if __name__ == "__main__":
    unittest.main()
