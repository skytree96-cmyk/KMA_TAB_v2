"""Company training demand: across every project of one company, how many people need each competency.

Each person counts once, with their most recent submitted test in the last twelve months (the post test
when there is one). A person "needs" a competency when that score is at least 0.2 below the project's
target. Only counts per competency and per department leave this module, under the N>=5 rule, so no
person can be picked out.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import StringIO
import csv
from typing import Any, Iterable, Mapping

import streamlit as st

from tap.account_insights import MEANINGFUL_DIFFERENCE, recommend_courses
from tap.account_ui_kit import bar_rows, foot, section, stat_tiles
from tap.config import MIN_GROUP_N
from tap.data import questions_for_factors
from tap.scoring import score_responses

DEMAND_DAYS = 365
UNASSIGNED = "부서 미지정"
KST = timezone(timedelta(hours=9))


def _latest_tests(rows: Iterable[Mapping[str, Any]], now: float) -> dict[str, tuple[Mapping[str, Any], str]]:
    """Each person's most recent submitted test within DEMAND_DAYS, as (assignment row, phase)."""
    cutoff = now - DEMAND_DAYS * 86400
    latest: dict[str, tuple[float, Mapping[str, Any], str]] = {}
    for row in rows:
        for phase in ("post", "pre"):
            when = row.get(phase + "_completed_at")
            if not row.get(phase + "_payload") or when is None or float(when) < cutoff:
                continue
            key = str(row["user_id"])
            if key not in latest or float(when) > latest[key][0]:
                latest[key] = (float(when), row, phase)
            break  # the post test, when there is one, is that assignment's latest word
    return {key: (row, phase) for key, (_, row, phase) in latest.items()}


def _interests(rows: Iterable[Mapping[str, Any]], user_id: str) -> set[str]:
    """The person's wishes from their most recent pre-training test."""
    picks = [(float(row.get("pre_completed_at") or 0), row) for row in rows
             if str(row["user_id"]) == user_id and row.get("pre_payload")]
    if not picks:
        return set()
    _, row = max(picks, key=lambda pick: pick[0])
    return {str(code) for code in row["pre_payload"].get("learning_interests") or []}


def _team(row: Mapping[str, Any]) -> str:
    return str(row.get("report_department") or row.get("department") or "").strip() or UNASSIGNED


def company_demand(rows: list[Mapping[str, Any]], *, now: float | None = None, min_n: int = MIN_GROUP_N) -> dict[str, Any]:
    """Counts per competency and per department; cells under min_n people are hidden."""
    now = now if now is not None else datetime.now(KST).timestamp()
    people = _latest_tests(rows, now)
    names: dict[str, str] = {}
    tally: dict[str, dict[str, Any]] = {}
    for user_id, (row, phase) in people.items():
        config = row.get("config") or {}
        questions = config.get("question_snapshot") or questions_for_factors(config.get("selected_factors") or [])
        wishes = _interests(rows, user_id)
        team = _team(row)
        for score in score_responses(questions, row[phase + "_payload"].get("responses") or {}, config.get("target_means")):
            if score["score_1_to_5"] is None:
                continue
            code = str(score["factor_code"])
            names.setdefault(code, str(score["factor_name_ko"]))
            entry = tally.setdefault(code, {"n": 0, "need": 0, "interest": 0, "teams": {}})
            needs = round(float(score["target_mean"]) - float(score["score_1_to_5"]), 2) >= MEANINGFUL_DIFFERENCE
            entry["n"] += 1
            entry["need"] += needs
            entry["interest"] += code in wishes
            cell = entry["teams"].setdefault(team, [0, 0])
            cell[0] += 1
            cell[1] += needs
    competencies = []
    for code, entry in tally.items():
        shown = entry["n"] >= min_n
        competencies.append({"factor_code": code, "factor_name_ko": names[code], "n": entry["n"], "shown": shown,
                             "need": entry["need"] if shown else None, "interest": entry["interest"] if shown else None,
                             "share": round(entry["need"] / entry["n"] * 100) if shown else None})
    competencies.sort(key=lambda row: (not row["shown"], -(row["share"] or 0), -(row["need"] or 0), row["factor_name_ko"]))
    teams = sorted({team for entry in tally.values() for team in entry["teams"]}, key=lambda team: (team == UNASSIGNED, team))
    grid = []
    for row in competencies:
        cells = {}
        counts = tally[row["factor_code"]]["teams"]
        for team in teams:
            n, need = counts.get(team, (0, 0))
            cells[team] = {"n": n, "share": round(need / n * 100) if row["shown"] and n >= min_n else None}
        # One hidden department next to the company total could be worked out; hide the smallest shown one too.
        hidden = [team for team in teams if cells[team]["n"] and cells[team]["share"] is None]
        shown_teams = [team for team in teams if cells[team]["share"] is not None]
        if row["shown"] and len(hidden) == 1 and shown_teams:
            cells[min(shown_teams, key=lambda team: (cells[team]["n"], team))]["share"] = None
        grid.append({"factor_code": row["factor_code"], "factor_name_ko": row["factor_name_ko"], "cells": cells})
    return {"people": len(people), "competencies": competencies, "teams": teams, "grid": grid}


def demand_courses(demand: Mapping[str, Any], limit_competencies: int = 3) -> list[dict[str, Any]]:
    """KMA courses for the competencies most people need, with the demand as the reason."""
    top = [row for row in demand["competencies"] if row["shown"] and row["need"]][:limit_competencies]
    if not top:
        return []
    # Fed as equal gaps so recommend_courses keeps this order; the reason is rewritten with the demand counts.
    config = {"target_means": {row["factor_code"]: 4.0 for row in top}, "target_level": "all", "delivery_preference": "all"}
    order = {row["factor_code"]: index for index, row in enumerate(top)}
    courses = recommend_courses(config, [{"factor_code": row["factor_code"], "factor_name_ko": row["factor_name_ko"],
                                          "post_score": 3.0} for row in top],
                                limit=3 * len(top), audience="organization", max_competencies=len(top))
    by_code = {row["factor_code"]: row for row in top}
    for course in courses:
        row = by_code[course["factor_code"]]
        course["reason"] = f"수요 {row['need']}명({row['share']}%)" + (f" · 학습 희망 {row['interest']}명" if row["interest"] else "")
        course["advice"] = ""
        course["score"] = course["target"] = None
    courses.sort(key=lambda course: order[course["factor_code"]])
    return courses


def demand_csv(demand: Mapping[str, Any]) -> bytes:
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(["역량", "응답 인원", "수요 인원", "수요 비율(%)", "학습 희망 인원", *[f"{team} 수요 비율(%)" for team in demand["teams"]]])
    grid = {row["factor_code"]: row for row in demand["grid"]}
    for row in demand["competencies"]:
        cells = grid[row["factor_code"]]["cells"]
        writer.writerow([row["factor_name_ko"], row["n"] if row["shown"] else f"{MIN_GROUP_N}명 미만",
                         row["need"] if row["shown"] else "", row["share"] if row["shown"] else "",
                         row["interest"] if row["shown"] else "",
                         *[("" if cells[team]["share"] is None else cells[team]["share"]) for team in demand["teams"]]])
    return out.getvalue().encode("utf-8-sig")


def render_company_demand(store: Any, token: str, *, company_id: str | None, company_name: str) -> None:
    from tap.account_course_ui import render_course_cards

    with section("demand", "query_stats", "회사 교육 수요",
                 f"{company_name} · 최근 12개월 · 사람마다 가장 최근 검사 기준. 역량별 응답 {MIN_GROUP_N}명 이상만 공개하고 개인은 드러나지 않음"):
        demand = company_demand(store.company_results(token, company_id))
        shown = [row for row in demand["competencies"] if row["shown"]]
        if not shown:
            st.info(f"역량별 응답이 {MIN_GROUP_N}명 이상 모이면 교육 수요가 표시됩니다. 지금 분석 인원은 {demand['people']}명입니다.")
            return
        top = max(shown, key=lambda row: (row["share"], row["need"]))
        wish = max(shown, key=lambda row: row["interest"])
        st.html(stat_tiles([
            ("분석 인원", f"{demand['people']:,}", "명", None, False),
            ("수요 1위 역량", top["factor_name_ko"], f"{top['share']}%", None, False),
            ("학습 희망 1위", wish["factor_name_ko"] if wish["interest"] else "—", f"{wish['interest']}명" if wish["interest"] else "", None, False),
        ]))
        st.html(bar_rows([(row["factor_name_ko"], row["share"],
                           f"{row['need']}명 / {row['n']}명 · 희망 {row['interest']}명") for row in shown]))
        hidden = [row["factor_name_ko"] for row in demand["competencies"] if not row["shown"]]
        if hidden:
            st.caption(f"응답 {MIN_GROUP_N}명 미만이라 숨긴 역량: " + ", ".join(hidden))
        teams = [team for team in demand["teams"] if any(row["cells"][team]["share"] is not None for row in demand["grid"])]
        if len(teams) >= 2:
            st.markdown("**부서별 수요 비율**")
            table = [{"역량": row["factor_name_ko"],
                      **{team: ("비공개" if row["cells"][team]["share"] is None else f"{row['cells'][team]['share']}%") for team in teams}}
                     for row in demand["grid"] if any(c["n"] for c in row["cells"].values())]
            st.dataframe(table, hide_index=True, width="stretch")
            st.caption(f"부서별 응답 {MIN_GROUP_N}명 이상인 칸만 보입니다. 한 부서만 가려지면 회사 합계로 계산할 수 있어 가장 작은 부서도 함께 가립니다.")
        courses = demand_courses(demand)
        if courses:
            st.markdown("**수요가 많은 역량과 연결 과정**")
            render_course_cards(courses)
        st.download_button("교육 수요 CSV 다운로드", demand_csv(demand), file_name="kma-tap-demand.csv", mime="text/csv",
                           icon=":material/table_view:", key="tap_demand_csv_" + str(company_id or "own"))
        st.html(foot("수요: 가장 최근 검사 점수가 프로젝트 목표보다 0.2점 이상 낮은 사람. 학습 희망: 교육 전 검사 끝에서 그 역량을 고른 사람. "
                     "본인이 답한 행동빈도(1~5) 기준입니다."))
