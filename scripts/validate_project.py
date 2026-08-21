from __future__ import annotations

import ast
import hashlib
import os
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


MANIFEST_PATH = ROOT / "MANIFEST_SHA256.txt"
BINARY_RELEASE_SUFFIXES = {
    ".gif",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pptx",
    ".webp",
    ".xlsx",
    ".zip",
}
MANIFEST_EXCLUDED_TOP_LEVEL = {
    ".agents",
    ".codex",
    ".devcontainer",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".tmp",
    "output",
    "tmp",
}
MANIFEST_EXCLUDED_DIRECTORY_NAMES = {
    ".wrangler",
    "__pycache__",
    "node_modules",
}


def deployable_paths() -> set[str]:
    paths: set[str] = set()
    for directory, child_directories, filenames in os.walk(ROOT):
        directory_path = Path(directory)
        if directory_path == ROOT:
            child_directories[:] = [
                name
                for name in child_directories
                if name not in MANIFEST_EXCLUDED_TOP_LEVEL and name != "__pycache__"
            ]
        else:
            child_directories[:] = [
                name
                for name in child_directories
                if name not in MANIFEST_EXCLUDED_DIRECTORY_NAMES
                and not (
                    directory_path == ROOT / "cloudflare"
                    and name == "dist"
                )
            ]
        for filename in filenames:
            path = directory_path / filename
            relative = path.relative_to(ROOT)
            if relative.as_posix() != MANIFEST_PATH.name:
                paths.add(relative.as_posix())
    return paths


def release_file_digest(path: Path) -> str:
    """Hash binary bytes exactly and text with platform-neutral LF endings."""

    payload = path.read_bytes()
    if path.suffix.lower() not in BINARY_RELEASE_SUFFIXES:
        payload = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(payload).hexdigest()


def write_release_manifest() -> None:
    lines = [
        f"{release_file_digest(ROOT / relative_path)}  ./{relative_path}"
        for relative_path in sorted(deployable_paths(), key=str.casefold)
    ]
    MANIFEST_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def validate_release_manifest() -> list[str]:
    """Verify that every deployable file is covered by an exact SHA-256."""

    if not MANIFEST_PATH.is_file():
        return ["release manifest is missing: MANIFEST_SHA256.txt"]

    errors: list[str] = []
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        MANIFEST_PATH.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        digest, separator, raw_path = raw_line.partition("  ")
        relative_path = raw_path.removeprefix("./").replace("\\", "/")
        if (
            not separator
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not relative_path
        ):
            errors.append(f"invalid manifest line {line_number}: {raw_line}")
            continue
        if relative_path in entries:
            errors.append(f"duplicate manifest path: {relative_path}")
            continue
        target = (ROOT / relative_path).resolve()
        try:
            target.relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"manifest path escapes project root: {relative_path}")
            continue
        entries[relative_path] = digest

    deployable = deployable_paths()

    missing_entries = sorted(deployable - set(entries))
    extra_entries = sorted(set(entries) - deployable)
    if missing_entries:
        errors.append(f"manifest paths missing: {missing_entries}")
    if extra_entries:
        errors.append(f"manifest paths not found: {extra_entries}")

    for relative_path in sorted(deployable & set(entries)):
        actual = release_file_digest(ROOT / relative_path)
        if actual != entries[relative_path]:
            errors.append(f"manifest hash mismatch: {relative_path}")
    return errors


def main() -> int:
    errors: list[str] = []
    errors.extend(validate_release_manifest())
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
        ROOT / ".streamlit" / "secrets.toml.example",
        ROOT / "pages" / "0_user_guide.py",
        ROOT / "pages" / "1_project_setup.py",
        ROOT / "pages" / "7_pre_assessment.py",
        ROOT / "pages" / "8_post_assessment.py",
        ROOT / "pages" / "9_manager_dashboard.py",
        ROOT / "pages" / "6_kma_dashboard.py",
        ROOT / "tap" / "github_demo_store.py",
        ROOT / "tap" / "company_scope_ui.py",
        ROOT / "tap" / "open_page.py",
        ROOT / "tap" / "radar.py",
        ROOT / "tap" / "tenant.py",
        ROOT / "docs" / "GITHUB_DEMO_STORE_SETUP.md",
        ROOT / "docs" / "TAP_기업범위_권한설계_v1.md",
        ROOT / "docs" / "TAP_오픈페이지_와이어프레임_v1.html",
        ROOT / "docs" / "TAP_사용설명서_v3.pdf",
        ROOT / "docs" / "TAP_빠른사용가이드_v3.pptx",
        ROOT / "cloudflare" / "build.mjs",
        ROOT / "cloudflare" / "package.json",
        ROOT / "cloudflare" / "pnpm-lock.yaml",
        ROOT / "cloudflare" / "pnpm-workspace.yaml",
        ROOT / "cloudflare" / "wrangler.jsonc",
    ]
    for path in required_pages:
        if not path.exists():
            errors.append(f"required dashboard/page missing: {path.relative_to(ROOT)}")

    guide_pdf = ROOT / "docs" / "TAP_사용설명서_v3.pdf"
    if guide_pdf.is_file():
        guide_bytes = guide_pdf.read_bytes()
        if not guide_bytes.startswith(b"%PDF-") or len(guide_bytes) < 100_000:
            errors.append("PDF user guide is empty or invalid")

    prepost_contract = {
        ROOT / "pages" / "1_project_setup.py": ("교육평가 프로젝트 만들기", "56 <= post_delay_days <= 70"),
        ROOT / "pages" / "2_assessment.py": ("사전·사후 모두 동일하게 최근 8주", "교육 참여자 ID"),
        ROOT / "pages" / "3_individual_report.py": ("교육 전·후 비교", "assessment_completed_by_phase"),
        ROOT / "pages" / "4_organization_report.py": (
            "교육 전후 리포트",
            "session_type",
            "실시 프로젝트에서 리포트 열기",
            "build_pre_post_radar",
            "build_planning_preview_radar",
            "소표본 실제값을 화면에서만 미리보기",
        ),
        ROOT / "pages" / "7_pre_assessment.py": ('"TAP_FORCED_ASSESSMENT_PHASE": "pre"',),
        ROOT / "pages" / "8_post_assessment.py": ('"TAP_FORCED_ASSESSMENT_PHASE": "post"',),
    }
    for path, markers in prepost_contract.items():
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                errors.append(f"pre/post contract missing in {path.relative_to(ROOT)}: {marker}")

    open_page_contract = {
        ROOT / "streamlit_app.py": (
            'stop_on_stale(st, ("tap.open_page",))',
            "from tap.open_page import render_open_page",
            "render_open_page()",
        ),
        ROOT / "tap" / "open_page.py": (
            "__tap_source_sha256__ = source_fingerprint(__file__)",
            "TAP_오픈페이지_와이어프레임_v1.html",
            "TAP_사용설명서_v3.pdf",
            "GUIDE_PDF_BASE64_TOKEN",
            "base64.b64encode",
            "st.html(",
            "unsafe_allow_javascript=True",
        ),
        ROOT / "docs" / "TAP_오픈페이지_와이어프레임_v1.html": (
            "현업 행동의 변화",
            "교육 전/후",
            "사전·사후 비교",
            "표본 보호",
            "header-guide-button",
            "data-guide-download",
            "__TAP_GUIDE_PDF_BASE64__",
            "landingDocument.addEventListener('click'",
            "target.scrollIntoView",
            "streamlitMain.scrollBy",
            "scrollToSection",
            "window.location.assign(link.href)",
        ),
    }
    for path, markers in open_page_contract.items():
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                errors.append(
                    f"open-page contract missing in {path.relative_to(ROOT)}: {marker}"
                )
    cloudflare_contract = {
        ROOT / "cloudflare" / "build.mjs": (
            "https://kmatap.streamlit.app",
            "tap-user-guide.pdf",
            "guidePdfBase64Token",
            "Content-Disposition: attachment",
            "GitHub repository link",
        ),
        ROOT / "cloudflare" / "wrangler.jsonc": (
            '"name": "kma-tap-open"',
            '"directory": "./dist"',
        ),
        ROOT / "cloudflare" / "package.json": (
            '"build": "node build.mjs"',
            '"wrangler"',
        ),
    }
    for path, markers in cloudflare_contract.items():
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                errors.append(
                    f"Cloudflare open-page contract missing in {path.relative_to(ROOT)}: {marker}"
                )
    open_page_html = ROOT / "docs" / "TAP_오픈페이지_와이어프레임_v1.html"
    if open_page_html.is_file():
        source = open_page_html.read_text(encoding="utf-8")
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
                errors.append(f"removed open-page content remains: {forbidden}")

    github_demo_contract = {
        ROOT / "tap" / "github_demo_store.py": (
            'ROOT_PATH = "tap-demo/v1"',
            'DEFAULT_BRANCH = "demo-data"',
            'f"{ROOT_PATH}/companies/{',
            'f"{ROOT_PATH}/project-index/{',
            "def participant_key(",
            "def save_project(",
            "def save_submission(",
            "def request_company_registration(",
            "def review_company_registration(",
            "def list_companies(",
            "def company_approval_status(",
            "def access_granted(",
            "def report_preview_granted(",
            "status == 409",
        ),
        ROOT / "pages" / "0_user_guide.py": (
            "기획검증용 완료 결과 저장",
            "회사 확인과 KMA 승인",
            "회사명과 사업자등록번호 두 항목만 입력",
            "참여 기업 및 관리자 범위",
            "프로젝트 코드를 선택한 검사 화면에 입력",
            "교육 참여자 ID 원문은 저장하지 않고 프로젝트별 가명키",
            "기획검증 접속코드",
        ),
        ROOT / "pages" / "1_project_setup.py": (
            "project_payload_from_state",
            ".save_project(",
        ),
        ROOT / "pages" / "2_assessment.py": (
            ".load_project(",
            "submission_payload_from_state",
            ".save_submission(",
        ),
        ROOT / "pages" / "6_kma_dashboard.py": (
            '"companies": store.list_companies()',
            "참여 기업 및 관리자 범위",
            "합성데이터 기획검증용 신청임을 확인했습니다.",
            "review_company_registration(",
            "사업자등록번호 원문과 개인 관리자 정보",
        ),
        ROOT / "docs" / "GITHUB_DEMO_STORE_SETUP.md": (
            "demo-data",
            "tap-demo/v1/",
            "companies/{company_id}",
            "project-index/{project_id}.json",
            "Repository permissions",
            "Read and write",
            "participant_hash_salt",
            "participant_access_code",
            "report_preview_code",
            "별도 비밀번호나 Secret을 사용하지 않습니다",
            "회사명·사업자등록번호로 기업 참여 요청",
            "참여 기업 목록",
            "사업자등록번호 원문과 관리자 개인 정보는 저장·표시하지 않습니다",
        ),
        ROOT / ".streamlit" / "secrets.toml.example": (
            "[github_demo_store]",
            'branch = "demo-data"',
            "participant_hash_salt",
            "participant_access_code",
            "report_preview_code",
        ),
        ROOT / "tap" / "tenant.py": (
            "def derive_company_identity(",
            "def normalize_business_registration_number(",
            "def hash_company_access_code(",
            "def hash_participant_access_code(",
            "business_registration_number",
        ),
        ROOT / "tap" / "company_scope_ui.py": (
            "def render_company_scope_gate(",
            '"회사명"',
            '"사업자등록번호"',
            "회사 확인·참여 요청",
            "KMA 승인 대기 중",
            "request_company_registration(",
            "company_access_digest",
        ),
        ROOT / "docs" / "TAP_기업범위_권한설계_v1.md": (
            "기업 범위(tenant scope)",
            "기업 신청·승인",
            "KMA 참여 기업 목록",
            "기업 프로젝트 관리자",
            "기업 리포트 열람자",
            "KMA 측정 관리자",
            "KMA 시스템 운영자",
            "관리자 개인을 식별하는 계정 목록이 아니다",
        ),
    }
    for path, markers in github_demo_contract.items():
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                errors.append(
                    f"GitHub demo contract missing in {path.relative_to(ROOT)}: {marker}"
                )

    company_scope_source = (ROOT / "tap" / "company_scope_ui.py").read_text(
        encoding="utf-8"
    )
    if company_scope_source.count("st.text_input(") != 2:
        errors.append(
            "company scope must expose exactly two inputs: company name and business registration number"
        )
    for stale_company_copy in (
        "KMA 부여 기업코드",
        "KMA 신규기업 등록 승인코드",
        "기업 관리자 확인코드",
        "회사 관리자 확인코드",
    ):
        if stale_company_copy in company_scope_source:
            errors.append(
                f"stale company gate copy remains in tap/company_scope_ui.py: {stale_company_copy}"
            )

    kma_review_source = (ROOT / "pages" / "6_kma_dashboard.py").read_text(
        encoding="utf-8"
    )
    for stale_review_gate in (
        "KMA 승인관리 코드",
        "company_registration_code",
        "company_access_granted",
    ):
        if stale_review_gate in kma_review_source:
            errors.append(
                f"stale KMA review gate remains in pages/6_kma_dashboard.py: {stale_review_gate}"
            )

    demo_store_source = (ROOT / "tap" / "github_demo_store.py").read_text(
        encoding="utf-8"
    )
    for stale_review_config in (
        "company_registration_code",
        "def company_access_granted(",
        "    company_access_code: str = field",
    ):
        if stale_review_config in demo_store_source:
            errors.append(
                f"stale KMA review configuration remains in tap/github_demo_store.py: {stale_review_config}"
            )

    navigation_paths = set(ROLE_LANDINGS.values())
    navigation_paths.update(path for items in ROLE_NAV.values() for path, _ in items)
    for relative_path in sorted(navigation_paths):
        if not (ROOT / relative_path).is_file():
            errors.append(f"navigation target missing: {relative_path}")

    ui_source = (ROOT / "tap" / "ui.py").read_text(encoding="utf-8")
    for required_navigation in (
        '("pages/7_pre_assessment.py", "교육 전 검사")',
        '("pages/8_post_assessment.py", "교육 후 검사")',
    ):
        if required_navigation not in ui_source:
            errors.append(f"split assessment navigation missing in tap/ui.py: {required_navigation}")
    for legacy_reference in (
        "pages/7_user_guide.py",
        '("pages/2_assessment.py", "사전·사후 검사")',
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
    if "--write-manifest" in sys.argv:
        write_release_manifest()
        print(f"WROTE {MANIFEST_PATH}")
        sys.exit(0)
    sys.exit(main())
