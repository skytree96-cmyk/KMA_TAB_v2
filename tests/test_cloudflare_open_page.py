from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CloudflareOpenPageTests(unittest.TestCase):
    def test_approved_public_copy_and_links_remain_in_source(self) -> None:
        source = (
            ROOT / "docs" / "TAP_오픈페이지_와이어프레임_v1.html"
        ).read_text(encoding="utf-8")

        for phrase in (
            "교육개발 전용 · 채용·승진·보상·성과평가에는 사용하지 않습니다.",
            "최근 8주 업무행동",
            "실제 업무에서 한 행동을 기준으로 응답",
            "조직 결과 공개 기준",
            "각 역량의 전·후 응답자가 5명 이상일 때 공개",
            '<div class="step-icon">중</div>',
            "교육 이수 후 8~10주간 실제 업무에 적용",
            "사용설명서 보기",
            'class="button button-ghost report-action"',
            ".report-copy .report-action",
            "background: var(--teal);",
            "color: #fff;",
        ):
            self.assertIn(phrase, source)

        self.assertNotIn("github.com/skytree96-cmyk/KMA_TAB_v2", source)
        self.assertNotIn('target="_top"', source)
        self.assertIn(
            'href="https://kmatap.streamlit.app/organization_report?tap_role=company"',
            source,
        )
        self.assertNotIn(
            'organization_report?tap_role=company" target="_blank"', source
        )

    def test_cloudflare_build_rewrites_app_routes_and_bundles_guide(self) -> None:
        build_source = (ROOT / "cloudflare" / "build.mjs").read_text(
            encoding="utf-8"
        )

        self.assertIn("https://kmatap.streamlit.app", build_source)
        self.assertIn("const appLinks", build_source)
        self.assertIn("tap-user-guide.pdf", build_source)
        self.assertIn("sourceGuide", build_source)
        self.assertIn("GitHub repository link", build_source)

    def test_wrangler_serves_generated_static_assets(self) -> None:
        config = json.loads(
            (ROOT / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8")
        )

        self.assertEqual("kma-tap-open", config["name"])
        self.assertEqual("./dist", config["assets"]["directory"])


if __name__ == "__main__":
    unittest.main()
