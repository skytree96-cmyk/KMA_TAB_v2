from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from streamlit.testing.v1 import AppTest


PAGES = [
    "pages/0_user_guide.py",
    "pages/1_project_setup.py",
    "pages/2_assessment.py",
    "pages/3_individual_report.py",
    "pages/4_organization_report.py",
    "pages/5_question_bank.py",
    "pages/6_kma_dashboard.py",
    "pages/7_pre_assessment.py",
    "pages/8_post_assessment.py",
    "pages/9_manager_dashboard.py",
]


def _assert_clean(app: AppTest, label: str) -> None:
    errors = [str(item.value) for item in app.exception]
    if errors:
        raise AssertionError(f"{label}: {errors}")


def main() -> int:
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=20).run()
    _assert_clean(app, "streamlit_app.py")
    html_nodes = app.get("html")
    if len(html_nodes) != 1:
        raise AssertionError("public open page must render exactly one HTML surface")
    if len(app.get("iframe")) != 0:
        raise AssertionError("public open page must not use a sandboxed iframe")
    if not html_nodes[0].proto.unsafe_allow_javascript:
        raise AssertionError("public open-page JavaScript must be enabled")
    source = str(html_nodes[0].proto.body)
    if "현업 행동의 변화" not in source:
        raise AssertionError("public open-page hero is missing")
    for forbidden in (
        "DATA TRANSPARENCY",
        "현재 저장 방식",
        "짝지은",
        "소표본 보호",
        "교육개발 전용 · 채용·승진·보상·성과평가에는 사용하지 않습니다.",
        "교육 전과 후",
        "교육 전후",
        "교육 전·후",
    ):
        if forbidden in source:
            raise AssertionError(f"removed open-page content remains: {forbidden}")
    for route in (
        "/organization_report?tap_role=company",
        "/project_setup?tap_role=company",
        "/pre_assessment?tap_role=participant",
        "/post_assessment?tap_role=participant",
        "/kma_dashboard?tap_role=kma",
        "/user_guide?tap_role=company",
    ):
        if f'href="https://kmatap.streamlit.app{route}"' not in source:
            raise AssertionError(f"absolute open-page link is missing: {route}")
    if source.count('href="https://kmatap.streamlit.app/user_guide?tap_role=company"') != 3:
        raise AssertionError("top/mobile/footer guide links must all exist")
    for marker in ('href="#method"', "scrollIntoView", "window.location.assign(link.href)"):
        if marker not in source:
            raise AssertionError(f"open-page navigation marker is missing: {marker}")
    for page in PAGES:
        app.switch_page(page).run()
        _assert_clean(app, page)

    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=20).run()
    app.switch_page("pages/1_project_setup.py").run()
    for key in ("optional_AI_USE", "optional_DATA_ANA", "optional_PM_EXEC"):
        app.checkbox(key=key).set_value(True).run()
    if not app.checkbox(key="optional_DX_APPLY").disabled:
        raise AssertionError("fourth specialty checkbox must be disabled")
    if app.checkbox(key="optional_SALES_CORE").disabled:
        raise AssertionError("one job checkbox must remain available after three specialty selections")
    app.checkbox(key="optional_SALES_CORE").set_value(True).run()
    if not app.checkbox(key="optional_MKT_CORE").disabled:
        raise AssertionError("second job checkbox must be disabled")

    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=20).run()
    app.switch_page("pages/9_manager_dashboard.py").run()
    app.button(key="tap_role_participant").click().run()
    _assert_clean(app, "participant role switch")
    if not any(button.label == "교육평가 프로젝트 설정으로 이동" for button in app.button):
        raise AssertionError("assessment landing is missing after participant role switch")
    app.switch_page("pages/8_post_assessment.py").run()
    _assert_clean(app, "post-assessment sidebar entry")
    if not any(
        uploader.label == "교육 전 검사 기준파일(JSON)"
        for uploader in app.get("file_uploader")
    ):
        raise AssertionError("post-assessment baseline entry is missing")
    app.switch_page("pages/3_individual_report.py").run()
    _assert_clean(app, "participant submenu navigation")
    if app.session_state.active_role != "participant":
        raise AssertionError("participant role was reset after opening a submenu")
    if not any("참여자 교육평가 화면" in item.value for item in app.markdown):
        raise AssertionError("participant sidebar was lost after opening a submenu")

    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=20).run()
    app.switch_page("pages/9_manager_dashboard.py").run()
    app.button(key="tap_role_kma").click().run()
    _assert_clean(app, "KMA role switch")
    if not any("회원사 진단 운영 현황" in item.value for item in app.markdown):
        raise AssertionError("KMA dashboard heading is missing after role switch")
    app.switch_page("pages/5_question_bank.py").run()
    _assert_clean(app, "KMA submenu navigation")
    if app.session_state.active_role != "kma":
        raise AssertionError("KMA role was reset after opening a submenu")
    if not any("전체 문항은행 및 예비 유효성 검수" in item.value for item in app.markdown):
        raise AssertionError("question bank is missing after KMA submenu navigation")

    print(
        f"STREAMLIT SMOKE PASSED: home + {len(PAGES)} pages + "
        "checkbox limits + persistent participant/KMA submenu navigation"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
