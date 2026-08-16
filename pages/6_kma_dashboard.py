from __future__ import annotations

import pandas as pd
import streamlit as st

from tap.runtime_guard import stop_on_stale


stop_on_stale(st, ("tap.dashboard", "tap.github_demo_store", "tap.ui"))

from tap.dashboard import (
    build_kma_persistent_dashboard,
    fetch_store_snapshot,
    load_dashboard_demo,
)
from tap.data import integrity_report, load_course_map, load_courses
from tap.github_demo_store import DemoStoreConfig, DemoStoreError, GitHubDemoStore
from tap.ui import callout, metric_grid, page_header, setup_page


setup_page("KMA 대시보드", "T")


@st.cache_data(ttl=30, show_spinner=False)
def _read_github_demo_snapshot(_secrets: object) -> dict[str, object]:
    config = DemoStoreConfig.from_sources(secrets=_secrets)
    store = GitHubDemoStore(config)
    status = store.status()
    if not status["read_enabled"]:
        return {"status": status, "projects": [], "submissions": []}
    return {"status": status, **fetch_store_snapshot(store)}


dashboard = load_dashboard_demo()["kma"]
dashboard_source = "sample"
store_error = ""
try:
    demo_store_secrets: object = dict(st.secrets)
except Exception:  # No secrets file is the normal local-development state.
    demo_store_secrets = {}
try:
    stored = _read_github_demo_snapshot(demo_store_secrets)
    store_status = dict(stored["status"])
    if store_status.get("read_enabled"):
        persistent_dashboard = build_kma_persistent_dashboard(
            stored["submissions"], stored["projects"]
        )
        if persistent_dashboard["has_data"]:
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

if dashboard_source == "store":
    refresh_col, source_col = st.columns([1, 3])
    with refresh_col:
        if st.button("누적 데이터 새로고침", width="stretch"):
            _read_github_demo_snapshot.clear()
            st.rerun()
    with source_col:
        callout(
            "기획검증 누적 실데이터",
            "프로젝트·참여자·교육 전후 완료 수치는 GitHub 데모 저장소의 실제 완료 제출을 집계했습니다. 원문 참여자 ID와 개인점수는 표시하지 않습니다.",
            icon="ⓘ",
        )
else:
    reason = (
        f"누적 저장소 조회 오류({store_error})로 목업을 표시합니다."
        if store_error
        else "누적 완료 제출이 없거나 GitHub 데모 저장소가 설정되지 않아 목업을 표시합니다."
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
    "완료 제출의 프로젝트별 참여·짝지음 상태만 표시하며 가명키·문항응답·개인점수는 열람하지 않습니다."
    if dashboard_source == "store"
    else "KMA 관리자는 프로젝트 진행 상태만 확인하며 회원사의 조직점수·격차·개인결과는 열람하지 않습니다."
)
organizations = pd.DataFrame(dashboard["organizations"]).rename(
    columns={
        "name": "프로젝트" if dashboard_source == "store" else "회원사",
        "projects": "프로젝트",
        "invited": "검사 참여자" if dashboard_source == "store" else "초대 인원",
        "completion_pct": (
            "사전·사후 짝지음률(%)" if dashboard_source == "store" else "완료율(%)"
        ),
        "activity": "최근 집계 갱신" if dashboard_source == "store" else "최근 활동",
    }
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
