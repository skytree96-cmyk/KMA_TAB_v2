from __future__ import annotations

import csv
import io
import json
from html import escape
from statistics import mean

import pandas as pd
import streamlit as st

from tap.data import load_course_map, load_courses, questions_for_factors
from tap.recommendation import rank_courses
from tap.scoring import response_quality_flags, score_pre_post_responses, score_responses
from tap.state import ensure_state
from tap.ui import callout, page_header, setup_page


setup_page("개인 리포트", "3")
ensure_state(st.session_state)

questions = questions_for_factors(st.session_state.selected_factors)
phase_store = dict(st.session_state.get("responses_by_phase") or {})
pre_responses = dict(phase_store.get("pre") or st.session_state.get("pre_responses") or {})
post_responses = dict(phase_store.get("post") or st.session_state.get("post_responses") or {})
legacy_responses = dict(st.session_state.get("responses") or {})
session_type = str(
    st.session_state.get("assessment_phase", st.session_state.get("session_type", "single"))
).lower()

completed_by_phase = dict(st.session_state.get("assessment_completed_by_phase") or {})
pre_complete = bool(completed_by_phase.get("pre", False))
post_complete = bool(completed_by_phase.get("post", False))

if not (pre_responses or post_responses or legacy_responses):
    st.warning("아직 저장된 응답이 없습니다.")
    if st.button("사전·사후 검사로 이동", type="primary"):
        st.switch_page("pages/2_assessment.py")
    st.stop()

has_pre_post = bool(pre_responses and post_responses and pre_complete and post_complete)
if pre_responses and post_responses and not has_pre_post:
    st.warning("사전·사후 검사가 모두 완료되어야 변화 리포트를 확정할 수 있습니다.")
    c_pre, c_post = st.columns(2)
    c_pre.metric("교육 전", "완료" if pre_complete else "진행 중")
    c_post.metric("교육 후", "완료" if post_complete else "진행 중")
    if st.button("검사로 돌아가기", type="primary"):
        st.switch_page("pages/2_assessment.py")
    st.stop()
if post_responses:
    current_responses = post_responses
    current_phase_label = "교육 후"
elif pre_responses:
    current_responses = pre_responses
    current_phase_label = "교육 전"
else:
    current_responses = legacy_responses
    current_phase_label = {"pre": "교육 전", "post": "교육 후"}.get(session_type, "현재")

results = score_responses(questions, current_responses, st.session_state.target_means)
valid_results = [row for row in results if row["status"] == "산출"]

page_header(
    "개인 리포트",
    "나의 교육 전·후 역량평가" if has_pre_post else "나의 역량진단 결과",
    (
        "같은 문항에서 교육 전과 교육 후의 자기보고 행동빈도 변화를 확인합니다."
        if has_pre_post
        else "측정한 역량의 행동빈도와 개발 우선영역을 확인합니다."
    ),
    badge="본인만 기본 열람",
)

if has_pre_post:
    pre_results = score_responses(questions, pre_responses, st.session_state.target_means)
    post_results = score_responses(questions, post_responses, st.session_state.target_means)
    scored_changes = score_pre_post_responses(
        questions, pre_responses, post_responses, st.session_state.target_means
    )
    change_rows = [
        {
            **row,
            "change": row["self_reported_change"],
            "common_valid_items": row["paired_valid_items"],
            "status": "비교 가능" if row["status"] == "산출" else "공통 유효문항 부족",
        }
        for row in scored_changes
    ]
    comparable = [row for row in change_rows if row["change"] is not None]
    common_item_count = sum(int(row["paired_valid_items"]) for row in change_rows)
    pre_na_count = sum(int(row["pre_na_items"]) for row in change_rows)
    post_na_count = sum(int(row["post_na_items"]) for row in change_rows)
    average_change = mean(float(row["change"]) for row in comparable) if comparable else None
    largest = max(comparable, key=lambda row: float(row["change"])) if comparable else None
    headline = (
        f"{escape(str(largest['factor_name_ko']))}에서 가장 큰 관찰 변화 {float(largest['change']):+.2f}점이 나타났습니다."
        if largest
        else "공통 유효문항이 부족해 교육 전·후 변화를 산출하지 못했습니다."
    )
    st.markdown(
        f"""
        <section class="tap-report-hero">
          <div>
            <span class="tap-chip teal">교육 전·후 짝지어진 비교</span>
            <h2>{headline}</h2>
            <p>같은 문항에 두 시점 모두 1~5점으로 응답한 결과만 비교했습니다. 변화는 관찰값이며 교육의 인과효과를 뜻하지 않습니다.</p>
          </div>
          <div class="tap-score-callout">
            <small>비교 가능 역량</small>
            <b>{len(comparable)}/{len(change_rows)}개</b>
            <small>공통 유효응답 {common_item_count}문항</small>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("비교 가능 역량", f"{len(comparable)}/{len(change_rows)}")
    c2.metric("관찰 변화 평균", "—" if average_change is None else f"{average_change:+.2f}")
    c3.metric("교육 전 수행기회 없음", pre_na_count)
    c4.metric("교육 후 수행기회 없음", post_na_count)

    comparison_frame = pd.DataFrame(change_rows).rename(
        columns={
            "factor_name_ko": "역량",
            "pre_score": "교육 전(1~5)",
            "post_score": "교육 후(1~5)",
            "change": "관찰 변화",
            "common_valid_items": "공통 유효문항",
            "pre_na_items": "교육 전 기회없음",
            "post_na_items": "교육 후 기회없음",
            "status": "비교상태",
        }
    )
    st.subheader("역량별 교육 전·후 비교")
    st.dataframe(
        comparison_frame[
            [
                "역량",
                "교육 전(1~5)",
                "교육 후(1~5)",
                "관찰 변화",
                "공통 유효문항",
                "교육 전 기회없음",
                "교육 후 기회없음",
                "비교상태",
            ]
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "변화량은 교육 후−교육 전입니다. 한 시점이라도 수행 기회 없음 또는 미응답인 문항은 변화 계산에서 제외했습니다."
    )

    durations = dict(st.session_state.get("duration_seconds_by_phase") or {})
    pre_flags = response_quality_flags(pre_responses, durations.get("pre"))
    post_flags = response_quality_flags(post_responses, durations.get("post"))
    if pre_flags or post_flags:
        messages = []
        if pre_flags:
            messages.append("교육 전: " + ", ".join(pre_flags))
        if post_flags:
            messages.append("교육 후: " + ", ".join(post_flags))
        st.warning("응답 품질 확인 신호 · " + " / ".join(messages) + ". 자동 무효처리하지 않습니다.")

    callout(
        "해석 범위",
        "비교집단이 없는 자기보고 전후 차이에는 업무환경 변화, 검사효과, 평균회귀와 판단기준 변화가 포함될 수 있습니다.",
        icon="i",
    )

    st.subheader("교육 후 전이요인과 다음 행동")
    transfer_values = dict(
        st.session_state.get("post_transfer_responses")
        or st.session_state.get("transfer_factors")
        or {}
    )
    transfer_labels = (
        ("application_opportunity", "업무 적용기회"),
        ("supervisor_support", "상사·동료 지원"),
        ("resources_authority", "도구·권한 지원"),
    )
    transfer_columns = st.columns(3)
    for column, (key, label) in zip(transfer_columns, transfer_labels, strict=False):
        value = transfer_values.get(key)
        with column:
            with st.container(border=True):
                st.markdown(f"**{label}**")
                st.metric("사후 확인", "미수집" if value is None else f"{float(value):.1f}/5")
                st.caption("점수 변화의 맥락을 해석하기 위해 확인합니다.")
    st.markdown(
        """
        1. 변화가 작거나 감소한 행동은 실제 적용기회와 업무환경을 먼저 확인합니다.
        2. 변화가 나타난 행동은 현업 과제와 피드백으로 반복합니다.
        3. 같은 기준의 추적검사에서 변화가 유지되는지 확인합니다.
        """
    )
else:
    valid_sorted = sorted(
        valid_results,
        key=lambda row: float(row["score_1_to_5"]) if row["score_1_to_5"] is not None else -1,
    )
    development_name = valid_sorted[0]["factor_name_ko"] if valid_sorted else "유효응답 확인"
    st.markdown(
        f"""
        <section class="tap-report-hero">
          <div>
            <span class="tap-chip teal">{current_phase_label} · 최근 8주 자기보고</span>
            <h2>{escape(str(development_name))}은 개발 맥락을 먼저 살펴볼 후보입니다.</h2>
            <p>외부 규준·백분위가 아닌 1~5점 행동빈도 평균입니다. 작은 점수 차이는 측정오차일 수 있으므로 역량 순위로 확정하지 않습니다.</p>
          </div>
          <div class="tap-score-callout">
            <small>측정한 역량</small>
            <b>{len(valid_results)}개</b>
            <small>유효응답 {sum(row['valid_items'] for row in results)}문항</small>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("산출 역량", f"{len(valid_results)}/{len(results)}")
    c2.metric("유효 응답", sum(row["valid_items"] for row in results))
    c3.metric("수행기회 없음", sum(row["na_items"] for row in results))
    c4.metric("미응답", sum(row["missing_items"] for row in results))

    display_cols = [
        "factor_name_ko",
        "score_1_to_5",
        "index_100",
        "frequency_level",
        "target_mean",
        "gap_to_target",
        "valid_items",
        "status",
    ]
    result_frame = pd.DataFrame(results)[display_cols].rename(
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
    st.dataframe(result_frame, hide_index=True, width="stretch")

    chart_rows = pd.DataFrame(valid_results)
    if not chart_rows.empty:
        st.bar_chart(chart_rows.set_index("factor_name_ko")["index_100"], y_label="0~100 선형 환산지수")
        st.caption("0~100 값은 (평균−1)×25인 표시용 지수이며 백분율·백분위·숙련도 점수가 아닙니다.")

    flags = response_quality_flags(current_responses, st.session_state.get("duration_seconds"))
    if flags:
        st.warning("응답 품질 확인 신호: " + ", ".join(flags) + ". 자동 무효처리하지 않습니다.")

    callout(
        "해석 범위",
        "이 결과는 교육개발을 위한 자기보고 행동빈도이며 규준 비교·개인 순위·채용·승진 판단에 사용할 수 없습니다.",
        icon="i",
    )

if has_pre_post or post_responses or session_type == "post":
    st.subheader("교육 후 후속지원")
    st.caption("사후점수가 낮다는 이유만으로 재교육을 자동 추천하지 않습니다.")
    callout(
        "현업 전이를 먼저 확인하세요",
        "적용기회, 상사 피드백, 도구와 권한, 업무 프로세스를 확인한 뒤 보충학습이나 코칭을 결정합니다.",
        icon="i",
    )
else:
    st.subheader("교육과정 검토 우선순위")
    st.caption("검토점수는 대화를 돕는 운영 휴리스틱이며 정밀한 측정점수나 교육효과 예측치가 아닙니다.")
    if st.session_state.training_cause == "system_only":
        st.info("주된 원인이 권한·도구·프로세스 등 시스템 요인으로 판정되어 교육 추천을 중단했습니다.")
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

if has_pre_post:
    export_payload = {"pre": pre_results, "post": post_results, "comparison": change_rows}
    participant_id = str(st.session_state.get("participant_id", "DEMO-P001"))
    project_id = str(st.session_state.get("project_name", "TAP-PROJECT"))
    assessment_version = str(st.session_state.get("assessment_version", "TAP-1.0"))
    phase_dates = {
        "pre": str(st.session_state.get("pre_end_date", "")),
        "post": str(st.session_state.get("post_end_date", "")),
    }
    transfer = dict(st.session_state.get("post_transfer_responses") or {})
    csv_rows = []
    for phase_name, phase_results in (("pre", pre_results), ("post", post_results)):
        for row in phase_results:
            if row.get("score_1_to_5") is None:
                continue
            csv_rows.append(
                {
                    "participant_id": participant_id,
                    "factor_code": row["factor_code"],
                    "score_1_to_5": row["score_1_to_5"],
                    "project_id": project_id,
                    "assessment_version": assessment_version,
                    "target_level": st.session_state.target_level,
                    "assessment_date": phase_dates[phase_name],
                    "session_type": phase_name,
                    "valid_items": row["valid_items"],
                    "na_items": row["na_items"],
                    "missing_items": row["missing_items"],
                    "opportunity_1_to_5": transfer.get("application_opportunity") if phase_name == "post" else None,
                    "manager_support_1_to_5": transfer.get("supervisor_support") if phase_name == "post" else None,
                    "resource_support_1_to_5": transfer.get("resources_authority") if phase_name == "post" else None,
                }
            )
    export_name = "tap_individual_pre_post_result"
else:
    export_payload = results
    csv_rows = results
    export_name = "tap_individual_result"

json_bytes = json.dumps(export_payload, ensure_ascii=False, indent=2).encode("utf-8")
csv_buffer = io.StringIO()
if csv_rows:
    writer = csv.DictWriter(csv_buffer, fieldnames=list(csv_rows[0].keys()))
    writer.writeheader()
    writer.writerows(csv_rows)
d1, d2 = st.columns(2)
d1.download_button("결과 JSON", json_bytes, f"{export_name}.json", "application/json", width="stretch")
d2.download_button(
    "결과 CSV",
    csv_buffer.getvalue().encode("utf-8-sig"),
    f"{export_name}.csv",
    "text/csv",
    width="stretch",
)
