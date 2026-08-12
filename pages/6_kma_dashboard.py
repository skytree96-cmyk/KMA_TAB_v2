from __future__ import annotations

import pandas as pd
import streamlit as st

from tap.dashboard import load_dashboard_demo
from tap.data import integrity_report, load_course_map, load_courses
from tap.ui import callout, metric_grid, page_header, setup_page


setup_page("KMA 대시보드", "T")
dashboard = load_dashboard_demo()["kma"]
integrity = integrity_report()

page_header(
    "KMA 운영 화면",
    "회원사 진단 운영 현황",
    "회원사 권한, 진단 버전, 교육과정 매핑과 데이터 접근 이력을 관리합니다.",
    badge="KMA 관리자 화면",
    badge_tone="amber",
)

callout(
    "운영 목업 데이터",
    "회원사·프로젝트·응답 수치는 관리자 화면 검토용 예시입니다. 문항은행 수치는 현재 배포 데이터에서 계산합니다.",
    icon="β",
    tone="warn",
)
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

st.markdown("### 회원사 운영 현황")
st.caption("KMA 관리자는 프로젝트 진행 상태만 확인하며 회원사의 조직점수·격차·개인결과는 열람하지 않습니다.")
organizations = pd.DataFrame(dashboard["organizations"]).rename(
    columns={
        "name": "회원사",
        "projects": "프로젝트",
        "invited": "초대 인원",
        "completion_pct": "완료율(%)",
        "activity": "최근 활동",
    }
)
st.dataframe(organizations, hide_index=True, width="stretch")

event_col, boundary_col = st.columns([1.35, 1], gap="large")
with event_col:
    with st.container(border=True):
        st.markdown('<h3 class="tap-card-title">최근 운영 이벤트</h3>', unsafe_allow_html=True)
        st.markdown(
            '<p class="tap-card-sub">권한 변경, 다운로드, 발행과 차단 상태를 기록합니다.</p>',
            unsafe_allow_html=True,
        )
        events = pd.DataFrame(dashboard["audit_events"]).rename(
            columns={"time": "시각", "event": "이벤트", "target": "대상", "result": "결과"}
        )
        st.dataframe(events, hide_index=True, width="stretch")

with boundary_col:
    with st.container(border=True):
        st.markdown('<h3 class="tap-card-title">운영 권한 경계</h3>', unsafe_allow_html=True)
        st.markdown(
            '<p class="tap-card-sub">KMA 운영 화면은 데이터 최소권한을 기본값으로 둡니다.</p>',
            unsafe_allow_html=True,
        )
        callout("확인 가능", "회원사·프로젝트 상태, 진단도구 버전, 과정 매핑, 감사로그")
        callout(
            "기본 미열람",
            "회원사 조직점수, 개인점수, 문항별 응답, 참여자 실명·연락처",
            icon="×",
            tone="danger",
        )
        if st.button("전체 문항은행 검수", type="primary", width="stretch"):
            st.switch_page("pages/5_question_bank.py")
