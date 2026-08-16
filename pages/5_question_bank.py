from __future__ import annotations

import pandas as pd
import streamlit as st

from tap.runtime_guard import stop_on_stale


stop_on_stale(st, ("tap.ui",))

from tap.data import load_pilot_item_candidates, load_questions
from tap.ui import callout, page_header, setup_page


setup_page("문항은행·검수", "5")
questions = pd.DataFrame(load_questions())
pilot_candidates = pd.DataFrame(load_pilot_item_candidates())

page_header(
    "문항은행 검수",
    "전체 문항은행 및 예비 유효성 검수",
    "원본 144문항의 수정·유지·삭제 근거와 운영 여부를 추적합니다.",
    badge="KMA 관리자 검수",
    badge_tone="amber",
)
callout(
    "학문적 타당화 전 단계",
    "현재 값은 작성자의 설계 체크리스트 충족수입니다. 타당도 계수나 전문가 인증이 아니며 인지면접·파일럿·문항분석·요인구조 검토가 남아 있습니다.",
    icon="β",
    tone="warn",
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("전체", len(questions))
c2.metric("운영 문항", int(questions["active"].sum()))
c3.metric("수정 문항", int((questions["original_decision"] == "수정").sum()))
c4.metric("인지면접 완료", f"0/{int(questions['active'].sum())}")

groups = ["전체"] + sorted(questions["module_group"].unique().tolist())
selected_group = st.radio("모듈군", groups, horizontal=True)
decision_options = sorted(questions["original_decision"].unique())
st.markdown("**원문 판정 필터**")
decision_columns = st.columns(len(decision_options))
decisions: list[str] = []
for index, decision in enumerate(decision_options):
    with decision_columns[index]:
        if st.checkbox(decision, value=True, key=f"question_filter_{decision}"):
            decisions.append(decision)
show_original = st.checkbox("원문과 상세 판정 사유 표시", value=False)

filtered = questions[questions["original_decision"].isin(decisions)]
if selected_group != "전체":
    filtered = filtered[filtered["module_group"] == selected_group]

base_cols = [
    "question_code",
    "module_group",
    "factor_name_ko",
    "revised_text",
    "validity_score",
    "empirical_status",
    "original_decision",
    "active",
]
if show_original:
    base_cols += ["original_text", "issue_codes", "rationale", "source_file"]
display = filtered[base_cols].rename(
    columns={
        "question_code": "문항코드",
        "module_group": "모듈군",
        "factor_name_ko": "역량",
        "revised_text": "운영 문구",
        "validity_score": "설계검토 충족수(10)",
        "empirical_status": "실증 검증상태",
        "original_decision": "원문 판정",
        "active": "운영 여부",
        "original_text": "원문",
        "issue_codes": "검토 이슈코드",
        "rationale": "검토 근거",
        "source_file": "출처 파일",
    }
)
st.dataframe(display, hide_index=True, width="stretch", height=620)

st.download_button(
    "필터 결과 CSV",
    filtered.to_csv(index=False).encode("utf-8-sig"),
    "tap_question_bank_review.csv",
    "text/csv",
)

st.markdown("### 누락 역량 파일럿 후보")
st.caption(
    "업무 소통, 책임 있는 판단, 디지털 안전·정보판별, 성과관리와 책임의 16문항 초안입니다. "
    "직무분석·전문가 검토·인지면접 전에는 점수 산출과 프로젝트 선택에 사용하지 않습니다."
)
candidate_view = pilot_candidates.rename(
    columns={
        "factor_name_ko": "후보 역량",
        "target_levels": "대상",
        "question_code": "후보 문항코드",
        "revised_text": "후보 문구",
        "review_status": "검토상태",
        "rationale": "추가 근거",
    }
)[["후보 역량", "대상", "후보 문항코드", "후보 문구", "검토상태", "추가 근거"]]
st.dataframe(candidate_view, hide_index=True, width="stretch", height=480)
st.download_button(
    "파일럿 후보 CSV",
    pilot_candidates.to_csv(index=False).encode("utf-8-sig"),
    "tap_pilot_item_candidates.csv",
    "text/csv",
)
