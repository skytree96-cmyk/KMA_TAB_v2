"""Tenant-authorized individual and privacy-thresholded organization summaries."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd
import streamlit as st

from tap.aggregation import aggregate_paired_factor_results
from tap.config import MIN_GROUP_N
from tap.data import questions_for_factors
from tap.scoring import score_pre_post_responses


def summarize_project(project: Mapping[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    config = project["config"]
    questions = config.get("question_snapshot") or questions_for_factors(config["selected_factors"])
    paired = []
    for result in results:
        if not result.get("pre_completed") or not result.get("post_completed"):
            continue
        pre = result.get("pre_payload") or {}
        post = result.get("post_payload") or {}
        for row in score_pre_post_responses(questions, pre.get("responses", {}), post.get("responses", {}), config.get("target_means")):
            row["participant_id"] = result["user_id"]
            paired.append(row)
    return aggregate_paired_factor_results(paired, min_group_n=MIN_GROUP_N)


def _render_individual_report(project: Mapping[str, Any], results: list[dict[str, Any]]) -> None:
    st.subheader("개인별 전·후 리포트")
    key = f"account_individual_{project['id']}_"
    query = st.text_input("참여자 검색", placeholder="이름 또는 아이디", key=key + "search")
    words = query.casefold().split()
    eligible = {str(row["id"]): row for row in results
                if row.get("pre_completed") and row.get("post_completed")
                and all(word in f"{row.get('user_name', '')} {row.get('login_id', '')}".casefold() for word in words)}
    if st.session_state.get(key + "selected") not in eligible:
        st.session_state.pop(key + "selected", None)
    if not eligible:
        st.info("사전·사후 검사를 모두 완료한 참여자가 검색되면 개인별 리포트를 확인할 수 있습니다.")
        return
    selected = st.selectbox("리포트 참여자", list(eligible), index=None,
                            placeholder="참여자를 선택하세요",
                            format_func=lambda value: f"{eligible[value].get('user_name', '')} · {eligible[value].get('login_id', '')}",
                            key=key + "selected")
    if selected not in eligible:
        return
    result = eligible[selected]
    config = project["config"]
    questions = config.get("question_snapshot") or questions_for_factors(config["selected_factors"])
    scored = score_pre_post_responses(questions, (result.get("pre_payload") or {}).get("responses", {}),
                                     (result.get("post_payload") or {}).get("responses", {}), config.get("target_means"))
    frame = pd.DataFrame([{"역량": row["factor_name_ko"], "교육 전": row["pre_score"], "교육 후": row["post_score"],
                           "변화": row["self_reported_change"], "전·후 유효 문항": row["paired_valid_items"]} for row in scored])
    st.dataframe(frame, hide_index=True, width="stretch")
    plot = frame.dropna(subset=["교육 전", "교육 후"])
    if not plot.empty:
        st.bar_chart(plot.set_index("역량")[["교육 전", "교육 후"]], horizontal=True, color=["#7ac7bd", "#087b76"])
    st.caption("동일 참여자의 두 시점 모두 1~5로 응답한 문항만 비교합니다. 0(수행 기회 없음)은 제외하며, 유효 문항이 부족하면 점수를 표시하지 않습니다. 자기보고 변화로 교육의 인과효과를 의미하지 않습니다.")


def render_project_report(store: Any, token: str, project: Mapping[str, Any]) -> None:
    # This read checks the live session role and company/project scope on the server.
    results = store.project_results(token, project["id"])
    st.subheader("참여 현황")
    columns = st.columns(3)
    columns[0].metric("배정 인원", len(results))
    columns[1].metric("사전검사 완료", sum(bool(row.get("pre_completed")) for row in results))
    columns[2].metric("사후검사 완료", sum(bool(row.get("post_completed")) for row in results))
    _render_individual_report(project, results)
    st.subheader("조직 전·후 리포트")
    summaries = summarize_project(project, results)
    if not summaries:
        st.info("사전·사후 검사를 모두 마친 참여자가 있으면 변화 리포트가 표시됩니다.")
        return
    disclosed = [row for row in summaries if row["paired_n"] >= MIN_GROUP_N]
    if not disclosed:
        st.info(f"각 역량의 사전·사후 유효응답이 {MIN_GROUP_N}명 이상일 때 평균과 변화량을 공개합니다.")
        return
    display_rows = [{"역량": row["factor_name_ko"], "전·후 유효 인원": row["paired_n"], "교육 전": row["pre_mean"], "교육 후": row["post_mean"], "변화": row["observed_change"], "상태": row["status"]} for row in summaries]
    frame = pd.DataFrame(display_rows)
    st.dataframe(frame, hide_index=True, use_container_width=True)
    plot = pd.DataFrame([{"역량": row["factor_name_ko"], "교육 전": row["pre_mean"], "교육 후": row["post_mean"]} for row in disclosed]).set_index("역량")
    st.bar_chart(plot, horizontal=True)
    st.caption("동일 참여자·동일 문항의 자기보고 변화입니다. 수행 기회 없음(0)은 점수에서 제외하며, 교육의 인과적 효과를 의미하지 않습니다.")
    st.download_button("조직 변화 요약 CSV", frame.to_csv(index=False).encode("utf-8-sig"), file_name="kma-tap-summary.csv", mime="text/csv", key=f"account_report_download_{project['id']}")