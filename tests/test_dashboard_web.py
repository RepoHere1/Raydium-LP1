"""Dashboard HTML/JS wiring (tooltips, hints)."""

import unittest
from pathlib import Path

from raydium_lp1.dashboard_web import REPO_ROOT, _FORM_SECTIONS, _page


class DashboardWebPageTests(unittest.TestCase):
    def test_form_sections_carry_help_for_every_field(self):
        keys = [f["key"] for sec in _FORM_SECTIONS for f in sec["fields"]]
        for sec in _FORM_SECTIONS:
            for f in sec["fields"]:
                self.assertIn(
                    "help",
                    f,
                    msg=f"missing help for field key={f.get('key')!r} in section {sec.get('title')!r}",
                )
                self.assertTrue(
                    (f.get("help") or "").strip(),
                    msg=f"empty help for {f.get('key')!r}",
                )
        self.assertGreater(len(keys), 20)

    def test_sections_have_blurb_metadata(self):
        for sec in _FORM_SECTIONS:
            self.assertIn("section_help", sec, msg=f"missing section_help for {sec.get('title')!r}")
            self.assertIn("section_rec", sec, msg=f"missing section_rec for {sec.get('title')!r}")

    def test_page_html_includes_css_popover_classes(self):
        html = _page().decode("utf-8")
        self.assertIn("fw-pop", html)
        self.assertIn("sec-hw", html)
        self.assertIn("mode-bar", html)
        self.assertIn("/dashboard_client.js", html)
        self.assertIn("tab-panel", html)
        self.assertIn("wall-live", html)
        self.assertIn("wall-demo", html)
        self.assertIn("lp-order-entry", html)
        self.assertIn("panel-lp-order", html)
        self.assertIn("jump-lp-entry", html)
        self.assertIn("fo-lp", html)
        self.assertIn("btn-mode-demo", html)
        self.assertIn("Funnel &amp; settings", html)
        self.assertIn("Raw JSON", html)
        self.assertIn("json-pre", html)
        self.assertNotIn("<<<<<<<", html)
        self.assertNotIn(">>>>>>>", html)
        js = (REPO_ROOT / "web" / "dashboard_client.js").read_text(encoding="utf-8")
        self.assertIn("renderAll", js)
        self.assertNotIn("<<<<<<<", js)
        self.assertNotIn(">>>>>>>", js)

    def test_page_includes_rpc_health_panel(self):
        html = _page().decode("utf-8")
        self.assertIn('id="rpc"', html)
        js = (REPO_ROOT / "web" / "dashboard_client.js").read_text(encoding="utf-8")
        self.assertIn("renderRpcHealth", js)

    def test_dashboard_client_has_run_scan_button(self):
        js = (REPO_ROOT / "web" / "dashboard_client.js").read_text(encoding="utf-8")
        self.assertIn("scan-run-now", js)
        self.assertIn("/api/scan/run", js)
        web_py = (REPO_ROOT / "src" / "raydium_lp1" / "dashboard_web.py").read_text(encoding="utf-8")
        self.assertIn("/api/scan/run", web_py)
        self.assertIn("/api/scan/status", web_py)

    def test_normalize_settings_mode_patch(self):
        from raydium_lp1.dashboard_web import _normalize_settings_mode_patch

        p = _normalize_settings_mode_patch({"dry_run": False})
        self.assertEqual(p["mode"], "live")
        self.assertFalse(p["dry_run"])
        p2 = _normalize_settings_mode_patch({"mode": "demo"})
        self.assertTrue(p2["dry_run"])


if __name__ == "__main__":
    unittest.main()
