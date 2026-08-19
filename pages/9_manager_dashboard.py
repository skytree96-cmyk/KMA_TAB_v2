from __future__ import annotations

import streamlit as st

from tap.runtime_guard import stop_on_stale


stop_on_stale(st, ("tap.dashboard", "tap.github_demo_store", "tap.ui"))

from tap.dashboard import (
    build_persistent_dashboard,
    build_session_dashboard,
    fetch_store_snapshot,
)
from tap.github_demo_store import DemoStoreConfig, DemoStoreError, GitHubDemoStore
from tap.state import ensure_state
from tap.ui import (
    callout,
    dashboard_hero,
    metric_grid,
    page_header,
    project_rows,
    safe_switch_page,
    setup_page,
)


setup_page("관리자 대시보드", "T")
ensure_state(st.session_state)


@st.cache_data(ttl=30, show_spinner=False)
def _read_github_demo_snapshot(_secrets: object) -> dict[str, object]:
    config = DemoStoreConfig.from_sources(secrets=_secrets)
    store = GitHubDemoStore(config)
    status = store.status()
    if not status["read_enabled"]:
        return {"status": status, "projects": [], "submissions": []}
    return {"status": status, **fetch_store_snapshot(store)}


session_dashboard = build_session_dashboard(st.session_state)
dashboard = session_dashboard
dashboard_source = "session"
store_error = ""
try:
    demo_store_secrets: object = dict(st.secrets)
except Exception:  # No secrets file is the normal local-development state.
    demo_store_secrets = {}
try:
    stored = _read_github_demo_snapshot(demo_store_secrets)
    store_status = dict(stored["status"])
    if store_status.get("read_enabled"):
        dashboard = build_persistent_dashboard(
            stored["submissions"], stored["projects"]
        )
        dashboard_source = "store"
except DemoStoreError as exc:
    store_status = {}
    store_error = str(exc)

page_header(
    "KMA 교육효과 평가",
    "교육 전후의 변화를 다음 개선으로",
    "교육담당자가 사전·사후 검사를 운영하고, 동일 참여자의 전후 변화와 현업 적용환경을 다음 교육 설계로 연결합니다.",
    badge="교육담당자 화면",
)

dashboard_hero()

actions = st.columns(3)
with actions[0]:
    if st.button("교육평가 프로젝트 만들기", type="primary", width="stretch"):
        safe_switch_page("pages/1_project_setup.py")
with actions[1]:
    if st.button("교육 전후 리포트 보기", width="stretch"):
        safe_switch_page("pages/4_organization_report.py")
with actions[2]:
    if st.button("처음 사용 안내", width="stretch"):
        safe_switch_page("pages/0_user_guide.py")
if dashboard_source == "store":
    refresh_col, source_col = st.columns([1, 3])
    with refresh_col:
        if st.button("누적 데이터 새로고침", width="stretch"):
            _read_github_demo_snapshot.clear()
            st.rerun()
    with source_col:
        st.info(
            "GitHub 기획검증 저장소에 저장된 완료 제출을 30초 단위로 누적 집계합니다. "
            "참여자 수는 원문 ID가 아닌 프로젝트별 가명키를 기준으로 계산합니다."
        )
elif store_error:
    st.warning(
        f"누적 저장소를 읽지 못해 현재 브라우저 세션으로 대체했습니다: {store_error}"
    )
    if st.button("누적 데이터 다시 읽기"):
        _read_github_demo_snapshot.clear()
        st.rerun()
else:
    st.info(
        "GitHub 기획검증 저장소가 설정되지 않아 이 브라우저 세션의 실제 프로젝트와 검사 상태를 보여줍니다. "
        "저장소를 설정하면 다른 테스트 브라우저의 완료 제출도 누적됩니다."
    )

metric_grid(dashboard["metrics"])

left, right = st.columns([1.35, 1], gap="large")
with left:
    with st.container(border=True):
        project_title = "누적 프로젝트" if dashboard_source == "store" else "현재 세션 프로젝트"
        project_subtitle = (
            "저장소에 누적된 프로젝트별 교육 전·후 완료 제출 현황입니다."
            if dashboard_source == "store"
            else "현재 브라우저에서 만든 프로젝트와 한 참여자의 교육 전·후 완료 상태입니다."
        )
        st.markdown(f'<h3 class="tap-card-title">{project_title}</h3>', unsafe_allow_html=True)
        st.markdown(f'<p class="tap-card-sub">{project_subtitle}</p>', unsafe_allow_html=True)
        if dashboard["projects"]:
            project_rows(dashboard["projects"])
            participant_scope = "누적 참여자" if dashboard_source == "store" else "현재 세션 참여자"
            st.caption(
                f"검사 단계 진행률 {dashboard['phase_completion_pct']:.0f}% · "
                f"교육 전·후 모두 완료한 {participant_scope} {dashboard['paired_count']}명"
            )
        else:
            empty_scope = "누적 저장소" if dashboard_source == "store" else "현재 세션"
            st.info(f"{empty_scope}에 완료 제출이 없습니다. 먼저 교육평가 검사를 완료해 주세요.")

with right:
    with st.container(border=True):
        st.markdown('<h3 class="tap-card-title">확인할 운영 원칙</h3>', unsafe_allow_html=True)
        st.markdown(
            '<p class="tap-card-sub">교육개발 목적에 맞는 사용만 허용합니다.</p>',
            unsafe_allow_html=True,
        )
        callout(
            "HR은 조직 집계가 기본",
            "개인결과는 참여자가 별도로 동의한 범위만 열람하며, 조직 변화는 동일 참여자의 유효한 사전·사후 결과만 집계합니다.",
        )
        callout(
            "채용·승진·성과평가에 사용 금지",
            "TAP은 자기보고형 교육 요구진단이며 인사평가 도구가 아닙니다.",
            icon="!",
            tone="warn",
        )
        callout(
            "표본 보호",
            "유효응답자 5명 미만의 부서·직급 점수는 표시하지 않습니다.",
            icon="5+",
        )
        callout(
            "변화와 인과효과는 다릅니다",
            "비교집단이 없는 사전·사후 자기보고 결과는 교육 전후 관찰된 변화로 표현합니다.",
            icon="i",
        )

st.markdown("### 다음 운영 작업")
next_a, next_b, next_c = st.columns(3)
with next_a:
    with st.container(border=True):
        st.markdown("**① 교육·평가 일정 구성**")
        st.caption("교육명과 교육일, 사전검사·사후검사 기간, 공통 측정역량을 함께 정합니다.")
        if st.button("프로젝트 설정", key="home_project", width="stretch"):
            safe_switch_page("pages/1_project_setup.py")
with next_b:
    with st.container(border=True):
        st.markdown("**② 사전·사후 화면 확인**")
        st.caption("두 시점 모두 같은 문항·척도와 최근 8주 회상기간을 사용하고, 동일 교육 참여자 ID로 전·후 결과를 연결합니다.")
        if st.button("실제 검사 시작", key="home_assessment", width="stretch"):
            safe_switch_page("pages/7_pre_assessment.py")
with next_c:
    with st.container(border=True):
        st.markdown("**③ 관찰된 변화 확인**")
        st.caption("N≥5 동일 참여자 전·후 집계, 역량별 전후 변화, 수행기회와 전이 장애요인을 함께 검토합니다.")
        if st.button("교육 전후 리포트", key="home_org", width="stretch"):
            safe_switch_page("pages/4_organization_report.py")
