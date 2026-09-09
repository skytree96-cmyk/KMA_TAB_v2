"""Live, tenant-scoped operations overview using one aggregate store read."""
from __future__ import annotations

import logging
from datetime import date, datetime
from math import ceil
from html import escape

import altair as alt
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from tap.account_reports import render_project_report
from tap.account_store import AuthenticationError, AuthorizationError


LOGGER = logging.getLogger(__name__)
PREFIX = "account_dashboard_"
PAGE_SIZE = 12


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError:
        return None


def _count(project: Mapping[str, Any], key: str) -> int:
    return max(0, int(project.get(key) or 0))


def project_status(project: Mapping[str, Any], today: date) -> str:
    """Use the configured inclusive assessment windows and actual completions."""
    config = project.get("config") or {}
    assigned = _count(project, "assigned")
    if not assigned:
        return "참여자 배정 필요"
    if _count(project, "post_completed") >= assigned:
        return "검사 완료"
    pre_start, pre_end, training, post_start, post_end = (
        _date(config.get(key)) for key in (
            "pre_start_date", "pre_end_date", "training_date", "post_start_date", "post_end_date"
        )
    )
    if not all((pre_start, pre_end, training, post_start, post_end)):
        return "일정 확인 필요"
    if pre_start <= today <= pre_end and post_start <= today <= post_end:
        return "사전·사후검사 진행"
    if today < pre_start:
        return "사전검사 예정"
    if today <= pre_end:
        return "사전검사 진행"
    if today < post_start:
        return "교육 예정" if today < training else "사후검사 대기"
    if today <= post_end:
        return "사후검사 진행"
    return "사후검사 종료"


def schedule_checks(projects: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Return actionable counts, never participant identities or answer rows."""
    checks: list[dict[str, Any]] = []
    for project in projects:
        base = {"회사": project.get("company_name") or "—", "프로젝트": project["name"]}
        assigned = _count(project, "assigned")
        if not assigned:
            checks.append({**base, "확인할 내용": "참여자 배정 필요", "일정": "—"})
            continue
        config = project.get("config") or {}
        for phase, label in (("pre", "사전검사"), ("post", "사후검사")):
            remaining = max(0, assigned - _count(project, phase + "_completed"))
            if not remaining:
                continue
            start, end = _date(config.get(phase + "_start_date")), _date(config.get(phase + "_end_date"))
            if not start or not end:
                checks.append({**base, "확인할 내용": f"{label} 일정 확인 필요", "일정": "—"})
            elif today > end:
                checks.append({**base, "확인할 내용": f"{label} 마감 · 미완료 {remaining}명", "일정": end.isoformat()})
            elif start <= today <= end:
                checks.append({**base, "확인할 내용": f"{label} 진행 · 미완료 {remaining}명", "일정": end.isoformat()})
            elif 0 < (start - today).days <= 7:
                checks.append({**base, "확인할 내용": f"{label} {int((start - today).days)}일 후 시작", "일정": start.isoformat()})
    return sorted(checks, key=lambda row: (row["일정"] == "—", row["일정"], row["프로젝트"]))


def filter_projects(projects: list[dict[str, Any]], query: str, company_id: str | None = None) -> list[dict[str, Any]]:
    words = query.strip().casefold().split()
    return [project for project in projects if (
        (not company_id or project.get("company_id") == company_id)
        and all(word in " ".join(str(value or "") for value in (
            project.get("company_name"), project.get("name"), (project.get("config") or {}).get("course_name")
        )).casefold() for word in words)
    )]


def _show_error(exc: Exception) -> None:
    LOGGER.error("Account dashboard operation failed: %s", type(exc).__name__)
    if isinstance(exc, AuthenticationError):
        st.error("로그인 시간이 만료되었습니다. 다시 로그인해 주세요.")
    elif isinstance(exc, AuthorizationError):
        st.error("대시보드를 열람할 권한이 없습니다. 계정의 회사와 역할을 확인해 주세요.")
    else:
        st.error("운영 현황을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")


def _render_projects(store: Any, token: str, projects: list[dict[str, Any]], role: str, today: date) -> None:
    with st.container(key=PREFIX + "projects"):
        st.subheader("프로젝트 현황")
        company_id = None
        if role == "kma":
            companies = {str(project["company_id"]): str(project.get("company_name") or "회사명 미등록") for project in projects}
            company_key = PREFIX + "company"
            if st.session_state.get(company_key) not in {None, *companies}:
                st.session_state[company_key] = None
            company_id = st.selectbox("회사", [None, *sorted(companies, key=companies.get)],
                                      format_func=lambda value: "전체 회사" if value is None else companies[value], key=company_key)
        query = st.text_input("회사·프로젝트·교육 검색", key=PREFIX + "search", placeholder="회사명, 프로젝트명 또는 교육과정명")
        matches = filter_projects(projects, query, company_id)
        st.caption(f"검색 결과 {len(matches):,}개 / 전체 {len(projects):,}개 프로젝트")
        pages = max(1, ceil(len(matches) / PAGE_SIZE))
        page_key = PREFIX + "page"
        signature = (query.strip().casefold(), company_id)
        if st.session_state.get(PREFIX + "filter") != signature:
            st.session_state[page_key] = 1
            st.session_state[PREFIX + "filter"] = signature
        st.session_state[page_key] = min(max(1, int(st.session_state.get(page_key, 1))), pages)
        page = int(st.number_input("목록 페이지", min_value=1, max_value=pages, step=1, key=page_key)) if pages > 1 else 1
        visible = matches[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
        by_id = {str(project["id"]): project for project in visible}
        select_key = PREFIX + "report"
        if st.session_state.get(select_key) not in by_id:
            st.session_state[select_key] = None
        if not matches:
            st.info("검색 조건에 맞는 프로젝트가 없습니다.")
            return
        rows = []
        for project in visible:
            config = project.get("config") or {}
            row = {
                "회사": project.get("company_name") or "—", "프로젝트": project["name"],
                "교육과정": config.get("course_name") or "—", "상태": project_status(project, today),
                "배정": _count(project, "assigned"), "사전 완료": _count(project, "pre_completed"),
                "사후 완료": _count(project, "post_completed"), "교육일": config.get("training_date") or "미설정",
                "사전검사": f"{config.get('pre_start_date') or '미설정'} ~ {config.get('pre_end_date') or '미설정'}",
                "사후검사": f"{config.get('post_start_date') or '미설정'} ~ {config.get('post_end_date') or '미설정'}",
            }
            if role == "company":
                row.pop("회사")
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        selected = st.selectbox("교육 전·후 리포트", list(by_id), index=None, key=select_key,
                                placeholder="리포트를 볼 프로젝트를 선택하세요",
                                format_func=lambda value: " · ".join(str(item) for item in (
                                    by_id[value].get("company_name") if role == "kma" else None,
                                    by_id[value]["name"], (by_id[value].get("config") or {}).get("course_name")
                                ) if item))
        if selected in by_id:
            st.caption("동일 참여자의 전·후 응답을 조직 단위로 집계하며, 개인 응답과 개인 점수는 표시하지 않습니다.")
            try:
                render_project_report(store, token, by_id[selected])
            except Exception as exc:
                _show_error(exc)


def _rate(value: int, total: int) -> str:
    return f"{min(100, value / total * 100):.0f}%" if total else "—"


def _rings(total: int, values: list[tuple[str, int, str]]) -> None:
    cards = []
    for label, value, color in values:
        percent = min(100, value / total * 100) if total else 0
        cards.append(f'<div class="tap-dash-ring-item"><div class="tap-dash-ring" '
                     f'style="--rate:{percent};--ring:{color}"><strong>{_rate(value, total)}</strong></div>'
                     f'<b>{escape(label)}</b><span>{value:,} / {total:,}명</span></div>')
    st.html('<div class="tap-dash-rings">' + ''.join(cards) + '</div>')


def _ranking(rows: list[tuple[str, int, int]], *, unit: str = "명") -> None:
    if not rows:
        st.info("집계할 항목이 없습니다.")
        return
    items = []
    for index, (name, value, total) in enumerate(rows, 1):
        percent = min(100, value / total * 100) if total else 0
        items.append(f'<div class="tap-dash-rank"><span class="tap-dash-rank-no">{index:02}</span>'
                     f'<div class="tap-dash-rank-body"><div><b>{escape(str(name))}</b>'
                     f'<strong>{_rate(value, total)}</strong></div><span>{value:,} / {total:,}{unit}</span>'
                     f'<div class="tap-dash-track"><i style="width:{percent}%"></i></div></div></div>')
    st.html('<div class="tap-dash-ranking">' + ''.join(items) + '</div>')


def _render_trend(summary: dict[str, Any], role: str) -> None:
    with st.container(key=PREFIX + "trend", border=True):
        st.subheader("전체 검사 완료 추세" if role == "kma" else "조직 전체 검사 완료 추세")
        st.caption("최근 12개월 · 월별 검사 완료 인원 · 사전·사후 각각 동일인 중복 제외")
        months = list(summary.get("completion_trend") or [])
        if not months:
            st.info("검사를 완료하면 월별 추세가 표시됩니다.")
            return
        points = [{"월": row["month"], "검사": label, "완료 인원": _count(row, key)}
                  for row in months for key, label in (("pre_completed", "사전검사"), ("post_completed", "사후검사"))]
        frame = pd.DataFrame(points)
        base = alt.Chart(frame).encode(
            x=alt.X("월:O", title=None, sort=[row["month"] for row in months], axis=alt.Axis(labelAngle=-35)),
            y=alt.Y("완료 인원:Q", title="완료 인원 (명)", scale=alt.Scale(domainMin=0), axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("검사:N", scale=alt.Scale(domain=["사전검사", "사후검사"], range=["#087b76", "#45bdb1"]),
                            legend=alt.Legend(title=None, orient="top")),
            tooltip=["월:O", "검사:N", alt.Tooltip("완료 인원:Q", format=",")])
        chart = (base.mark_area(opacity=0.07, line=False).encode(y=alt.Y("완료 인원:Q", stack=None))
                 + base.mark_line(strokeWidth=3, point=alt.OverlayMarkDef(size=44, filled=True)))
        chart = chart.properties(height=270).configure_view(strokeWidth=0).configure_axis(
            labelFontSize=13, titleFontSize=13, labelColor="#54716f", gridColor="#e7f0ee", domain=False,
        ).configure_legend(labelFontSize=14).configure(background="transparent")
        st.altair_chart(chart, width="stretch")
        current = months[-1]
        pre, post = _count(current, "pre_completed"), _count(current, "post_completed")
        st.html(f'<div class="tap-dash-insight"><b>{escape(current["month"])} 검사 완료</b>'
                f'<span>사전검사 <strong>{pre:,}명</strong> · 사후검사 <strong>{post:,}명</strong></span></div>')
        st.caption("완료한 시점의 한국시간 월 기준입니다. 같은 사람이 두 검사를 완료하면 각 검사에 집계됩니다. 과거 참여율을 추정하지 않습니다.")


def render_dashboard(store: Any, token: str, principal: Mapping[str, Any]) -> None:
    role = principal.get("role")
    if role not in {"kma", "company"} or (role == "company" and not principal.get("company_id")):
        st.error("KMA 관리자 또는 교육담당자 계정으로 로그인해 주세요.")
        return
    st.title("대시보드")
    st.caption("회원사 전체의 역량검사 운영 현황을 한눈에 확인하세요." if role == "kma" else
               f"{principal.get('company_name') or '소속 회사'} · 조직 전체 역량검사 현황")
    try:
        summary = store.dashboard_summary(token)
    except Exception as exc:
        _show_error(exc)
        return
    projects = list(summary.get("projects") or [])
    if role == "company":
        projects = [project for project in projects if project.get("company_id") == principal["company_id"]]
    total = _count(summary, "participant_users_count")
    participating = _count(summary, "participating_users_count")
    pre, post = _count(summary, "pre_completed_users_count"), _count(summary, "post_completed_users_count")
    metrics = [("참여 기업", _count(summary, "participating_companies_count"), "개사"),
               ("검사 참여 인원", participating, "명"), ("전체 등록 참여자", total, "명"), ("운영 프로젝트", len(projects), "개")]
    if role == "company":
        metrics = [("검사 참여 인원", participating, "명"), ("사전검사 완료", pre, "명"),
                   ("사후검사 완료", post, "명"), ("운영 프로젝트", len(projects), "개")]
    with st.container(key=PREFIX + "metrics"):
        for column, (label, value, unit) in zip(st.columns(4, gap="small"), metrics):
            with column:
                st.metric(label, f"{value:,} {unit}", border=True)
    scope = f"전체 등록 기업 {_count(summary, 'companies_count'):,}개사 · " if role == "kma" else ""
    st.caption(f"{scope}전체 등록 참여자 {total:,}명 · 교육담당자 {_count(summary, 'company_users_count'):,}명")
    with st.container(key=PREFIX + "overview"):
        left, right = st.columns([1.1, 1], gap="medium")
        with left, st.container(key=PREFIX + "participation", border=True):
            st.subheader("전체 역량검사 참여 현황" if role == "kma" else "조직 전체 역량검사 참여 현황")
            st.caption("전체 등록 참여자 대비 · 프로젝트 간 동일인 중복 제외")
            _rings(total, [("검사 참여율", participating, "#087b76"), ("사전검사 완료율", pre, "#16998c"),
                           ("사후검사 완료율", post, "#52bfb2")])
            st.html(f'<div class="tap-dash-insight"><b>아직 참여하지 않은 인원</b><strong>{max(0,total-participating):,}명</strong></div>')
            st.caption("참여: 한 문항 이상 저장한 사람. 모수: 전체 등록 참여자(미배정·사용 중지 포함). 참여 기업: 참여자가 있는 기업.")
        with right, st.container(key=PREFIX + "ranking", border=True):
            if role == "kma":
                st.subheader("기업별 검사 참여율")
                st.caption("모수: 각 기업 전체 등록 참여자 · 미배정 포함")
                companies = list(summary.get("company_participation") or [])
                query = st.text_input("기업 검색", key=PREFIX + "ranking_search", placeholder="회사명으로 검색") if len(companies) > 6 else ""
                matches = [row for row in companies if query.casefold().strip() in str(row.get("company_name") or "").casefold()]
                matches.sort(key=lambda row: (-(_count(row,"participating") / _count(row,"total") if _count(row,"total") else -1), str(row.get("company_name") or "")))
                _ranking([(row.get("company_name") or "회사명 미등록", _count(row,"participating"), _count(row,"total")) for row in matches])
            else:
                st.subheader("프로젝트별 검사 완료 현황")
                st.caption("모수: 프로젝트별 배정 인원 × 사전·사후 2회")
                _ranking([(project["name"], _count(project,"pre_completed") + _count(project,"post_completed"),
                           _count(project,"assigned") * 2) for project in projects], unit="건")
    _render_trend(summary, str(role))
    if not projects:
        st.info("등록된 프로젝트가 없습니다. 프로젝트를 등록하고 참여자를 배정하면 운영 현황이 표시됩니다.")
        return
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    with st.container(key=PREFIX + "schedule", border=True):
        st.subheader("일정·미완료 점검")
        checks = schedule_checks(projects, today)
        st.caption(f"{today.isoformat()} 기준 · 진행 중·마감된 미완료 검사와 7일 이내 시작 일정")
        if checks:
            frame = pd.DataFrame(checks[:10])
            if role == "company":
                frame = frame.drop(columns=["회사"])
            st.dataframe(frame, hide_index=True, width="stretch")
            if len(checks) > 10:
                st.caption(f"점검 항목 {len(checks):,}건 중 10건 표시 · 아래 프로젝트 목록에서 전체 일정을 확인할 수 있습니다.")
        else:
            st.info("현재 확인할 미완료 검사나 임박한 일정이 없습니다.")
    _render_projects(store, token, projects, str(role), today)
