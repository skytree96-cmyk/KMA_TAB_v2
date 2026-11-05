"""Tenant-authorized individual and privacy-thresholded organization summaries."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd
import streamlit as st

from tap.account_insights import (COURSE_INQUIRY_URL, TRANSFER_ATTENTION_MEAN, course_context_note, course_gap_counts,
                                  hidden_team_note, organization_detail_rows, team_heatmap,
                                  recommend_courses, summarize_transfer, transfer_notes)
from tap.account_ui_kit import bar_rows, chip, fmt, foot, heatmap, notes, pair_bar_rows, section, stat_tiles
from tap.aggregation import aggregate_paired_factor_results
from tap.config import MIN_GROUP_N
from tap.data import questions_for_factors
from tap.scoring import score_pre_post_responses


COMPARE_NOTE = ("교육 전후 모두 1~5로 답한 문항만 비교합니다. 수행 기회 없음(0)은 빼고, 유효 문항이 부족하면 점수를 비웁니다. "
                "자기보고 변화이며 교육의 인과효과를 뜻하지 않습니다.")


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


UNASSIGNED_TEAM = "부서 미지정"
# What the heatmap can be grouped by: one department and one job title per person. Groups a person can be
# in several of are left out on purpose: overlapping averages can be subtracted down to a few people.
TEAM_BASES = {"department": ("부서별", UNASSIGNED_TEAM), "job_title": ("직급별", "직급 미지정")}
# Only a KMA administrator opens another person's report. The participant reads their own on their own screen.
INDIVIDUAL_REPORT_ROLES = frozenset({"kma"})
INDIVIDUAL_REPORT_RULE = "개인별 리포트는 참여자 본인과 KMA 담당자만 열 수 있습니다."


def can_open_individual_reports(store: Any, token: str) -> bool:
    """Asked from the store on every call, so a changed role or an ended session is noticed. Fails closed."""
    try:
        return str(store.principal(token).get("role")) in INDIVIDUAL_REPORT_ROLES
    except AttributeError:
        return False


def team_of(result: Mapping[str, Any], basis: str = "department") -> str:
    """The group a result counts in: the membership kept at the post assessment, else the account as it is now."""
    return str(result.get("report_" + basis) or result.get(basis) or "").strip() or TEAM_BASES[basis][1]


def summarize_by_team(project: Mapping[str, Any], results: list[dict[str, Any]], basis: str = "department") -> list[dict[str, Any]]:
    """The organization summary again per department (or job title), for the team heatmap."""
    unassigned = TEAM_BASES[basis][1]
    groups: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        groups.setdefault(team_of(result, basis), []).append(result)
    return [{"team": team, "summaries": summarize_project(project, rows),
             "paired_n": len({row["user_id"] for row in rows if row.get("pre_completed") and row.get("post_completed")})}
            for team, rows in sorted(groups.items(), key=lambda item: (item[0] == unassigned, item[0]))]


def individual_report_pdf(project: Mapping[str, Any], questions: list[dict[str, Any]], pre_responses: Mapping[str, Any],
                          post_responses: Mapping[str, Any], subject: str) -> bytes:
    """Build one person's pre/post PDF from responses the caller is already authorized to read."""
    from tap.account_report_pdf import build_report_pdf
    scores = score_pre_post_responses(questions, pre_responses, post_responses, (project.get("config") or {}).get("target_means"))
    rows = [{**row, "change": row["self_reported_change"], "valid_n": row["paired_valid_items"]} for row in scores]
    # Personal transfer answers stay out of the PDF.
    # Same picks as the participant screen: three competencies, each with a public course and an e-learning course.
    courses = recommend_courses(project.get("config") or {}, scores, limit=6)
    return build_report_pdf(project, rows, kind="individual", subject=subject, participant_count=1, courses=courses)


def export_report_pdf(store: Any, token: str, project: Mapping[str, Any], assignment_id: str | None = None) -> bytes:
    """Generate on download, rechecking the session and project scope each time."""
    from tap.account_report_pdf import build_report_pdf
    from tap.account_store import AuthorizationError, ValidationError
    if assignment_id is not None and not can_open_individual_reports(store, token):
        raise AuthorizationError(INDIVIDUAL_REPORT_RULE)
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
    # The PDF decides whether the department page is worth printing (two departments with a shown cell).
    return build_report_pdf(project, rows, kind="organization", subject="조직 전체", participant_count=count,
                            transfer=summarize_transfer(results), courses=_organization_courses(config, summaries.values()),
                            heatmap=team_heatmap(summarize_by_team(project, results)))


def _disclosed_scores(summaries: Any) -> list[dict[str, Any]]:
    return [{**row, "pre_score": row["pre_mean"], "post_score": row["post_mean"]}
            for row in summaries if row["paired_n"] >= MIN_GROUP_N]


def _organization_courses(config: Mapping[str, Any], summaries: Any) -> list[dict[str, Any]]:
    # Three competencies × (public course, e-learning, in-house inquiry course).
    return recommend_courses(config, _disclosed_scores(summaries), limit=9, audience="organization")


def _percent(value: int, total: int) -> float | None:
    return value / total * 100 if total else None


def _rate_text(value: int, total: int) -> str:
    return f"명 · {value / total * 100:.0f}%" if total else "명"


def _render_participation(results: list[dict[str, Any]], *, individual_reports: bool = True) -> None:
    assigned = len(results)
    pre = sum(bool(row.get("pre_completed")) for row in results)
    post = sum(bool(row.get("post_completed")) for row in results)
    paired = sum(bool(row.get("pre_completed") and row.get("post_completed")) for row in results)
    with section("participation", "groups", "참여 현황", "배정 인원과 교육 전후 검사 완료 인원"):
        st.html(stat_tiles([
            ("배정 인원", f"{assigned}", "명", None, False),
            ("교육 전 검사 완료", f"{pre}", _rate_text(pre, assigned), _percent(pre, assigned), False),
            ("교육 후 검사 완료", f"{post}", _rate_text(post, assigned), _percent(post, assigned), False),
            ("교육 전후 비교 가능", f"{paired}", "명", None, False),
        ]))
        if not individual_reports:
            st.html(foot(INDIVIDUAL_REPORT_RULE + " 이 화면에는 조직 결과만 나옵니다."))


def _render_transfer(results: list[dict[str, Any]]) -> dict[str, Any]:
    transfer = summarize_transfer(results)
    with section("transfer", "work_history", "현업전이 환경", "교육 후 검사에서 답한 적용 여건 4가지(1~5)와 적용 장애요인",
                 tone="soft", chips=[chip(f"응답 {transfer['n']}명", icon_name="group")]):
        if not transfer["disclosed"]:
            st.info(f"교육 후 검사의 현업전이 응답이 {MIN_GROUP_N}명 이상일 때 평균과 적용 장애요인을 공개합니다. 지금은 {transfer['n']}명입니다.")
            return transfer
        st.html(stat_tiles([(row["label"], fmt(row["mean"]), "/ 5", row["mean"] / 5 * 100, row["mean"] < TRANSFER_ATTENTION_MEAN)
                            for row in transfer["factors"]]))
        left, right = st.columns([1.25, 1], gap="medium")
        with left:
            st.html('<div class="tap-sub">적용 장애요인 <span>· 복수 선택</span></div>'
                    + bar_rows([(row["label"], row["rate"], f"{row['count']}명 · {row['rate']}%") for row in transfer["barriers"]]))
        with right:
            # The first note names conditions under the attention mean; it is the one to act on.
            st.html(notes([(note, "warn" if note.startswith("평균이") else "") for note in transfer_notes(transfer)]))
        st.html(foot(f"교육 후 검사 응답 {transfer['n']}명 기준입니다. 서술형 적용 사례는 조직 리포트에 넣지 않습니다."))
    return transfer


def _render_courses(courses: list[dict[str, Any]], transfer: Mapping[str, Any], *, has_gap: bool = False) -> None:
    from tap.account_course_ui import render_course_cards
    with section("courses", "school", "교육과정 검토 우선순위",
                 "교육 후 평균이 목표보다 0.2점 이상 낮은 역량과, 역량마다 연결된 KMA 과정(공개교육 · 이러닝 · 단체교육 문의)", tone="tint"):
        if not courses and has_gap:
            st.info("목표보다 낮은 공개 역량은 있지만 지금 추천할 수 있는 KMA 과정이 없습니다. 아래 단체교육 문의를 이용해 주세요.")
        elif not courses:
            st.success("목표보다 0.2점 이상 낮은 공개 역량이 없어 검토할 후속 과정이 없습니다.")
        else:
            if note := course_context_note(transfer):
                st.html(notes([(note, "warn")]))
            render_course_cards(courses)
            from tap.course_schedule import schedule_basis
            st.html(foot("공개교육은 개강까지 7일 이상 남은 기수가 있는 과정만 보여 줍니다. "
                         + schedule_basis() + " 개설 여부와 교육비는 KMA 페이지에서 확인하세요."))
        st.caption("회사 상황에 맞춘 과정은 KMA에 문의하세요.")
        st.link_button("맞춤형 교육 문의", COURSE_INQUIRY_URL, icon=":material/mail:")


def _render_individual_report(store: Any, token: str, project: Mapping[str, Any], results: list[dict[str, Any]]) -> None:
    key = f"account_individual_{project['id']}_"
    with section("individual", "person", "개인별 교육 전후 리포트",
                 "교육 전후 검사를 모두 마친 참여자의 역량별 변화. 본인 면담 등 정해진 용도로만 사용"):
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
                           icon=":material/download:", key=key + "pdf")
        result = eligible[selected]
        config = project["config"]
        questions = config.get("question_snapshot") or questions_for_factors(config["selected_factors"])
        scored = score_pre_post_responses(questions, (result.get("pre_payload") or {}).get("responses", {}),
                                         (result.get("post_payload") or {}).get("responses", {}), config.get("target_means"))
        frame = pd.DataFrame([{"역량": row["factor_name_ko"], "교육 전": row["pre_score"], "교육 후": row["post_score"],
                               "변화": row["self_reported_change"], "전후 유효 문항": row["paired_valid_items"]} for row in scored])
        st.dataframe(frame, hide_index=True, width="stretch")
        plotted = [row for row in scored if row["pre_score"] is not None and row["post_score"] is not None]
        if plotted:
            st.html(pair_bar_rows([(row["factor_name_ko"], row["pre_score"], row["post_score"],
                                    f"{fmt(row['pre_score'])} → {fmt(row['post_score'])}") for row in plotted]))
        st.html(foot(COMPARE_NOTE))


def _render_team_heatmap(project: Mapping[str, Any], results: list[dict[str, Any]]) -> None:
    # A basis is offered only when it splits the people in two or more groups: one group is the organization result again.
    grids = {}
    for basis in TEAM_BASES:
        teams = summarize_by_team(project, results, basis)
        if len([team for team in teams if team["paired_n"]]) >= 2:
            grids[basis] = team_heatmap(teams)
    if not grids:
        return
    with section("teams", "grid_view", "팀(부서)별 교육 후 평균",
                 "부서·직급별 역량 평균(1~5)과 교육 전후 변화. 묶음·역량별 교육 전후 유효응답 5명 이상만 공개"):
        basis = next(iter(grids))
        if len(grids) > 1:
            basis = st.segmented_control("묶는 기준", list(grids), format_func=lambda value: TEAM_BASES[value][0], default=basis,
                                         key=f"account_team_basis_{project['id']}", label_visibility="collapsed") or basis
        grid = grids[basis]
        st.html(heatmap([factor["factor_name_ko"] for factor in grid["factors"]],
                        [(row["team"], f"전후 비교 {row['paired_n']}명",
                          [(cell["post_mean"], cell["change"]) for cell in row["cells"]], hidden_team_note(row))
                         for row in grid["rows"]]))
        unassigned = next((row["paired_n"] for row in grid["rows"] if row["team"] == TEAM_BASES[basis][1]), 0)
        st.html(foot("칸의 큰 숫자는 교육 후 평균, 작은 숫자는 교육 전후 변화입니다. 진할수록 평균이 높습니다. "
                     "교육 후 검사를 마친 시점의 소속으로 묶습니다. 그 뒤에 부서나 직급을 옮겨도 이 표는 바뀌지 않습니다."
                     + (f" {TEAM_BASES[basis][1]} {unassigned}명은 한 줄로 모았습니다." if unassigned else "")))


def render_project_report(store: Any, token: str, project: Mapping[str, Any]) -> None:
    # This read checks the live session role and company/project scope on the server.
    results = store.project_results(token, project["id"])
    individual_reports = can_open_individual_reports(store, token)
    _render_participation(results, individual_reports=individual_reports)
    if individual_reports:
        _render_individual_report(store, token, project, results)
    summaries = summarize_project(project, results)
    disclosed = [row for row in summaries if row["paired_n"] >= MIN_GROUP_N]
    paired = len({row["user_id"] for row in results if row.get("pre_completed") and row.get("post_completed")})
    chips = [chip(str(project.get("name") or project.get("project_name") or project["id"]), icon_name="folder_open")]
    if disclosed:
        chips.append(chip(f"공개 역량 {len(disclosed)} / {len(summaries)}", icon_name="verified", tone="ok"))
        chips.append(chip(f"전후 비교 {paired}명", icon_name="group"))
    with section("organization", "bar_chart", "조직 교육 전후 리포트",
                 "같은 참여자가 같은 문항에 답한 역량별 평균 변화. 역량별 유효응답 5명 이상만 공개", chips=chips):
        if not summaries:
            st.info("교육 전후 검사를 모두 마친 참여자가 있으면 변화 리포트가 표시됩니다.")
        elif not disclosed:
            st.info(f"각 역량의 교육 전후 유효응답이 {MIN_GROUP_N}명 이상일 때 평균과 변화량을 공개합니다.")
        else:
            st.download_button("조직 리포트 PDF 다운로드", data=lambda: export_report_pdf(store, token, project),
                               file_name="KMA_TAP_조직리포트.pdf", mime="application/pdf", on_click="ignore", type="primary",
                               icon=":material/download:", key=f"account_report_pdf_{project['id']}")
            display_rows = [{"역량": row["factor_name_ko"], "전후 유효 인원": row["paired_n"], "교육 전": row["pre_mean"], "교육 후": row["post_mean"],
                             "변화": row["observed_change"], "상태": row["status"]} for row in summaries]
            st.dataframe(pd.DataFrame(display_rows), hide_index=True, width="stretch")
            # Side by side, not stacked: pre and post are two readings of the same 1~5 scale.
            st.html(pair_bar_rows([(row["factor_name_ko"], row["pre_mean"], row["post_mean"],
                                    f"{fmt(row['pre_mean'])} → {fmt(row['post_mean'])}") for row in disclosed]))
            st.html(foot("같은 참여자가 같은 문항에 답한 자기보고 변화입니다. 수행 기회 없음(0)은 점수에서 빼며, 교육의 인과효과를 뜻하지 않습니다."))
    if not disclosed:
        return
    _render_team_heatmap(project, results)
    transfer = _render_transfer(results)
    _, below = course_gap_counts(project["config"], _disclosed_scores(summaries))
    _render_courses(_organization_courses(project["config"], summaries), transfer, has_gap=bool(below))
    detail = pd.DataFrame(organization_detail_rows(summaries, project["config"], transfer))
    # Mixed row types leave blanks; nullable integers keep counts as 8, not 8.0, in the CSV.
    detail = detail.astype({column: "Int64" for column in ("교육 전 응답", "교육 후 응답", "교육 전후 유효 인원", "교육 후 미응답", "응답 수", "비율(%)")
                            if column in detail})
    st.download_button("조직 리포트 상세 CSV", detail.to_csv(index=False).encode("utf-8-sig"), file_name="kma-tap-detail.csv", mime="text/csv",
                       icon=":material/table_view:", key=f"account_report_download_{project['id']}")
    st.caption("상세 CSV에는 역량별 응답 인원, 교육 전후 점수, 목표 대비 차이와 현업전이 환경, 장애요인 집계가 담깁니다. 개인별 응답은 넣지 않습니다.")
