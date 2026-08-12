from __future__ import annotations

import csv
import io
import json
from html import escape

import pandas as pd
import streamlit as st

from tap.data import load_course_map, load_courses, questions_for_factors
from tap.recommendation import rank_courses
from tap.scoring import response_quality_flags, score_responses
from tap.state import ensure_state
from tap.ui import callout, page_header, setup_page


setup_page("개인 리포트", "3")
ensure_state(st.session_state)

if not st.session_state.responses:
    st.warning("아직 저장된 응답이 없습니다.")
    if st.button("진단 참여로 이동", type="primary"):
        st.switch_page("pages/2_assessment.py")
    st.stop()

questions = questions_for_factors(st.session_state.selected_factors)
results = score_responses(questions, st.session_state.responses, st.session_state.target_means)
valid_results = [r for r in results if r["status"] == "산출"]

page_header(
    "개인 리포트",
    "나의 역량진단 결과",
    "측정한 역량의 행동빈도와 개발 우선영역을 확인합니다.",
    badge="본인만 기본 열람",
)

valid_sorted = sorted(
    valid_results,
    key=lambda row: float(row["score_1_to_5"]) if row["score_1_to_5"] is not None else -1,
)
development_name = valid_sorted[0]["factor_name_ko"] if valid_sorted else "유효응답 확인"
st.markdown(
    f"""
    <section class="tap-report-hero">
      <div>
        <span class="tap-chip teal">최근 8주 자기보고 결과</span>
        <h2>{escape(str(development_name))}은 개발 맥락을 먼저 살펴볼 후보입니다.</h2>
        <p>외부 규준·백분위가 아닌 1~5점 행동빈도 평균입니다. 작은 점수 차이는 측정오차일 수 있으므로 역량 순위로 확정하지 않습니다.</p>
      </div>
      <div class="tap-score-callout">
        <small>측정한 역량</small>
        <b>{len(valid_results)}개</b>
        <small>유효응답 {sum(r['valid_items'] for r in results)}문항</small>
      </div>
    </section>
    """,
    unsafe_allow_html=True,
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("산출 역량", f"{len(valid_results)}/{len(results)}")
c2.metric("유효 응답", sum(r["valid_items"] for r in results))
c3.metric("수행기회 없음", sum(r["na_items"] for r in results))
c4.metric("미응답", sum(r["missing_items"] for r in results))

display_cols = [
    "factor_name_ko", "score_1_to_5", "index_100", "frequency_level",
    "target_mean", "gap_to_target", "valid_items", "status",
]
df = pd.DataFrame(results)[display_cols].rename(
    columns={
        "factor_name_ko": "역량",
        "score_1_to_5": "평균(1~5)",
        "index_100": "환산지수(0~100)",
        "frequency_level": "임시 기술구간",
        "target_mean": "목표수준",
        "gap_to_target": "목표격차",
        "valid_items": "유효문항",
        "status": "산출상태",
    }
)
st.dataframe(df, hide_index=True, width="stretch")

chart_rows = pd.DataFrame(valid_results)
if not chart_rows.empty:
    st.bar_chart(chart_rows.set_index("factor_name_ko")["index_100"], y_label="0~100 선형 환산지수")
    st.caption("0~100 값은 (평균−1)×25로 바꾼 표시용 지수이며 백분율·백분위·숙련도 점수가 아닙니다.")

flags = response_quality_flags(st.session_state.responses, st.session_state.get("duration_seconds"))
if flags:
    st.warning("응답 품질 확인 신호: " + ", ".join(flags) + ". 자동 무효처리하지 않으며 담당자가 맥락을 확인해야 합니다.")

callout(
    "해석 범위",
    "이 결과는 교육개발을 위한 자기보고 행동빈도이며 규준 비교·개인 순위·채용·승진 판단에 사용할 수 없습니다.",
    icon="i",
)

st.subheader("교육과정 검토 우선순위")
st.caption("검토점수는 대화를 돕는 운영 휴리스틱이며 정밀한 측정점수나 교육효과 예측치가 아닙니다.")
if st.session_state.training_cause == "system_only":
    st.info("주된 원인이 권한·도구·프로세스 등 시스템 요인으로 판정되어 교육 추천을 중단했습니다. 업무환경 개선을 먼저 검토하세요.")
else:
    ranked = rank_courses(
        results,
        load_courses(),
        load_course_map(),
        organization_priorities=set(st.session_state.organization_priorities),
        learner_interests=set(st.session_state.learner_interests),
        target_level=st.session_state.target_level,
        delivery_preference=st.session_state.delivery_preference,
        training_cause=st.session_state.training_cause,
    )
    if not ranked:
        st.success("현재 설정한 목표수준 기준으로 우선 추천할 과정이 없습니다.")
    else:
        for row in ranked:
            with st.container(border=True):
                st.markdown(f"**{row['title']}** · 검토점수 {row['recommendation_score']}점")
                st.caption(
                    f"연계역량: {row['factor_name_ko']} · {row['mapping_rationale']} · "
                    f"격차 {row['gap_points']} / 내용적합 {row['content_points']} / 조직우선 {row['priority_points']} / "
                    f"학습희망 {row['interest_points']} / 대상·방식 {row['context_points']}"
                )
                if row.get("url"):
                    st.link_button("과정 확인", row["url"])

st.subheader("개인결과 공유")
share_consent = st.checkbox(
    "조직 교육담당자에게 이 개인 결과를 공유하는 데 동의합니다.",
    value=bool(st.session_state.get("share_consent", False)),
)
st.session_state.share_consent = share_consent
st.caption("동의하지 않아도 조직의 익명 집계에는 포함될 수 있으며, N<5 집계는 공개되지 않습니다.")

json_bytes = json.dumps(results, ensure_ascii=False, indent=2).encode("utf-8")
csv_buffer = io.StringIO()
writer = csv.DictWriter(csv_buffer, fieldnames=list(results[0].keys()))
writer.writeheader()
writer.writerows(results)
d1, d2 = st.columns(2)
d1.download_button("결과 JSON", json_bytes, "tap_individual_result.json", "application/json", width="stretch")
d2.download_button("결과 CSV", csv_buffer.getvalue().encode("utf-8-sig"), "tap_individual_result.csv", "text/csv", width="stretch")
