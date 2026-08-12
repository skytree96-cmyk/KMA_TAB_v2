from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UiRegressionTests(unittest.TestCase):
    def test_material_icon_font_is_not_overridden(self) -> None:
        source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
        self.assertNotIn('[class*="st-"]', source)
        self.assertIn('[data-testid="stIconMaterial"]', source)
        self.assertIn('font-family:"Material Symbols Rounded"', source)

    def test_builtin_english_page_navigation_is_hidden(self) -> None:
        source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
        self.assertIn('[data-testid="stSidebarNav"] { display:none !important; }', source)

    def test_dark_theme_tokens_and_fixed_paper_report_exist(self) -> None:
        source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
        self.assertIn("@media (prefers-color-scheme:dark)", source)
        self.assertIn("color-scheme:light", source)


if __name__ == "__main__":
    unittest.main()
