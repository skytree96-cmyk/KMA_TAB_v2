from __future__ import annotations

from typing import Any, Mapping

import pandas as pd
import streamlit as st

from tap.runtime_guard import stop_on_stale


stop_on_stale(st, ("tap.dashboard", "tap.github_demo_store", "tap.ui"))

from tap.dashboard import (
    build_kma_persistent_dashboard,
    fetch_store_snapshot,
    format_kma_organization_rows,
    load_dashboard_demo,
)
from tap.data import integrity_report, load_course_map, load_courses
from tap.github_demo_store import DemoStoreConfig, DemoStoreError, GitHubDemoStore
from tap.ui import callout, metric_grid, page_header, setup_page


setup_page("KMA 대시보드", "T")


_COMPANY_STATUS_LABELS = {
    "pending": "승인 대기",
    "approved": "승인 완료",
    "rejected": "승인 거절",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _company_status(company: Mapping[str, Any]) -> str:
    """Normalize legacy registries as approved without exposing raw identity data."""

    status = _clean(company.get("approval_status")).lower() or "approved"
    return status if status in _COMPANY_STATUS_LABELS else "pending"


def _display_time(value: Any) -> str:
    rendered = _clean(value).replace("T", " ")
    return rendered[:16] if rendered else "-"


def _company_admin_rows(
    companies: list[Mapping[str, Any]],
    projects: list[Mapping[str, Any]],
    submissions: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return a privacy-minimal KMA registry view.

    The public planning demo has one company-manager scope per company, not
    individually identifiable manager accounts. Raw business registration
    numbers and manager access proofs therefore never enter this table.
    """

    projects_by_company: dict[str, int] = {}
    pre_by_company: dict[str, int] = {}
    post_by_company: dict[str, int] = {}
    for project in projects:
        company_id = _clean(project.get("company_id"))
        if company_id:
            projects_by_company[company_id] = projects_by_company.get(company_id, 0) + 1
    for submission in submissions:
        company_id = _clean(submission.get("company_id"))
        phases = submission.get("phases")
        if not company_id or not isinstance(phases, Mapping):
            continue
        pre = phases.get("pre")
        post = phases.get("post")
        if isinstance(pre, Mapping) and pre.get("completed") is True:
            pre_by_company[company_id] = pre_by_company.get(company_id, 0) + 1
        if isinstance(post, Mapping) and post.get("completed") is True:
            post_by_company[company_id] = post_by_company.get(company_id, 0) + 1

    ordered = sorted(
        companies,
        key=lambda company: (
            {"pending": 0, "approved": 1, "rejected": 2}[
                _company_status(company)
            ],
            _clean(company.get("company_name")),
        ),
    )
    rows = [
        {
            "회사명": _clean(company.get("company_name")) or "이름 미등록 기업",
            "승인 상태": _COMPANY_STATUS_LABELS[_company_status(company)],
            "관리자 범위": "1개 회사",
            "프로젝트": projects_by_company.get(_clean(company.get("company_id")), 0),
            "교육 전 완료": pre_by_company.get(_clean(company.get("company_id")), 0),
            "교육 후 완료": post_by_company.get(_clean(company.get("company_id")), 0),
            "신청일": _display_time(
                company.get("requested_at") or company.get("created_at")
            ),
            "검토일": _display_time(company.get("reviewed_at")),
        }
        for company in ordered
    ]

    # Projects created before company scoping have no company_id and therefore
    # cannot be truthfully attributed to a company. Keep them visible as one
    # explicit migration bucket instead of silently dropping historical demo
    # activity from the KMA company view.
    legacy_projects = [
        project for project in projects if not _clean(project.get("company_id"))
    ]
    legacy_submissions = [
        submission
        for submission in submissions
        if not _clean(submission.get("company_id"))
    ]
    if legacy_projects or legacy_submissions:
        legacy_pre = 0
        legacy_post = 0
        for submission in legacy_submissions:
            phases = submission.get("phases")
            if not isinstance(phases, Mapping):
                continue
            pre = phases.get("pre")
            post = phases.get("post")
            legacy_pre += int(isinstance(pre, Mapping) and pre.get("completed") is True)
            legacy_post += int(isinstance(post, Mapping) and post.get("completed") is True)
        rows.append(
            {
                "회사명": "기존 미분류 데이터",
                "승인 상태": "회사 연결 필요",
                "관리자 범위": "기업 정보 없음",
                "프로젝트": len(legacy_projects),
                "교육 전 완료": legacy_pre,
                "교육 후 완료": legacy_post,
                "신청일": "-",
                "검토일": "-",
            }
        )

    return rows


@st.cache_data(ttl=30, show_spinner=False)
def _read_github_demo_snapshot(_secrets: object) -> dict[str, object]:
    config = DemoStoreConfig.from_sources(secrets=_secrets)
    store = GitHubDemoStore(config)
    status = store.status()
    if not status["read_enabled"]:
        return {
            "status": status,
            "companies": [],
            "projects": [],
            "submissions": [],
        }
    return {
        "status": status,
        "companies": store.list_companies(),
        **fetch_store_snapshot(store),
    }


dashboard = load_dashboard_demo()["kma"]
dashboard_source = "sample"
store_error = ""
store_status: dict[str, Any] = {}
stored_companies: list[Mapping[str, Any]] = []
stored_projects: list[Mapping[str, Any]] = []
stored_submissions: list[Mapping[str, Any]] = []
try:
    demo_store_secrets: object = dict(st.secrets)
except Exception:  # No secrets file is the normal local-development state.
    demo_store_secrets = {}
try:
    stored = _read_github_demo_snapshot(demo_store_secrets)
    store_status = dict(stored["status"])
    if store_status.get("read_enabled"):
        stored_companies = list(stored.get("companies") or [])
        stored_projects = list(stored.get("projects") or [])
        stored_submissions = list(stored.get("submissions") or [])
        persistent_dashboard = build_kma_persistent_dashboard(
            stored_submissions, stored_projects
        )
        if persistent_dashboard["has_data"] or stored_companies:
            dashboard = persistent_dashboard
            dashboard_source = "store"
except DemoStoreError as exc:
    store_error = str(exc)
integrity = integrity_report()

page_header(
    "KMA 운영 화면",
    "회원사 진단 운영 현황",
    "기획검증 프로젝트의 현재 완료 집계, 진단 버전과 교육과정 매핑을 확인합니다.",
    badge="KMA 관리자 화면",
    badge_tone="amber",
)

st.warning(
    "현재 KMA 역할 전환은 공개 데모의 화면 미리보기이며 로그인·권한 인증이 아닙니다. "
    "실제 회원사 데이터를 운영하기 전 계정 인증·RBAC·감사로그를 적용해야 합니다."
)

if dashboard_source == "store":
    refresh_col, source_col = st.columns([1, 3])
    with refresh_col:
        if st.button("누적 데이터 새로고침", width="stretch"):
            _read_github_demo_snapshot.clear()
            st.rerun()
    with source_col:
        callout(
            "기획검증 누적 실데이터",
            "프로젝트·참여자·교육 전후 완료 수치는 기획검증용 저장소의 실제 완료 제출을 집계했습니다. 원문 참여자 ID와 개인점수는 표시하지 않습니다.",
            icon="ⓘ",
        )
else:
    reason = (
        f"누적 저장소 조회 오류({store_error})로 목업을 표시합니다."
        if store_error
        else "누적 완료 제출이 없거나 기획검증용 저장소가 설정되지 않아 목업을 표시합니다."
    )
    callout(
        "운영 목업 데이터",
        f"{reason} 회원사·프로젝트·응답 수치는 화면 검증용 예시이며, 문항은행 수치만 현재 배포 데이터에서 계산합니다.",
        icon="β",
        tone="warn",
    )
    if store_error and st.button("누적 데이터 다시 읽기"):
        _read_github_demo_snapshot.clear()
        st.rerun()
metric_grid(dashboard["metrics"])

st.markdown("### 참여 기업 및 관리자 범위")
st.caption(
    "회사명과 승인 상태, 회사별 운영 건수만 표시합니다. 사업자등록번호 원문과 개인 관리자 정보는 "
    "저장·표시하지 않으며, 현재 데모에서는 기업마다 하나의 관리자 범위를 둡니다."
)
company_rows = _company_admin_rows(
    stored_companies,
    stored_projects,
    stored_submissions,
)
if company_rows:
    st.dataframe(pd.DataFrame(company_rows), hide_index=True, width="stretch")
else:
    st.info(
        "아직 저장된 기업 신청이 없습니다."
        if store_status.get("read_enabled")
        else "기획검증용 저장소를 연결하면 기업 신청과 승인 상태가 표시됩니다."
    )

pending_companies = [
    company for company in stored_companies if _company_status(company) == "pending"
]
if pending_companies:
    with st.container(border=True):
        st.markdown("#### 신규 기업 승인 관리")
        st.caption(
            "공개 데모의 KMA 역할 전환은 인증이 아닙니다. 승인·거절 저장은 별도의 "
            "KMA 승인관리 코드가 일치할 때만 가능합니다."
        )
        pending_by_id = {
            _clean(company.get("company_id")): company for company in pending_companies
        }
        selected_company_id = st.selectbox(
            "승인 대기 기업",
            options=list(pending_by_id),
            format_func=lambda company_id: (
                _clean(pending_by_id[company_id].get("company_name"))
                or "이름 미등록 기업"
            ),
            key="_kma_company_review_target",
        )
        management_code = st.text_input(
            "KMA 승인관리 코드",
            type="password",
            key="_kma_company_review_code",
            help="Streamlit Secrets의 신규기업 승인관리 코드와 비교하며 저장하지 않습니다.",
        )
        reviewer_note = st.text_area(
            "검토 메모(선택)",
            max_chars=300,
            key="_kma_company_review_note",
            placeholder="거절 시 사유를 입력해 주세요. 개인정보는 입력하지 마세요.",
        )
        approve_col, reject_col = st.columns(2)
        approve_clicked = approve_col.button(
            "기업 승인",
            type="primary",
            width="stretch",
            key="_kma_company_approve",
        )
        reject_clicked = reject_col.button(
            "승인 거절",
            width="stretch",
            key="_kma_company_reject",
        )
        decision = "approved" if approve_clicked else "rejected" if reject_clicked else ""
        if decision:
            try:
                review_config = DemoStoreConfig.from_sources(
                    secrets=demo_store_secrets
                )
                if not review_config.company_access_granted(management_code):
                    raise DemoStoreError("KMA 승인관리 코드가 일치하지 않습니다.")
                if decision == "rejected" and not reviewer_note.strip():
                    raise DemoStoreError("승인을 거절하려면 검토 메모에 사유를 입력해 주세요.")
                review_store = GitHubDemoStore(
                    review_config,
                    company_registration_code=management_code,
                )
                review_store.review_company_registration(
                    selected_company_id,
                    decision,
                    reviewer_note=reviewer_note,
                )
                _read_github_demo_snapshot.clear()
                st.session_state["_kma_company_review_flash"] = (
                    "기업 신청을 승인했습니다."
                    if decision == "approved"
                    else "기업 신청을 거절했습니다."
                )
                st.rerun()
            except DemoStoreError as exc:
                st.error(str(exc))

review_flash = st.session_state.pop("_kma_company_review_flash", "")
if review_flash:
    st.success(review_flash)

left, right = st.columns([1.15, 1], gap="large")
with left:
    with st.container(border=True):
        st.markdown('<h3 class="tap-card-title">진단도구 발행 상태</h3>', unsafe_allow_html=True)
        st.markdown(
            '<p class="tap-card-sub">발행본은 고정하고 변경 시 새 버전을 생성합니다.</p>',
            unsafe_allow_html=True,
        )
        active_questions = integrity["question_count"] - 20
        rows = [
            ("운영 문항은행", f"활성 {active_questions} / 원본 {integrity['question_count']}문항", 0, "전문가 검토 전"),
            ("역량체계", f"운영 31 / 원본 {integrity['competency_count']}개", 0, "인지면접 전"),
            ("직급 문항", "비활성 20문항 · 배정조건으로 전환", 100, "운영정책 반영"),
        ]
        for name, description, progress, stage in rows:
            st.markdown(f"**{name}** · {stage}")
            st.caption(description)
            st.progress(progress / 100, text=f"{progress}%")

with right:
    with st.container(border=True):
        st.markdown('<h3 class="tap-card-title">교육과정 매핑 품질</h3>', unsafe_allow_html=True)
        st.markdown(
            '<p class="tap-card-sub">과정명 키워드가 아니라 학습목표와 행동지표를 검수합니다.</p>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        c1.metric("활성 과정", f"{sum(row['active'] for row in load_courses())}개")
        c2.metric("역량–과정 매핑", f"{len(load_course_map())}건")
        callout(
            "매핑 완료 · 46개 과정",
            "주역량, 행동지표, 학습목표, 대상, 난이도, 방식, 감수 버전을 등록한 예시입니다.",
        )
        callout(
            "검수 필요 · 12개 과정",
            "추천 이유가 없거나 학습목표와 행동지표의 연결 근거가 부족한 예시입니다.",
            icon="!",
            tone="danger",
        )
        st.caption("적합 과정이 없으면 억지로 추천하지 않고 ‘현재 매핑된 과정 없음’으로 표시합니다.")

st.markdown("### 기획검증 프로젝트 누적 현황" if dashboard_source == "store" else "### 회원사 운영 현황")
st.caption(
    "완료 제출의 프로젝트별 참여·전후 완료 상태만 표시하며 가명키·문항응답·개인점수는 열람하지 않습니다."
    if dashboard_source == "store"
    else "KMA 관리자는 프로젝트 진행 상태만 확인하며 회원사의 조직점수·격차·개인결과는 열람하지 않습니다."
)
organizations = pd.DataFrame(
    format_kma_organization_rows(
        dashboard["organizations"], persistent=dashboard_source == "store"
    )
)
st.dataframe(organizations, hide_index=True, width="stretch")

event_col, boundary_col = st.columns([1.35, 1], gap="large")
with event_col:
    with st.container(border=True):
        event_title = "최근 집계 갱신" if dashboard_source == "store" else "운영 이벤트 목업"
        st.markdown(f'<h3 class="tap-card-title">{event_title}</h3>', unsafe_allow_html=True)
        st.markdown(
            (
                '<p class="tap-card-sub">프로젝트별 현재 완료 집계를 마지막 갱신 시각 기준으로 표시합니다. 감사 이벤트 이력이 아닙니다.</p>'
                if dashboard_source == "store"
                else '<p class="tap-card-sub">향후 감사로그 화면 구성을 검토하기 위한 예시이며 실제 운영 이력이 아닙니다.</p>'
            ),
            unsafe_allow_html=True,
        )
        if dashboard_source == "store":
            events = pd.DataFrame(dashboard["snapshot_rows"]).rename(
                columns={
                    "updated_at": "갱신 시각",
                    "snapshot": "구분",
                    "project": "프로젝트",
                    "counts": "현재 완료 수",
                }
            )
        else:
            events = pd.DataFrame(dashboard["audit_events"]).rename(
                columns={"time": "시각", "event": "예시 이벤트", "target": "대상", "result": "결과"}
            )
        st.dataframe(events, hide_index=True, width="stretch")

with boundary_col:
    with st.container(border=True):
        st.markdown('<h3 class="tap-card-title">운영 권한 경계</h3>', unsafe_allow_html=True)
        st.markdown(
            '<p class="tap-card-sub">KMA 운영 화면은 데이터 최소권한을 기본값으로 둡니다.</p>',
            unsafe_allow_html=True,
        )
        callout(
            "확인 가능",
            (
                "프로젝트별 현재 완료 집계와 갱신 시각, 진단도구 버전, 과정 매핑"
                if dashboard_source == "store"
                else "회원사·프로젝트 상태, 진단도구 버전, 과정 매핑, 감사로그 화면 목업"
            ),
        )
        callout(
            "기본 미열람",
            "회원사 조직점수, 개인점수, 문항별 응답, 참여자 실명·연락처",
            icon="×",
            tone="danger",
        )
        if st.button("전체 문항은행 검수", type="primary", width="stretch"):
            st.switch_page("pages/5_question_bank.py")
