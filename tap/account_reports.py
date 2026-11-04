"""Tenant-authorized individual and privacy-thresholded organization summaries."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd
import streamlit as st

from tap.account_insights import (COURSE_INQUIRY_URL, course_context_note, organization_detail_rows, recommend_courses,
                                  summarize_transfer, transfer_notes)
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


def individual_report_pdf(project: Mapping[str, Any], questions: list[dict[str, Any]], pre_responses: Mapping[str, Any],
                          post_responses: Mapping[str, Any], subject: str) -> bytes:
    """Build one person's pre/post PDF from responses the caller is already authorized to read."""
    from tap.account_report_pdf import build_report_pdf
    scores = score_pre_post_responses(questions, pre_responses, post_responses, (project.get("config") or {}).get("target_means"))
    rows = [{**row, "change": row["self_reported_change"], "valid_n": row["paired_valid_items"]} for row in scores]
    # Personal transfer answers stay out of the PDF: managers can also download it.
    # Same picks as the participant screen: three competencies, each with a public course and an e-learning course.
    courses = recommend_courses(project.get("config") or {}, scores, limit=6)
    return build_report_pdf(project, rows, kind="individual", subject=subject, participant_count=1, courses=courses)


def export_report_pdf(store: Any, token: str, project: Mapping[str, Any], assignment_id: str | None = None) -> bytes:
    """Generate on download, rechecking the session and project scope each time."""
    from tap.account_report_pdf import build_report_pdf
    from tap.account_store import ValidationError
    results = store.project_results(token, project["id"])
    config = project["config"]
    questions = config.get("question_snapshot") or questions_for_factors(config["selected_factors"])
    if assignment_id is not None:
        result = next((row for row in results if str(row["id"]) == assignment_id), None)
        if not result or not result.get("pre_completed") or not result.get("post_completed"):
            raise ValidationError("교육 전후 검사를 모두 완료한 참여자를 선택해 주세요.")
        subject = " · ".join(str(part) for part in (result.get("user_name") or "참여자", result.get("login_id")) if part)
        return individual_report_pdf(project, questions, (result.get("pre_payload") or {}).get("responses", {}),
                                     (result.get("post_payload") or {}).get("responses", {}), subject)
    summaries = {row["factor_code"]: row for row in summarize_project(project, results)}
    if not any(row["paired_n"] >= MIN_GROUP_N for row in summaries.values()):
        raise ValidationError("조직 리포트는 역량별 교육 전후 유효응답이 5명 이상일 때 다운로드할 수 있습니다.")
    metadata = {row["factor_code"]: row for row in questions}
    rows = []
    for code, question in metadata.items():
        row = summaries.get(code, {})
        rows.append({"factor_code":code,"factor_name_ko":question["factor_name_ko"],"module_group":question.get("module_group", ""),
                     "pre_score":row.get("pre_mean"),"post_score":row.get("post_mean"),"change":row.get("observed_change"),
                     "valid_n":row.get("paired_n",0)})
    count = len({row["user_id"] for row in results if row.get("pre_completed") and row.get("post_completed")})
    return build_report_pdf(project, rows, kind="organization", subject="조직 전체", participant_count=count,
                            transfer=summarize_transfer(results), courses=_organization_courses(config, summaries.values()))


def _organization_courses(config: Mapping[str, Any], summaries: Any) -> list[dict[str, Any]]:
    disclosed = [{**row, "pre_score": row["pre_mean"], "post_score": row["post_mean"]}
                 for row in summaries if row["paired_n"] >= MIN_GROUP_N]
    # Three competencies × (public course, e-learning, in-house inquiry course).
    return recommend_courses(config, disclosed, limit=9, audience="organization")


def _render_transfer(results: list[dict[str, Any]]) -> dict[str, Any]:
    transfer = summarize_transfer(results)
    st.subheader("현업전이 환경")
    if not transfer["disclosed"]:
        st.info(f"교육 후 검사의 현업전이 응답이 {MIN_GROUP_N}명 이상일 때 평균과 적용 장애요인을 공개합니다. 현재 {transfer['n']}명입니다.")
        return transfer
    columns = st.columns(len(transfer["factors"]))
    for column, row in zip(columns, transfer["factors"]):
        column.metric(row["label"], f"{row['mean']:.2f} / 5")
    barriers = pd.DataFrame([{"장애요인": row["label"], "응답 비율(%)": row["rate"]} for row in transfer["barriers"]])
    st.bar_chart(barriers.set_index("장애요인"), horizontal=True, color="#087b76")
    for note in transfer_notes(transfer):
        st.markdown("- " + note)
    st.caption(f"교육 후 검사 응답 {transfer['n']}명 기준입니다. 적용 장애요인은 복수 선택이며, 서술형 적용 사례는 조직 리포트에 표시하지 않습니다.")
    return transfer


def _render_courses(courses: list[dict[str, Any]], transfer: Mapping[str, Any]) -> None:
    st.subheader("교육과정 검토 우선순위")
    if not courses:
        st.success("목표보다 0.2점 이상 낮은 공개 역량이 없어 검토할 후속 과정이 없습니다.")
    elif note := course_context_note(transfer):
        st.warning(note)
    if courses:
        from tap.account_course_ui import render_course_cards
        render_course_cards(courses)
        st.caption("교육 후 평균이 목표보다 0.2점 이상 낮은 역량을 차이가 큰 순서로 골라, 역량마다 공개교육, 이러닝, 단체교육 문의 과정을 제안합니다. "
                   "공개교육은 개강이 일주일 넘게 남은 기수가 있는 과정만 보여 주고, 버튼을 누르면 최신 일정 페이지가 열립니다.")
    st.markdown("회사 상황에 맞춘 과정이 필요하면 KMA에 문의하세요.")
    st.link_button("맞춤형 교육 문의", COURSE_INQUIRY_URL)


def _render_individual_report(store: Any, token: str, project: Mapping[str, Any], results: list[dict[str, Any]]) -> None:
    st.subheader("개인별 교육 전후 리포트")
    key = f"account_individual_{project['id']}_"
    query = st.text_input("참여자 검색", placeholder="이름 또는 아이디", key=key + "search")
    words = query.casefold().split()
    eligible = {str(row["id"]): row for row in results
                if row.get("pre_completed") and row.get("post_completed")
                and all(word in f"{row.get('user_name', '')} {row.get('login_id', '')}".casefold() for word in words)}
    if st.session_state.get(key + "selected") not in eligible:
        st.session_state.pop(key + "selected", None)
    if not eligible:
        st.info("교육 전후 검사를 모두 마친 참여자가 검색되면 개인별 리포트를 볼 수 있습니다.")
        return
    selected = st.selectbox("리포트 참여자", list(eligible), index=None,
                            placeholder="참여자를 선택하세요",
                            format_func=lambda value: f"{eligible[value].get('user_name', '')} · {eligible[value].get('login_id', '')}",
                            key=key + "selected")
    if selected not in eligible:
        return
    st.download_button("개인 리포트 PDF 다운로드", data=lambda: export_report_pdf(store, token, project, selected),
                       file_name="KMA_TAP_개인리포트.pdf", mime="application/pdf", on_click="ignore", type="primary",
                       key=key + "pdf", width="stretch")
    result = eligible[selected]
    config = project["config"]
    questions = config.get("question_snapshot") or questions_for_factors(config["selected_factors"])
    scored = score_pre_post_responses(questions, (result.get("pre_payload") or {}).get("responses", {}),
                                     (result.get("post_payload") or {}).get("responses", {}), config.get("target_means"))
    frame = pd.DataFrame([{"역량": row["factor_name_ko"], "교육 전": row["pre_score"], "교육 후": row["post_score"],
                           "변화": row["self_reported_change"], "전후 유효 문항": row["paired_valid_items"]} for row in scored])
    st.dataframe(frame, hide_index=True, width="stretch")
    plot = frame.dropna(subset=["교육 전", "교육 후"])
    if not plot.empty:
        st.bar_chart(plot.set_index("역량")[["교육 전", "교육 후"]], horizontal=True, stack=False, color=["#7ac7bd", "#087b76"])
    st.caption("교육 전후 모두 1~5로 응답한 문항만 비교합니다. 0(수행 기회 없음)은 빼고, 유효 문항이 부족하면 점수를 표시하지 않습니다. 자기보고 변화이며 교육의 인과효과를 뜻하지 않습니다.")


def render_project_report(store: Any, token: str, project: Mapping[str, Any]) -> None:
    # This read checks the live session role and company/project scope on the server.
    results = store.project_results(token, project["id"])
    st.subheader("참여 현황")
    columns = st.columns(3)
    columns[0].metric("배정 인원", len(results))
    columns[1].metric("교육 전 검사 완료", sum(bool(row.get("pre_completed")) for row in results))
    columns[2].metric("교육 후 검사 완료", sum(bool(row.get("post_completed")) for row in results))
    _render_individual_report(store, token, project, results)
    st.subheader("조직 교육 전후 리포트")
    st.caption(f"선택한 프로젝트: {project.get('name') or project.get('project_name') or project['id']} · 다른 프로젝트는 프로젝트 목록에서 선택하세요.")
    summaries = summarize_project(project, results)
    if not summaries:
        st.info("교육 전후 검사를 모두 마친 참여자가 있으면 변화 리포트가 표시됩니다.")
        return
    disclosed = [row for row in summaries if row["paired_n"] >= MIN_GROUP_N]
    if not disclosed:
        st.info(f"각 역량의 교육 전후 유효응답이 {MIN_GROUP_N}명 이상일 때 평균과 변화량을 공개합니다.")
        return
    st.download_button("조직 리포트 PDF 다운로드", data=lambda: export_report_pdf(store, token, project),
                       file_name="KMA_TAP_조직리포트.pdf", mime="application/pdf", on_click="ignore", type="primary",
                       key=f"account_report_pdf_{project['id']}", width="stretch")
    display_rows = [{"역량": row["factor_name_ko"], "전후 유효 인원": row["paired_n"], "교육 전": row["pre_mean"], "교육 후": row["post_mean"], "변화": row["observed_change"], "상태": row["status"]} for row in summaries]
    frame = pd.DataFrame(display_rows)
    st.dataframe(frame, hide_index=True, use_container_width=True)
    plot = pd.DataFrame([{"역량": row["factor_name_ko"], "교육 전": row["pre_mean"], "교육 후": row["post_mean"]} for row in disclosed]).set_index("역량")
    # Side by side, not stacked: pre and post are two readings of the same 1~5 scale.
    st.bar_chart(plot, horizontal=True, stack=False, color=["#7ac7bd", "#087b76"])
    st.caption("같은 참여자가 같은 문항에 답한 자기보고 변화입니다. 수행 기회 없음(0)은 점수에서 빼며, 교육의 인과효과를 뜻하지 않습니다.")
    transfer = _render_transfer(results)
    _render_courses(_organization_courses(project["config"], summaries), transfer)
    detail = pd.DataFrame(organization_detail_rows(summaries, project["config"], transfer))
    # Mixed row types leave blanks; nullable integers keep counts as 8, not 8.0, in the CSV.
    detail = detail.astype({column: "Int64" for column in ("교육 전 응답", "교육 후 응답", "교육 전후 유효 인원", "교육 후 미응답", "응답 수", "비율(%)")
                            if column in detail})
    st.download_button("조직 리포트 상세 CSV", detail.to_csv(index=False).encode("utf-8-sig"), file_name="kma-tap-detail.csv", mime="text/csv", key=f"account_report_download_{project['id']}")
    st.caption("상세 CSV에는 역량별 응답 인원, 교육 전후 점수, 목표 대비 차이와 현업전이 환경, 장애요인 집계가 담깁니다. 개인별 응답은 넣지 않습니다.")