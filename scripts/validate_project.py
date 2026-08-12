from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tap.dashboard import load_dashboard_demo, validate_dashboard_demo
from tap.data import (
    integrity_report,
    load_competencies,
    load_course_map,
    load_pilot_item_candidates,
    load_questions,
)
from tap.ui import ROLE_LANDINGS, ROLE_NAV


def main() -> int:
    errors: list[str] = []
    report = integrity_report()
    expected = {
        "question_count": 144,
        "competency_count": 36,
        "unique_question_codes": True,
        "unmapped_question_factors": [],
        "unexpected_empty_competencies": [],
        "factors_not_four_items": {},
    }
    for key, value in expected.items():
        if report.get(key) != value:
            errors.append(f"integrity {key}: expected {value!r}, got {report.get(key)!r}")

    questions = load_questions()
    if sum(q["active"] for q in questions) != 124:
        errors.append("active question count must be 124")
    if any(q["scoring_direction"] != "direct" for q in questions if q["active"]):
        errors.append("active question bank contains non-direct scoring")

    pilot_candidates = load_pilot_item_candidates()
    if len(pilot_candidates) != 16:
        errors.append("pilot item candidate count must be 16")
    if any(row["active_for_scoring"] for row in pilot_candidates):
        errors.append("pilot item candidates must remain inactive before validation")

    active_factors = {c["factor_code"] for c in load_competencies() if c["active_for_scoring"]}
    mapped_factors = {m["factor_code"] for m in load_course_map()}
    if active_factors - mapped_factors:
        errors.append(f"course mappings missing: {sorted(active_factors - mapped_factors)}")

    errors.extend(validate_dashboard_demo(load_dashboard_demo()))

    required_pages = [
        ROOT / "streamlit_app.py",
        ROOT / "pages" / "0_user_guide.py",
        ROOT / "pages" / "1_project_setup.py",
        ROOT / "pages" / "6_kma_dashboard.py",
    ]
    for path in required_pages:
        if not path.exists():
            errors.append(f"required dashboard/page missing: {path.relative_to(ROOT)}")

    navigation_paths = set(ROLE_LANDINGS.values())
    navigation_paths.update(path for items in ROLE_NAV.values() for path, _ in items)
    for relative_path in sorted(navigation_paths):
        if not (ROOT / relative_path).is_file():
            errors.append(f"navigation target missing: {relative_path}")

    ui_source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
    for legacy_reference in (
        "pages/7_user_guide.py",
        '"participant": "임직원"',
        '"kma": "KMA 운영자"',
    ):
        if legacy_reference in ui_source:
            errors.append(f"stale navigation reference remains in tap/ui.py: {legacy_reference}")

    project_source = (ROOT / "pages" / "1_project_setup.py").read_text(encoding="utf-8")
    if "st.multiselect" in project_source or "st.selectbox" in project_source:
        errors.append("project setup must use checkbox/radio selection, not list selectors")

    forbidden_files = [ROOT / ".env", ROOT / ".streamlit" / "secrets.toml"]
    for path in forbidden_files:
        if path.exists():
            errors.append(f"secret file must not be committed: {path.relative_to(ROOT)}")

    for path in ROOT.rglob("*.py"):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"syntax error {path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")

    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("VALIDATION PASSED")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
