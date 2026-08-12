from __future__ import annotations

import streamlit as st

from tap.dashboard import completion_rate, load_dashboard_demo
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
dashboard = load_dashboard_demo()["company"]

page_header(
    "KMA 회원사 지원",
    "진단 결과를 교육의 다음 행동으로",
    "회원사 교육담당자가 프로젝트를 운영하고 KMA 교육과 stud.io로 연결합니다.",
    badge="교육담당자 화면",
)

dashboard_hero()

actions = st.columns(3)
with actions[0]:
    if st.button("새 프로젝트 만들기", type="primary", width="stretch"):
        safe_switch_page("pages/1_project_setup.py")
with actions[1]:
    if st.button("조직 리포트 보기", width="stretch"):
        safe_switch_page("pages/4_organization_report.py")
with actions[2]:
    if st.button("처음 사용 안내", width="stretch"):
        safe_switch_page("pages/0_user_guide.py")
st.caption("아래 운영 수치는 화면 검토를 위한 목업 데이터이며 실제 회원사 실적이 아닙니다.")

metric_grid(dashboard["metrics"])

left, right = st.columns([1.35, 1], gap="large")
with left:
    with st.container(border=True):
        st.markdown('<h3 class="tap-card-title">진행 프로젝트</h3>', unsafe_allow_html=True)
        st.markdown(
            '<p class="tap-card-sub">참여율과 마감 상태를 확인하고 리마인드를 운영합니다.</p>',
            unsafe_allow_html=True,
        )
        project_rows(dashboard["projects"])
        st.caption(
            f"전체 초대 기준 가중 완료율 {completion_rate(dashboard['projects']):.1f}% · "
            "실제 운영에서는 프로젝트·참여자 DB에서 계산합니다."
        )

with right:
    with st.container(border=True):
        st.markdown('<h3 class="tap-card-title">확인할 운영 원칙</h3>', unsafe_allow_html=True)
        st.markdown(
            '<p class="tap-card-sub">교육개발 목적에 맞는 사용만 허용합니다.</p>',
            unsafe_allow_html=True,
        )
        callout(
            "HR은 조직 집계가 기본",
            "개인결과는 참여자가 별도로 동의한 범위만 열람합니다.",
        )
        callout(
            "채용·승진·성과평가에 사용 금지",
            "TAP은 자기보고형 교육 요구진단이며 인사평가 도구가 아닙니다.",
            icon="!",
            tone="warn",
        )
        callout(
            "소수집단 결과 보호",
            "유효응답자 5명 미만의 부서·직급 점수는 표시하지 않습니다.",
            icon="5+",
        )

st.markdown("### 다음 운영 작업")
next_a, next_b, next_c = st.columns(3)
with next_a:
    with st.container(border=True):
        st.markdown("**① 진단 프로젝트 구성**")
        st.caption("대상 수준을 정하고 공통역량과 선택역량을 체크박스로 구성합니다.")
        if st.button("프로젝트 설정", key="home_project", width="stretch"):
            safe_switch_page("pages/1_project_setup.py")
with next_b:
    with st.container(border=True):
        st.markdown("**② 참여자 화면 확인**")
        st.caption("최근 8주 행동빈도 응답, 자동저장, 수행 기회 없음 처리를 확인합니다.")
        if st.button("참여자 미리보기", key="home_assessment", width="stretch"):
            safe_switch_page("pages/2_assessment.py")
with next_c:
    with st.container(border=True):
        st.markdown("**③ 조직 교육수요 확인**")
        st.caption("N≥5 집계, 목표격차, 교육 외 원인과 과정추천을 함께 검토합니다.")
        if st.button("조직 리포트", key="home_org", width="stretch"):
            safe_switch_page("pages/4_organization_report.py")
