from __future__ import annotations

import hashlib
from html import escape
from time import time

import streamlit as st

from tap.config import LIKERT_OPTIONS
from tap.data import questions_for_factors
from tap.state import ensure_state, reset_assessment
from tap.ui import callout, page_header, setup_page


setup_page("진단 참여", "2")
ensure_state(st.session_state)

if not st.session_state.selected_factors:
    st.warning("먼저 프로젝트 모듈을 설정해 주세요.")
    if st.button("프로젝트 설정으로 이동", type="primary"):
        st.switch_page("pages/1_project_setup.py")
    st.stop()

questions = questions_for_factors(st.session_state.selected_factors)
order_seed = str(st.session_state.get("project_name", "TAP"))
questions = sorted(
    questions,
    key=lambda row: hashlib.sha256(
        f"{order_seed}|{row['question_code']}".encode("utf-8")
    ).hexdigest(),
)
idx = min(st.session_state.current_question, len(questions) - 1)
question = questions[idx]
responses: dict[str, int] = st.session_state.responses
answered = len(responses)

page_header(
    "진단 참여",
    st.session_state.get("project_name", "역량진단"),
    "최근 8주 동안 실제 업무에서 나타난 행동을 기준으로 응답해 주세요.",
    badge="세션 임시저장",
)
callout(
    "교육개발 목적의 자기보고형 진단",
    "채용·승진·보상·성과평가의 단독 판단자료로 사용하지 않습니다. 이 공개 데모의 응답은 현재 브라우저 세션에만 임시 저장됩니다.",
    icon="i",
)
st.progress(answered / len(questions), text=f"{answered}/{len(questions)} 응답 · 현재 {idx + 1}번")

st.markdown(
    f"""
    <div class="tap-question-card">
      <div class="tap-question-meta">
        <span>업무행동 문항 {idx + 1}</span>
        <span>최근 8주</span>
      </div>
      <h2>{escape(question['revised_text'])}</h2>
    </div>
    """,
    unsafe_allow_html=True,
)

options = list(LIKERT_OPTIONS)
current_value = responses.get(question["question_code"])
with st.form(f"question_form_{question['question_code']}"):
    choice = st.radio(
        "응답",
        options=options,
        index=options.index(current_value) if current_value in options else None,
        format_func=lambda value: f"{value}. {LIKERT_OPTIONS[value]}" if value else LIKERT_OPTIONS[value],
        horizontal=True,
    )
    submitted = st.form_submit_button(
        "결과 보기" if idx == len(questions) - 1 else "저장하고 다음",
        type="primary",
        width="stretch",
    )

if submitted:
    if choice is None:
        st.error("응답을 선택해 주세요. 수행 기회가 없었다면 해당 항목을 선택할 수 있습니다.")
    else:
        responses[question["question_code"]] = int(choice)
        st.session_state.responses = responses
        if idx == len(questions) - 1:
            st.session_state.assessment_completed = True
            started = st.session_state.assessment_started_at or time()
            st.session_state.duration_seconds = max(0, time() - started)
            st.switch_page("pages/3_individual_report.py")
        else:
            st.session_state.current_question = idx + 1
            st.rerun()

left, right = st.columns(2)
with left:
    if st.button("이전 문항", disabled=idx == 0, width="stretch"):
        st.session_state.current_question = idx - 1
        st.rerun()
with right:
    with st.popover("진단 초기화", width="stretch"):
        st.write("현재 세션의 응답을 모두 지웁니다.")
        if st.button("초기화 확인", type="secondary"):
            reset_assessment(st.session_state)
            st.rerun()
