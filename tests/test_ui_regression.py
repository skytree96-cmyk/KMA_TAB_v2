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

    def test_company_navigation_opens_real_assessment(self) -> None:
        source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
        self.assertIn('("pages/2_assessment.py", "사전·사후 검사")', source)
        self.assertNotIn('("pages/2_assessment.py", "검사 미리보기")', source)
        self.assertIn('("streamlit_app.py", "회원사 운영 화면")', source)
        self.assertNotIn('("streamlit_app.py", "회원사 화면 미리보기")', source)

        setup_source = (ROOT / "pages" / "1_project_setup.py").read_text(encoding="utf-8")
        self.assertIn('"설정 저장 후 실제 검사 시작"', setup_source)
        self.assertNotIn('"설정 저장 후 참여자 화면 확인"', setup_source)

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

    def test_user_guide_explains_project_code_storage_and_session_fallback(self) -> None:
        source = (ROOT / "pages" / "0_user_guide.py").read_text(encoding="utf-8")
        self.assertIn("기획검증용 GitHub 누적 저장", source)
        self.assertIn("교육 참여자 ID 원문은 저장하지 않고 프로젝트별 가명키", source)
        self.assertIn("교육담당자가 전달한 프로젝트 코드를 참여자 화면에 입력", source)
        self.assertIn("사전·사후 완료 결과만 저장", source)
        self.assertIn("미연결 때에는 동일 브라우저에서 시작하거나 기준파일(JSON)", source)

    def test_dark_theme_tokens_and_fixed_paper_report_exist(self) -> None:
        source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
        self.assertIn("@media (prefers-color-scheme:dark)", source)
        self.assertIn("color-scheme:light", source)

    def test_assessment_radio_and_progress_colors_follow_tap_theme(self) -> None:
        source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
        self.assertIn('[data-testid="stRadioOption"] p', source)
        self.assertIn('[data-testid="stRadioOption"][data-selected] p', source)
        self.assertIn('[data-testid="stProgressBarTrack"] > div', source)
        self.assertNotIn('[data-testid="stProgress"] > div > div', source)

    def test_locked_participant_id_remains_readable(self) -> None:
        source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
        self.assertIn('[data-testid="stTextInput"] input:disabled', source)
        self.assertIn('-webkit-text-fill-color:var(--tap-ink) !important', source)

    def test_assessment_uses_focused_card_and_response_tile_grid(self) -> None:
        ui_source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
        page_source = (ROOT / "pages" / "2_assessment.py").read_text(encoding="utf-8")
        self.assertIn(':has(.tap-question-stage-anchor)', ui_source)
        self.assertIn('grid-template-columns:repeat(6,minmax(0,1fr))', ui_source)
        self.assertIn('[data-testid="stRadioOption"]:has(input:checked)', ui_source)
        self.assertIn('--tap-option-selected:#1b4743', ui_source)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))', ui_source)
        self.assertIn('with st.container(border=True):', page_source)
        self.assertIn("question['factor_name_ko']", page_source)
        self.assertIn('class="tap-response-head tap-response-anchor"', page_source)
        self.assertIn('format_func=lambda value: LIKERT_OPTIONS[value]', page_source)
        self.assertIn('label_visibility="collapsed"', page_source)

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
