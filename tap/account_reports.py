"""Tenant-authorized organization summaries; never render individual answer rows."""
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


def render_project_report(store: Any, token: str, project: Mapping[str, Any]) -> None:
    # This read checks the live session role and company/project scope on the server.
    results = store.project_results(token, project["id"])
    st.subheader("참여 현황")
    columns = st.columns(3)
    columns[0].metric("배정 인원", len(results))
    columns[1].metric("사전검사 완료", sum(bool(row.get("pre_completed")) for row in results))
    columns[2].metric("사후검사 완료", sum(bool(row.get("post_completed")) for row in results))
    st.subheader("교육 전·후 변화")
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