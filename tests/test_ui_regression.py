from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.errors import StreamlitAPIException

from tap.ui import _safe_page_link, safe_switch_page


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

    def test_role_switch_does_not_use_page_scoped_radio_state(self) -> None:
        source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
        self.assertNotIn('key="tap_role_selector"', source)
        self.assertIn('key=f"tap_role_{role}"', source)

    def test_user_guide_download_is_pdf_with_simple_label(self) -> None:
        expected_path = '"docs" / "TAP_사용설명서_v3.pdf"'
        sidebar_source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
        page_source = (ROOT / "pages" / "0_user_guide.py").read_text(encoding="utf-8")
        for source in (sidebar_source, page_source):
            self.assertIn(expected_path, source)
            self.assertIn('"application/pdf"', source)
            self.assertNotIn("PPT 사용설명서", source)
            self.assertNotIn("PPT 빠른 사용 가이드", source)

        self.assertIn('"사용설명서"', sidebar_source)
        self.assertIn('"사용설명서 내려받기"', page_source)

        guide_bytes = (ROOT / "docs" / "TAP_사용설명서_v3.pdf").read_bytes()
        self.assertTrue(guide_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(guide_bytes), 100_000)

    def test_dark_theme_tokens_and_fixed_paper_report_exist(self) -> None:
        source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
        self.assertIn("@media (prefers-color-scheme:dark)", source)
        self.assertIn("color-scheme:light", source)

    @patch("tap.ui.st.error")
    @patch("tap.ui.st.switch_page", side_effect=StreamlitAPIException("missing page"))
    def test_safe_switch_keeps_current_page_on_registry_error(self, switch_page, error) -> None:
        self.assertFalse(safe_switch_page("pages/missing.py"))
        switch_page.assert_called_once_with("pages/missing.py")
        error.assert_called_once()

    @patch("tap.ui.st.button")
    @patch("tap.ui.st.page_link", side_effect=KeyError("url_pathname"))
    def test_page_link_falls_back_when_registry_entry_is_incomplete(self, page_link, button) -> None:
        _safe_page_link("pages/missing.py", "안내", key="missing")
        page_link.assert_called_once()
        button.assert_called_once()


if __name__ == "__main__":
    unittest.main()
