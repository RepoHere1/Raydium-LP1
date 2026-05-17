import unittest

from raydium_lp1 import dashboard_web


class DashboardWebPageTests(unittest.TestCase):
    def test_module_imports_and_page_has_shell(self):
        page = dashboard_web._page().decode("utf-8")
        self.assertNotIn("BOOT_JSON", page)
        self.assertNotIn("CLIENT_JS_HERE", page)
        self.assertIn("Raydium-LP1 · mission control", page)
        self.assertIn("form_sections", page)
        self.assertIn("Save settings", page)


if __name__ == "__main__":
    unittest.main()
