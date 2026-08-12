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
]


def _assert_clean(app: AppTest, label: str) -> None:
    errors = [str(item.value) for item in app.exception]
    if errors:
        raise AssertionError(f"{label}: {errors}")


def main() -> int:
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=20).run()
    _assert_clean(app, "streamlit_app.py")
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
    app.radio(key="tap_role_selector").set_value("참여자").run()
    _assert_clean(app, "participant role switch")
    if not any(button.label == "프로젝트 설정으로 이동" for button in app.button):
        raise AssertionError("assessment landing is missing after participant role switch")

    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=20).run()
    app.radio(key="tap_role_selector").set_value("KMA 관리자").run()
    _assert_clean(app, "KMA role switch")
    if not any("회원사 진단 운영 현황" in item.value for item in app.markdown):
        raise AssertionError("KMA dashboard heading is missing after role switch")

    print(
        f"STREAMLIT SMOKE PASSED: home + {len(PAGES)} pages + "
        "checkbox limits + participant/KMA role switches"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
