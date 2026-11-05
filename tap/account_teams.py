"""Departments and job titles of participants: who has none, moving people, and a CSV for many at once.

A department here is a named list the training manager keeps, not a value the account was born with.
Reports group people by it (one department and one job title per person), so it has to be correctable.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Mapping

import streamlit as st

from tap.config import MIN_GROUP_N

FIELDS = {"department": ("부서", 100), "job_title": ("직급", 80)}
UNASSIGNED = {"department": "부서 미지정", "job_title": "직급 미지정"}
ROSTER_HEADERS = ("아이디", "이름", "상태", "부서", "직급")
MAX_ROSTER_BYTES = 256 * 1024
# AccountStore.set_profiles takes this many accounts in one transaction.
BATCH = 200
PREFIX = "account_teams_"


def participants_of(users: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in users if row.get("role") == "participant"]


def _value(row: Mapping[str, Any], field: str) -> str:
    return str(row.get(field) or "").strip()


def team_counts(users: list[Mapping[str, Any]], field: str = "department") -> list[tuple[str, int]]:
    """(name, people) per department or job title, largest first; people without one are not a group."""
    counts: dict[str, int] = {}
    for row in participants_of(users):
        if name := _value(row, field):
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _cell(value: Any) -> str:
    """Spreadsheets run a cell that starts like a formula; a leading apostrophe keeps it text."""
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text


def roster_csv(users: list[Mapping[str, Any]]) -> bytes:
    """Everyone with their department and job title, to fill in and upload again. People without a department come first."""
    people = sorted(participants_of(users), key=lambda row: (bool(_value(row, "department")), str(row.get("display_name") or ""),
                                                             str(row.get("login_id") or "")))
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(ROSTER_HEADERS)
    for row in people:
        writer.writerow([_cell(row.get("login_id") or ""), _cell(row.get("display_name") or ""),
                         "지정됨" if _value(row, "department") else UNASSIGNED["department"],
                         _cell(_value(row, "department")), _cell(_value(row, "job_title"))])
    return output.getvalue().encode("utf-8-sig")


def plan_roster(content: bytes, users: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Read a filled-in roster and say what applying it would change. Nothing is written here.

    People are found by login ID, so a shared name cannot mix two people up. A row the file leaves out is
    not touched; an empty department or job-title cell clears it. A row that cannot be applied is listed in
    "excluded" with the reason and the rest still goes through.

    Returns {"changes": [{"user_id", "department"?, "job_title"?}], "rows": [preview rows],
             "counts": {"new", "assign", "move", "clear", "excluded"}, "excluded": [(who, reason)], "new": [names]}.
    """
    if len(content) > MAX_ROSTER_BYTES:
        raise ValueError("CSV 파일은 256KB 이하로 올려 주세요.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("엑셀에서 ‘CSV UTF-8(쉼표로 분리)’ 형식으로 저장한 파일을 올려 주세요.") from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = [name.strip() for name in reader.fieldnames or []]
        if "아이디" not in headers or not ({"부서", "직급"} & set(headers)) or len(headers) != len(set(headers)):
            raise ValueError("첫 줄에 ‘아이디’와 ‘부서’ 또는 ‘직급’ 열이 있어야 합니다. 명단 받기로 받은 파일을 그대로 채워 주세요.")
        records = [{key.strip(): (value or "") for key, value in record.items() if key is not None} for record in reader]
    except csv.Error as exc:
        raise ValueError("CSV 구분자와 따옴표를 확인해 주세요.") from exc
    by_login = {str(row.get("login_id") or "").lower(): row for row in participants_of(users)}
    known = {field: {name for name, _ in team_counts(users, field)} for field in FIELDS}
    changes, rows, excluded, seen, new_names = [], [], [], set(), []
    counts = {"new": 0, "assign": 0, "move": 0, "clear": 0, "excluded": 0}
    for number, record in enumerate(records, start=2):
        login = record.get("아이디", "").strip().lstrip("'").lower()
        if not login and not any(value.strip() for value in record.values()):
            continue
        label = f"{number}행 {record.get('이름', '').strip() or login or ''}".strip()
        user = by_login.get(login)
        reason = ("아이디가 비어 있습니다" if not login else "등록된 참여자가 아닙니다" if user is None
                  else "같은 아이디가 두 번 있습니다" if login in seen else "")
        change: dict[str, str] = {}
        if not reason:
            seen.add(login)
            for field, (header, limit) in FIELDS.items():
                if header not in record:
                    continue
                value = record[header].strip().lstrip("'").strip()
                if any(mark in value for mark in (",", ";", "\n")):
                    reason = f"{header}가 두 개입니다. 한 사람에 하나만 적어 주세요"
                elif len(value) > limit or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
                    reason = f"{header}는 줄바꿈 없이 {limit}자 이내로 적어 주세요"
                elif value != _value(user, field):
                    change[field] = value
        if reason:
            excluded.append((label, reason))
            counts["excluded"] += 1
            continue
        if not change:
            continue
        for field, value in change.items():
            before = _value(user, field)
            kind = "지정" if not before else "빠짐" if not value else "옮김"
            counts[{"지정": "assign", "빠짐": "clear", "옮김": "move"}[kind]] += 1
            if value and value not in known[field] and value not in new_names:
                new_names.append(value)
                counts["new"] += 1
            rows.append({"이름": str(user.get("display_name") or ""), "아이디": str(user.get("login_id") or ""), "구분": FIELDS[field][0],
                         "지금": before or UNASSIGNED[field], "바뀜": value or UNASSIGNED[field], "처리": kind})
        changes.append({"user_id": str(user["id"]), **change})
    return {"changes": changes, "rows": rows, "counts": counts, "excluded": excluded, "new": new_names}


def apply_changes(store: Any, token: str, changes: list[dict[str, str]]) -> int:
    """Send the changes in the store's batch size. Each batch is all-or-none; a failure stops the rest."""
    return sum(store.set_profiles(token, changes[start:start + BATCH]) for start in range(0, len(changes), BATCH))


def _notice(message: str) -> None:
    st.session_state["account_admin_notice"] = message


def _try(action) -> tuple[bool, Any]:
    from tap.account_admin_ui import _attempt
    return _attempt(action)


def _render_unassigned(store: Any, token: str, people: list[Mapping[str, Any]], departments: list[str]) -> None:
    from tap.account_admin_ui import _identifier, _people_window, _person_label
    missing = [row for row in people if not _value(row, "department")]
    if not missing:
        st.success("모든 참여자에게 부서가 있습니다.")
        return
    with st.container(border=True, key=PREFIX + "unassigned"):
        st.subheader(f"{UNASSIGNED['department']} {len(missing)}명")
        st.caption("부서가 없는 참여자는 리포트의 부서별 비교에서 한 줄로 모입니다. 목록에 없는 부서는 이름을 입력하면 새로 생깁니다.")
        window, pager = _people_window(missing, range_key=PREFIX + "unassigned_range", page_key=PREFIX + "unassigned_page",
                                       name_key="display_name")
        picks: dict[str, str] = {}
        for row in window:
            left, right = st.columns([1.3, 1], vertical_alignment="center")
            with left:
                st.write(_person_label(row))
            with right:
                choice = st.selectbox("부서", departments, index=None, placeholder="부서 선택 또는 입력", accept_new_options=True,
                                      key=PREFIX + "unassigned_pick_" + _identifier(row), label_visibility="collapsed")
            if choice and str(choice).strip():
                picks[_identifier(row)] = str(choice).strip()
        pager()
        if st.button(f"고른 {len(picks)}명 부서 지정", disabled=not picks, type="primary", key=PREFIX + "unassigned_save"):
            ok, count = _try(lambda: apply_changes(store, token, [{"user_id": user_id, "department": name} for user_id, name in picks.items()]))
            if ok:
                _notice(f"{count}명의 부서를 지정했습니다.")
                st.rerun()


def _render_overview(people: list[Mapping[str, Any]]) -> None:
    basis = st.segmented_control("구분", list(FIELDS), format_func=lambda field: f"{FIELDS[field][0]} {len(team_counts(people, field))}",
                                 default="department", key=PREFIX + "basis", label_visibility="collapsed") or "department"
    groups = team_counts(people, basis)
    if not groups:
        st.info(f"아직 등록된 {FIELDS[basis][0]}가 없습니다. 아래에서 사람을 골라 지정하거나 CSV로 한 번에 지정하세요.")
        return
    st.dataframe([{FIELDS[basis][0]: name, "인원": count,
                   "리포트 비교": "공개 가능" if count >= MIN_GROUP_N else f"{MIN_GROUP_N}명 미만 · 비공개"} for name, count in groups],
                 hide_index=True, width="stretch", height=min(420, 38 + 35 * len(groups)))
    st.caption(f"리포트의 {FIELDS[basis][0]}별 비교는 교육 전후 검사를 모두 마친 사람이 {MIN_GROUP_N}명 이상인 {FIELDS[basis][0]}만 숫자를 보여 줍니다. "
               "한 사람은 부서 하나, 직급 하나에만 속합니다.")


def _render_move(store: Any, token: str, people: list[Mapping[str, Any]], departments: list[str], titles: list[str]) -> None:
    from tap.account_admin_ui import _bulk_pick
    with st.expander("부서 · 직급 바꾸기", key=PREFIX + "move", on_change="rerun"):
        st.caption("부서를 통째로 고르면 부서 이름을 바꾸거나 합칠 수 있습니다. 한 명씩 옮길 때는 검색해서 고르세요.")
        selected = _bulk_pick(people, PREFIX + "move_pick", search_key=PREFIX + "move_search", search_label="참여자 검색", unit_label="참여자")
        left, right = st.columns(2)
        with left:
            department = st.selectbox("옮길 부서", departments, index=None, placeholder="바꾸지 않음", accept_new_options=True,
                                      key=PREFIX + "move_department", help="목록에 없는 이름을 입력하면 새 부서가 됩니다.")
        with right:
            title = st.selectbox("바꿀 직급", titles, index=None, placeholder="바꾸지 않음", accept_new_options=True,
                                 key=PREFIX + "move_title", help="목록에 없는 이름을 입력하면 새 직급이 됩니다.")
        target = {field: str(value).strip() for field, value in (("department", department), ("job_title", title)) if value and str(value).strip()}
        st.caption("교육 후 검사를 이미 마친 프로젝트의 리포트는 바뀌지 않습니다. 리포트는 검사를 마친 시점의 소속으로 묶습니다.")
        if st.button(f"고른 {len(selected)}명 적용", disabled=not (selected and target), type="primary", key=PREFIX + "move_save"):
            ok, count = _try(lambda: apply_changes(store, token, [{"user_id": user_id, **target} for user_id in selected]))
            if ok:
                _notice(f"{count}명의 소속을 바꿨습니다." if count else "바뀐 사람이 없습니다. 이미 같은 소속입니다.")
                st.rerun()


def _render_roster(store: Any, token: str, people: list[Mapping[str, Any]]) -> None:
    with st.expander("CSV로 한 번에 지정", key=PREFIX + "roster", on_change="rerun"):
        st.caption("명단을 받아 부서와 직급 칸만 채워서 올립니다. 아이디로 찾기 때문에 이름이 같아도 섞이지 않습니다. "
                   "칸을 비우면 그 소속에서 빠지고, 파일에 없는 사람은 그대로 둡니다.")
        st.download_button(f"참여자 명단 받기 ({len(people)}명)", roster_csv(people), "tap_부서지정_명단.csv", "text/csv",
                           icon=":material/download:", key=PREFIX + "roster_download")
        upload = st.file_uploader("채운 명단 CSV", type=["csv"], key=PREFIX + "roster_upload")
        if upload is None:
            return
        try:
            plan = plan_roster(upload.getvalue(), people)
        except ValueError as exc:
            st.error(str(exc))
            return
        counts = plan["counts"]
        columns = st.columns(5)
        for column, (label, key) in zip(columns, (("새 부서 · 직급", "new"), ("지정", "assign"), ("옮김", "move"), ("빠짐", "clear"), ("제외", "excluded"))):
            column.metric(label, counts[key])
        if plan["new"]:
            st.caption("새로 생기는 이름: " + ", ".join(plan["new"]))
        if plan["rows"]:
            st.dataframe(plan["rows"], hide_index=True, width="stretch", height=min(420, 38 + 35 * len(plan["rows"])))
        if plan["excluded"]:
            st.warning("적용하지 않는 줄\n\n" + "\n".join(f"- {label}: {reason}" for label, reason in plan["excluded"]))
        if not plan["changes"]:
            st.info("바뀌는 사람이 없습니다.")
            return
        st.caption("교육 후 검사를 이미 마친 프로젝트의 리포트는 바뀌지 않습니다. 리포트는 검사를 마친 시점의 소속으로 묶습니다.")
        if st.button(f"{len(plan['changes'])}명 적용", type="primary", key=PREFIX + "roster_save"):
            ok, count = _try(lambda: apply_changes(store, token, plan["changes"]))
            if ok:
                _notice(f"{count}명의 소속을 바꿨습니다.")
                st.rerun()


def render_teams(store: Any, token: str, principal: Mapping[str, Any], users: list[dict[str, Any]]) -> None:
    """The training manager's page; AccountStore.set_profiles enforces the company scope on every change."""
    people = [row for row in participants_of(users) if str(row.get("company_id")) == str(principal.get("company_id"))]
    if not people:
        st.info("먼저 참여자 계정을 발급해 주세요. 계정을 만들 때 부서와 직급을 함께 넣을 수도 있습니다.")
        return
    departments = [name for name, _ in team_counts(people, "department")]
    titles = [name for name, _ in team_counts(people, "job_title")]
    st.caption("리포트의 부서별 · 직급별 비교는 여기서 정한 소속으로 묶습니다.")
    _render_unassigned(store, token, people, departments)
    _render_overview(people)
    _render_move(store, token, people, departments, titles)
    _render_roster(store, token, people)
