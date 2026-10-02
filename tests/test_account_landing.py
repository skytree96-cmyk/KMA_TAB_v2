from __future__ import annotations

from html.parser import HTMLParser
import re
import unittest

from tap.account_landing import account_landing_html
from tap.brand import BRAND_VARIANTS, brand_html
from tap.open_page import GUIDE_PDF_PATH, OPEN_PAGE_PATH


class LandingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.app_links = []
        self.visible_copy = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"style", "script"}:
            self.suppressed += 1
        if tag == "a" and "data-app-link" in attrs:
            self.app_links.append(attrs.get("href"))
        if not self.suppressed:
            self.visible_copy.extend(str(attrs[key]) for key in ("aria-label", "title", "alt") if key in attrs)

    def handle_endtag(self, tag):
        if tag in {"style", "script"}:
            self.suppressed -= 1

    def handle_data(self, data):
        if not self.suppressed:
            self.visible_copy.append(data)


class AccountLandingTests(unittest.TestCase):
    def test_all_account_links_require_login_and_copy_describes_assigned_accounts(self):
        page = account_landing_html()
        parser = LandingParser()
        parser.feed(page)
        self.assertEqual(parser.app_links, ["/login"] * 8)
        copy = " ".join(parser.visible_copy)
        for phrase in ("데모", "기획검증", "MVP", "합성", "개인정보를 입력하지", "프로젝트 코드", "tap_role", "원문 ID 미저장"):
            self.assertNotIn(phrase, copy)
        self.assertIn("로그인하고 검사 참여", copy)
        self.assertIn("본인에게 배정된 프로젝트", copy)
        self.assertIn("리포트 예시", copy)
        self.assertIn('id="heroRadar"', page)
        self.assertIn('id="reportRadar"', page)
        self.assertNotIn('class="brand-mark"', page)
        self.assertIn("tap-ci--reverse", page)

    def test_guide_opens_current_instructions_and_legacy_sources_are_preserved(self):
        before = OPEN_PAGE_PATH.read_bytes()
        pdf_before = GUIDE_PDF_PATH.read_bytes()
        page = account_landing_html()
        self.assertIn('const guidePdfBase64 = "";', page)
        self.assertEqual(before, OPEN_PAGE_PATH.read_bytes())
        self.assertEqual(pdf_before, GUIDE_PDF_PATH.read_bytes())
        self.assertIn("기획검증용 공개 데모", before.decode("utf-8"))
        self.assertEqual(page.count('href="/guide"'), 3)
        self.assertNotIn('data-guide-download href=', page)
        self.assertNotIn('href="/tap-user-guide.pdf"', page)
        self.assertNotIn('download="TAP_사용설명서_v3.pdf"', page)

    def test_wordmark_variants_are_static_and_reject_html_injection(self):
        for variant in BRAND_VARIANTS:
            html = brand_html(variant=variant)
            self.assertIn('role="img"', html)
            self.assertIn("교육 전·후", html)
        with self.assertRaises(ValueError):
            brand_html(variant='navy" onclick="alert(1)')


if __name__ == "__main__":
    unittest.main()
