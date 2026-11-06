"""KMA monthly review of access records (개인정보의 안전성 확보조치 기준 제8조).

Staff sign-ins, personal report reads and report downloads are written by
AccountStore; this screen lists one month at a time so the monthly check and
the reason check for downloads can be done and kept as CSV.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from tap.account_ui_kit import foot, section, stat_tiles


SEOUL = ZoneInfo("Asia/Seoul")
PREFIX = "access_log_"
EVENT_LABELS = {
    "login": "로그인",
    "view_individual_report": "개인 리포트 열람",
    "download_individual_pdf": "개인 리포트 PDF 내려받기",
    "download_organization_pdf": "조직 리포트 PDF 내려받기",
    "purge_assessments": "보관 기간 만료 응답 파기",
    "privacy_consent": "참여자 개인정보 동의",
    "create_user": "계정 발급",
    "reset_password": "비밀번호 재발급",
    "change_password": "비밀번호 변경",
    "activate_user": "계정 사용 상태 변경",
    "create_company": "회원사 등록",
    "set_company_registration_number": "사업자등록번호 입력",
    "create_project": "프로젝트 만들기",
    "assign_participant": "참여자 배정",
    "activate_assignment": "배정 상태 변경",
    "submit_pre": "교육 전 검사 제출",
    "submit_post": "교육 후 검사 제출",
    "save_question_text": "문항 문구 수정",
    "bootstrap_admin": "최초 관리자 생성",
}
ROLE_LABELS = {"kma": "KMA 관리자", "company": "교육담당자", "participant": "참여자"}
DOWNLOAD_EVENTS = {"download_individual_pdf", "download_organization_pdf"}


def client_address() -> str:
    """The caller's address as Cloud Run passes it on (first X-Forwarded-For hop)."""
    try:
        forwarded = st.context.headers.get("X-Forwarded-For") or ""
        return forwarded.split(",")[0].strip() or (st.context.ip_address or "")
    except Exception:
        return ""


def _month_bounds(month: date) -> tuple[float, float]:
    start = datetime(month.year, month.month, 1, tzinfo=SEOUL)
    end = datetime(month.year + (month.month == 12), month.month % 12 + 1, 1, tzinfo=SEOUL)
    return start.timestamp(), end.timestamp()


def _months(today: date, count: int = 13) -> list[date]:
    months, year, month = [], today.year, today.month
    for _ in range(count):
        months.append(date(year, month, 1))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return months


def event_rows(events: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for event in events:
        target = " · ".join(part for part in (event.get("target_name"), event.get("target_login")) if part)
        if event["event"] == "purge_assessments":
            target = f"응답 {event.get('count') or 0}건"
        rows.append({
            "일시": datetime.fromtimestamp(float(event["created_at"]), SEOUL).strftime("%Y-%m-%d %H:%M:%S"),
            "계정": " · ".join(part for part in (event.get("actor_name"), event.get("actor_login")) if part) or "시스템",
            "역할": ROLE_LABELS.get(event.get("actor_role") or "", ""),
            "회사": event.get("company_name") or "",
            "행위": EVENT_LABELS.get(event["event"], event["event"]),
            "대상": target,
            "프로젝트": event.get("project_name") or "",
            "접속 IP": event.get("ip") or "",
        })
    return rows


def render_access_log(store: Any, token: str) -> None:
    today = datetime.now(SEOUL).date()
    st.title("접속 기록")
    st.caption("교육담당자·KMA 관리자의 개인정보 처리 기록")
    with section("access_log", "manage_search", "접속 기록 점검",
                 "로그인, 개인 리포트 열람, 리포트 내려받기와 계정·배정 변경 기록. 매월 1회 점검하고 1년 이상 보관"):
        month = st.selectbox("점검할 달", _months(today), format_func=lambda value: value.strftime("%Y년 %m월"),
                             key=PREFIX + "month")
        events = store.access_events(token, *_month_bounds(month))
        counts = {name: sum(event["event"] == name for event in events) for name in EVENT_LABELS}
        st.html(stat_tiles([
            ("로그인", str(counts["login"]), "건", None, False),
            ("개인 리포트 열람", str(counts["view_individual_report"]), "건", None, False),
            ("PDF 내려받기", str(counts["download_individual_pdf"] + counts["download_organization_pdf"]), "건", None,
             bool(counts["download_individual_pdf"])),
        ]))
        if not events:
            st.info("이 달에 남은 기록이 없습니다.")
            return
        rows = event_rows(events)
        downloads_only = st.toggle("내려받기 기록만 보기", key=PREFIX + "downloads")
        shown = [row for row, event in zip(rows, events) if not downloads_only or event["event"] in DOWNLOAD_EVENTS]
        st.dataframe(pd.DataFrame(shown), hide_index=True, width="stretch")
        st.download_button("이 달 기록 CSV 내려받기", pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"KMA_TAP_접속기록_{month:%Y%m}.csv", mime="text/csv", on_click="ignore",
                           icon=":material/download:", key=PREFIX + "csv")
        st.html(foot("개인 리포트 PDF 내려받기는 내려받은 사람에게 사유를 확인하고 점검 결과와 함께 보관합니다. "
                     "응답과 점수는 프로젝트의 교육 후 검사 마감일부터 1년이 지나면 자동으로 지웁니다."))
