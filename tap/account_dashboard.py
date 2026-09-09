"""Live, tenant-scoped operations overview using one aggregate store read."""
from __future__ import annotations

import logging
from datetime import date, datetime
from math import ceil
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
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
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


def render_dashboard(store: Any, token: str, principal: Mapping[str, Any]) -> None:
    role = principal.get("role")
    if role not in {"kma", "company"} or (role == "company" and not principal.get("company_id")):
        st.error("KMA 관리자 또는 교육담당자 계정으로 로그인해 주세요.")
        return
    st.title("대시보드")
    st.caption("회원사 전체 교육평가 운영 현황입니다." if role == "kma" else
               f"{principal.get('company_name') or '소속 회사'}의 교육평가 운영 현황입니다.")
    try:
        # Authorization and company filtering are enforced by the live store.
        summary = store.dashboard_summary(token)
    except Exception as exc:
        _show_error(exc)
        return
    projects = list(summary.get("projects") or [])
    if role == "company":
        projects = [project for project in projects if project.get("company_id") == principal["company_id"]]
    assigned = sum(_count(project, "assigned") for project in projects)
    pre = sum(_count(project, "pre_completed") for project in projects)
    post = sum(_count(project, "post_completed") for project in projects)
    with st.container(key=PREFIX + "metrics"):
        columns = st.columns(4, gap="small")
        for column, label, value in zip(columns, ("프로젝트", "참여자 계정", "사전검사 완료", "사후검사 완료"),
                                        (len(projects), summary.get("participant_users_count", 0), pre, post)):
            with column:
                st.metric(label, f"{value:,}", border=True)
    scope = f"회원사 {summary.get('companies_count', 0):,}곳 · " if role == "kma" else ""
    st.caption(f"{scope}교육담당자 {summary.get('company_users_count', 0):,}명 · 프로젝트 배정 {assigned:,}건 · 검사 완료는 프로젝트별 합계입니다.")
    if not projects:
        st.info("등록된 프로젝트가 없습니다. 프로젝트를 등록하고 참여자를 배정하면 운영 현황이 표시됩니다.")
        return
    with st.container(key=PREFIX + "stages"):
        st.subheader("단계별 검사 진행률")
        for column, label, completed in zip(st.columns(2, gap="large"), ("사전검사", "사후검사"), (pre, post)):
            with column:
                rate = min(1.0, completed / assigned) if assigned else 0.0
                st.progress(rate, text=f"{label} {rate:.0%}")
                st.caption(f"완료 {completed:,} / 배정 {assigned:,}건 · 미완료 {max(0, assigned - completed):,}건")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    st.subheader("일정·미완료 점검")
    checks = schedule_checks(projects, today)
    st.caption(f"{today.isoformat()} 한국시간 기준 · 진행 중·마감된 미완료 검사와 7일 이내 시작 일정을 표시합니다.")
    if checks:
        frame = pd.DataFrame(checks[:10])
        if role == "company":
            frame = frame.drop(columns=["회사"])
        st.dataframe(frame, hide_index=True, use_container_width=True)
        if len(checks) > 10:
            st.caption(f"점검 항목 {len(checks):,}건 중 10건 표시 · 아래 프로젝트 목록에서 전체 일정을 확인할 수 있습니다.")
    else:
        st.info("현재 확인할 미완료 검사나 임박한 일정이 없습니다.")
    _render_projects(store, token, projects, str(role), today)
