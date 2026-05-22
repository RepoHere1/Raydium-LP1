"""Dashboard HTML/JS wiring (tooltips, hints)."""

import unittest

from raydium_lp1.dashboard_web import _FORM_SECTIONS, _page


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

    def test_page_html_includes_floating_tip_and_hint_styles(self):
        html = _page().decode("utf-8")
        self.assertIn("dash-tip", html)
        self.assertIn("hint-line", html)
        self.assertIn("wireDataTips", html)
        self.assertIn("sec-blurb", html)


if __name__ == "__main__":
    unittest.main()
