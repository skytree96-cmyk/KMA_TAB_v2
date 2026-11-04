"""The signed-in theme is injected with st.html, which sanitizes the markup with DOMPurify."""
from __future__ import annotations

import re
import unittest

from tap.account_theme import ASSETS, account_theme_css, workspace_theme_css


class AccountThemeTests(unittest.TestCase):
    def test_css_assets_contain_no_markup_characters(self):
        # A "<" inside a style block makes DOMPurify drop the whole block, so the
        # console styles silently disappear (2026-11-04: a "<tone>" in a comment).
        for path in sorted(ASSETS.glob("*.css")):
            with self.subTest(file=path.name):
                self.assertNotIn("<", path.read_text(encoding="utf-8"))

    def test_console_layers_are_bundled_in_order(self):
        for css in (account_theme_css(), workspace_theme_css()):
            self.assertLess(css.index("--c2-canvas"), css.index("tap-sec-head"))
            self.assertIsNone(re.search(r"<(?!/?style\b)[A-Za-z/!]", css.split("</style>")[-2].split("<style>")[-1]))


if __name__ == "__main__":
    unittest.main()
