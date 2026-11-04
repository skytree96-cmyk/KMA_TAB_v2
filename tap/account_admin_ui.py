"""Account and project administration for authenticated production users."""
from __future__ import annotations

import csv
import hashlib
from html import escape
import io
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

import streamlit as st

from tap.data import load_competencies, questions_for_factors
from tap.selection import MAX_JOB_FUNCTION, MAX_SPECIALTY, applicable_to_level, selection_errors


LOGGER = logging.getLogger(__name__)
PREFIX = "account_admin_"
ROLE_LABELS = {"kma": "KMA 관리자", "company": "교육담당자", "participant": "참여자"}
LEVEL_LABELS = {"staff": "실무자", "manager": "관리자·리더", "executive": "임원"}
MAX_BATCH_ROWS = 200
WORKSPACE_PAGE_SIZE = 12
WORKSPACE_SECTIONS = {
    "kma": {"companies": "회원사", "accounts": "계정 관리", "projects": "프로젝트"},
    "company": {"accounts": "참여자 계정", "create_project": "프로젝트 만들기", "projects": "프로젝트"},
}
MAX_CSV_BYTES = 256 * 1024
PROFILE_FIELDS = {"department": ("부서", 100), "job_title": ("직급", 80), "email": ("이메일", 254), "phone": ("연락처", 40)}
# Customers see Korean headers; the original English headers stay accepted for files made earlier.
CSV_HEADER_ALIASES = {"아이디": "login_id", "이름": "display_name", **{label: key for key, (label, _) in PROFILE_FIELDS.items()}}
CSV_TEMPLATE = "\ufeff아이디,이름,부서,직급,이메일,연락처\nuser001,참여자1,,,,\nuser002,참여자2,,,,\n"


def _identifier(row: Mapping[str, Any]) -> str:
    return str(row.get("id") or row.get("project_id") or row.get("user_id") or "")


def _safe_error(exc: Exception) -> str:
    messages = {
        "AuthenticationError": "로그인 시간이 만료되었습니다. 다시 로그인해 주세요.",
        "AuthorizationError": "이 작업을 수행할 권한이 없습니다. 계정의 회사와 역할을 확인해 주세요.",
        "ConflictError": "이미 등록된 아이디 또는 사업자등록번호입니다. 기존 목록을 확인해 주세요.",
        "ValidationError": "입력 형식 또는 검사 일정을 확인해 주세요. 저장되지 않았습니다.",
        "RateLimitError": "잠시 후 다시 시도해 주세요. 요청이 일시적으로 많습니다.",
    }
    return messages.get(type(exc).__name__, "처리하지 못했습니다. 잠시 후 다시 시도하거나 KMA 관리자에게 문의해 주세요.")


def _attempt(action: Callable[[], Any]) -> tuple[bool, Any]:
    try:
        return True, action()
    except Exception as exc:
        LOGGER.error("Account administration operation failed: %s", type(exc).__name__)
        st.error(_safe_error(exc))
        return False, None


def _notice(message: str) -> None:
    st.session_state[PREFIX + "notice"] = message


def _josa(word: str, with_final: str, without_final: str) -> str:
    """Attach the particle that matches the word's last syllable (회원사가, 프로젝트가, 직급은)."""
    last = word[-1:]
    has_final = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return word + (with_final if has_final else without_final)


def _login_id(value: str, company_prefix: str | None = None) -> str:
    value = value.strip().lower()
    if not value:
        raise ValueError("아이디를 입력해 주세요.")
    if company_prefix:
        company_prefix = company_prefix.strip().lower()
        if re.fullmatch(r"user[0-9]*", value):
            value = f"{company_prefix}-{value}"
        if value == company_prefix + "-":
            raise ValueError("회사 식별정보 뒤에 사용할 아이디를 입력해 주세요.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", value):
        raise ValueError("아이디는 영문 소문자나 숫자로 시작하는 3~64자로 입력해 주세요. 영문 소문자, 숫자, 점, 밑줄과 하이픈만 쓸 수 있습니다.")
    return value


def _registration_number(value: str) -> str:
    if not re.fullmatch(r"[0-9]{10}", value):
        raise ValueError("사업자등록번호는 하이픈 없이 0~9 숫자 10자리로 입력해 주세요.")
    return value


def _company_registration_label(company: Mapping[str, Any]) -> str:
    value = str(company.get("registration_number", company.get("slug", "")))
    return value if re.fullmatch(r"[0-9]{10}", value) else "미등록"


def _display_name(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 80 or any(ord(char) < 32 for char in value):
        raise ValueError("이름은 줄바꿈 없이 1~80자로 입력해 주세요.")
    return value


def _participant_profile(values: Mapping[str, Any]) -> dict[str, str]:
    profile: dict[str, str] = {}
    for key, (label, limit) in PROFILE_FIELDS.items():
        raw_value = str(values.get(key) or "")
        value = raw_value.strip()
        if len(value) > limit or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in raw_value):
            raise ValueError(f"{_josa(label, '은', '는')} 줄바꿈 없이 {limit}자 이내로 입력해 주세요.")
        profile[key] = value
    if profile["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", profile["email"]):
        raise ValueError("이메일 형식을 확인해 주세요. 예: name@example.com")
    phone = profile["phone"]
    if phone and (not re.fullmatch(r"\+?[0-9][0-9 ().-]*", phone) or not 5 <= len(re.findall(r"[0-9]", phone)) <= 20):
        raise ValueError("연락처는 5~20개의 숫자와 +, 공백, 괄호, 하이픈, 점으로 입력해 주세요.")
    return profile


def parse_participant_csv(content: bytes, company_prefix: str) -> list[dict[str, str]]:
    """Validate a batch completely before the first account is created."""
    if len(content) > MAX_CSV_BYTES:
        raise ValueError("CSV 파일은 256KB 이하로 올려 주세요.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("엑셀에서 ‘CSV UTF-8(쉼표로 분리)’ 형식으로 저장한 파일을 올려 주세요.") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    try:
        fields = [CSV_HEADER_ALIASES.get(name.strip(), name.strip()) for name in reader.fieldnames or []]
        reader.fieldnames = fields
        if fields[:2] != ["login_id", "display_name"] or len(fields) != len(set(fields)) or not set(fields[2:]).issubset(PROFILE_FIELDS):
            raise ValueError("첫 두 열은 아이디, 이름이어야 합니다. 그 뒤에는 부서, 직급, 이메일, 연락처 열만 쓸 수 있습니다. 아래 양식을 내려받아 사용해 주세요.")
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{number}행의 열 개수를 확인해 주세요.")
            if not any(str(value or "").strip() for value in row.values()):
                continue
            try:
                login_id = _login_id(str(row.get("login_id") or ""), company_prefix)
                name = _display_name(str(row.get("display_name") or ""))
                profile = _participant_profile(row)
            except ValueError as exc:
                raise ValueError(f"{number}행: {exc}") from exc
            if login_id in seen:
                raise ValueError(f"{number}행: CSV 안에 같은 아이디가 두 번 있습니다.")
            rows.append({"login_id": login_id, "display_name": name, **profile})
            seen.add(login_id)
            if len(rows) > MAX_BATCH_ROWS:
                raise ValueError(f"한 번에 최대 {MAX_BATCH_ROWS}명까지 등록할 수 있습니다.")
    except csv.Error as exc:
        raise ValueError("CSV 구분자와 따옴표를 확인해 주세요.") from exc
    if not rows:
        raise ValueError("등록할 참여자를 한 명 이상 입력해 주세요.")
    return rows


def _csv_cell(value: Any) -> str:
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text


def credentials_csv(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["로그인 아이디", "이름", "임시 비밀번호"])
    for row in rows:
        writer.writerow([_csv_cell(row[key]) for key in ("login_id", "display_name", "temp_password")])
    return output.getvalue().encode("utf-8-sig")


def _temporary_password(role: str) -> str:
    # Only these two account roles use the explicitly requested initial password.
    # KMA administrator passwords are managed outside this UI.
    if role not in {"company", "participant"}:
        raise ValueError("교육담당자와 참여자 계정만 임시 비밀번호를 발급할 수 있습니다.")
    return "kma"


def _remember_credentials(rows: list[dict[str, str]], principal: Mapping[str, Any]) -> None:
    previous = st.session_state.get(PREFIX + "credentials", {})
    owner = _identifier(principal)
    kept = previous.get("rows", []) if previous.get("owner") == owner else []
    by_login = {row["login_id"]: row for row in kept}
    by_login.update({row["login_id"]: row for row in rows})
    st.session_state[PREFIX + "credentials"] = {"owner": owner, "rows": list(by_login.values())}


def _render_credentials(principal: Mapping[str, Any]) -> None:
    data = st.session_state.get(PREFIX + "credentials")
    if not data:
        return
    if data.get("owner") != _identifier(principal):
        st.session_state.pop(PREFIX + "credentials", None)
        return
    rows = data["rows"]
    with st.container(border=True, key=PREFIX + "credentials_panel"):
        st.subheader("발급한 로그인 정보")
        st.info("임시 비밀번호는 이 화면에서만 확인할 수 있습니다. 내려받아 사용자에게 전달한 뒤 닫아 주세요. 사용자는 첫 로그인 때 비밀번호를 바꿉니다.")
        st.dataframe([
            {"로그인 아이디": row["login_id"], "이름": row["display_name"], "임시 비밀번호": row["temp_password"]}
            for row in rows
        ], hide_index=True, width="stretch")
        st.download_button("로그인 정보 CSV 내려받기", credentials_csv(rows), "tap_initial_accounts.csv", "text/csv", key=PREFIX + "credentials_download")
        st.button(
            "전달 완료 · 발급 정보 닫기", key=PREFIX + "credentials_clear",
            on_click=lambda: st.session_state.pop(PREFIX + "credentials", None),
        )


def build_project_config(
    name: str, course_name: str, target_level: str, optional_factors: list[str],
    training_date: date, pre_start: date, pre_end: date, post_start: date, post_end: date,
    target_mean: float = 3.5, priorities: list[str] | None = None, delivery: str = "all",
) -> dict[str, Any]:
    if not name.strip() or not course_name.strip():
        raise ValueError("프로젝트명과 교육과정명을 입력해 주세요.")
    if target_level not in LEVEL_LABELS:
        raise ValueError("응답 대상을 선택해 주세요.")
    if pre_end < pre_start or post_end < post_start:
        raise ValueError("검사 마감일은 시작일보다 빠를 수 없습니다.")
    if pre_end > training_date or post_start < training_date:
        raise ValueError("교육 전 검사 마감일은 교육일과 같거나 빨라야 하며, 교육 후 검사 시작일은 교육일과 같거나 늦어야 합니다.")
    rows = load_competencies()
    available = {row["factor_code"]: row for row in rows if row["active_for_scoring"] and applicable_to_level(row, target_level)}
    optional_factors = list(dict.fromkeys(optional_factors))
    if any(code not in available or available[code]["library_type"] not in {"specialty", "job_function"} for code in optional_factors):
        raise ValueError("응답 대상에 적용할 수 있는 선택역량을 골라 주세요.")
    errors = selection_errors(optional_factors, rows)
    if errors:
        raise ValueError(" ".join(errors))
    selected = [code for code, row in available.items() if row["library_type"] == "base"] + optional_factors
    if not 1 <= target_mean <= 5:
        raise ValueError("조직 기대 행동빈도는 1~5 사이여야 합니다.")
    priorities = list(dict.fromkeys(priorities or []))
    if len(priorities) > 3 or not set(priorities).issubset(selected):
        raise ValueError("조직 우선역량은 측정역량 중 최대 3개까지 골라 주세요.")
    questions = sorted(questions_for_factors(selected), key=lambda row: hashlib.sha256(f"{name.strip()}|{row['question_code']}".encode("utf-8")).hexdigest())
    if not questions:
        raise ValueError("측정할 문항이 없습니다. 역량 선택을 확인해 주세요.")
    snapshot_rows = sorted(
        (str(row["question_code"]), str(row["revised_text"]), str(row.get("scoring_direction", "direct")))
        for row in questions
    )
    snapshot = "\n".join("|".join(parts) for parts in snapshot_rows)
    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    return {
        "project_name": name.strip(), "course_name": course_name.strip(), "target_level": target_level,
        "training_date": training_date.isoformat(), "pre_start_date": pre_start.isoformat(), "pre_end_date": pre_end.isoformat(),
        "post_start_date": post_start.isoformat(), "post_end_date": post_end.isoformat(),
        "project_start_date": pre_start.isoformat(), "project_end_date": pre_end.isoformat(),
        "selected_factors": selected, "target_means": {code: target_mean for code in selected},
        "organization_priorities": priorities, "learner_interests": [], "training_cause": "mixed_or_unknown",
        "delivery_preference": delivery if delivery in {"all", "offline", "online"} else "all",
        "allow_schedule_override": False, "question_snapshot_codes": [str(row["question_code"]) for row in questions],
        "question_snapshot_hash": digest, "assessment_version": f"TAP-1.0+{digest[:12]}",
    }


def _render_companies(store: Any, token: str, companies: list[dict[str, Any]], *, show_heading: bool = True) -> None:
    if show_heading:
        st.subheader("회원사")
    if companies:
        st.dataframe([{"회사명": row["name"], "사업자등록번호": _company_registration_label(row), "상태": "사용 중" if row.get("active", True) else "중지"} for row in companies], hide_index=True, width="stretch")
    else:
        st.info("등록된 회원사가 없습니다. 먼저 회사를 등록해 주세요.")
    with st.form(PREFIX + "company_create", clear_on_submit=True):
        name = st.text_input("회사명", max_chars=120)
        registration_input = st.text_input("사업자등록번호", help="하이픈 없이 숫자 10자리를 입력합니다. 맨 앞의 0도 그대로 입력해 주세요.", max_chars=20)
        if st.form_submit_button("회사 등록", type="primary"):
            try:
                if not name.strip():
                    raise ValueError("회사명을 입력해 주세요.")
                registration_number = _registration_number(registration_input)
            except ValueError as exc:
                st.error(str(exc))
            else:
                ok, _ = _attempt(lambda: store.create_company(token, name.strip(), registration_number))
                if ok:
                    _notice("회사를 등록했습니다. 교육담당자 계정을 발급할 수 있습니다.")
                    st.rerun()
    if not companies:
        return
    st.subheader("사업자등록번호 등록·수정")
    st.caption("미등록 회사의 번호를 보완하거나 등록된 번호를 수정할 수 있습니다.")
    company = _company_pick(companies, PREFIX + "registration_company_pick", "사업자등록번호를 변경할 회사 검색")
    if company is None:
        return
    selected = _identifier(company)
    current_number = _company_registration_label(company)
    with st.form(PREFIX + "registration_update_" + selected):
        registration_input = st.text_input("등록할 사업자등록번호", value="" if current_number == "미등록" else current_number, help="하이픈 없이 0~9 숫자 10자리로 입력해 주세요.", max_chars=20, key=PREFIX + "registration_value_" + selected)
        if st.form_submit_button("사업자등록번호 저장"):
            try:
                registration_number = _registration_number(registration_input)
            except ValueError as exc:
                st.error(str(exc))
            else:
                ok, _ = _attempt(lambda: store.set_company_registration_number(token, selected, registration_number))
                if ok:
                    _notice("사업자등록번호를 저장했습니다.")
                    st.rerun()


def _render_create_user(store: Any, token: str, principal: Mapping[str, Any], company: Mapping[str, Any], role: str,
                        *, show_heading: bool = True) -> None:
    if role not in {"company", "participant"}:
        st.error("교육담당자 또는 참여자 계정만 발급할 수 있습니다.")
        return
    label = ROLE_LABELS[role]
    if show_heading:
        st.subheader(f"{label} 계정 발급")
    st.caption(f"회사: {company['name']} · 사업자등록번호: {_company_registration_label(company)}")
    if role == "participant":
        st.caption(f"user 또는 user001처럼 user 뒤에 숫자만 붙인 기본 예시 아이디에는 회사 식별정보 {company['slug']}-가 자동으로 붙습니다. 직접 정한 아이디와 회사 식별정보가 이미 붙은 아이디는 그대로 사용합니다.")
    else:
        st.caption("교육담당자는 입력한 아이디로 로그인합니다. 아이디는 전체 회원사에서 중복 없이 사용합니다.")
    st.caption("영문 대문자는 소문자로 저장됩니다. 로그인에는 이메일을 사용하지 않습니다.")
    st.info(f"{label}의 임시 비밀번호는 kma로 자동 발급됩니다. 첫 로그인 때 새 비밀번호로 변경해야 합니다.")
    with st.form(PREFIX + f"user_create_{role}_{_identifier(company)}", clear_on_submit=True):
        login_input = st.text_input("아이디", max_chars=80, placeholder="예: user001", help="영문 소문자, 숫자, 점, 밑줄과 하이픈을 쓸 수 있습니다. 완성된 로그인 아이디는 3~64자이며, 영문 소문자 또는 숫자로 시작해야 합니다.")
        name = st.text_input("이름", max_chars=80)
        profile_input: dict[str, str] = {}
        if role == "participant":
            st.caption("부서, 직급, 이메일과 연락처는 선택 입력입니다.")
            left, right = st.columns(2)
            with left:
                profile_input["department"] = st.text_input("부서", max_chars=100)
                profile_input["email"] = st.text_input("이메일", max_chars=254, placeholder="예: name@example.com")
            with right:
                profile_input["job_title"] = st.text_input("직급", max_chars=80)
                profile_input["phone"] = st.text_input("연락처", max_chars=40, placeholder="예: 010-1234-5678")
        submitted = st.form_submit_button(f"{label} 계정 발급", type="primary")
    if submitted:
        try:
            login_id, display_name = _login_id(login_input, str(company["slug"]) if role == "participant" else None), _display_name(name)
            profile = _participant_profile(profile_input) if role == "participant" else None
        except ValueError as exc:
            st.error(str(exc))
        else:
            password = _temporary_password(role)
            ok, _ = _attempt(lambda: store.create_user(token, login_id, display_name, role, _identifier(company), password, profile=profile))
            if ok:
                _remember_credentials([{"login_id": login_id, "display_name": display_name, "temp_password": password}], principal)
                _notice(f"{label} 계정을 발급했습니다.")
                st.rerun()


def _render_batch(store: Any, token: str, principal: Mapping[str, Any], company: Mapping[str, Any], users: list[dict[str, Any]],
                  projects: list[dict[str, Any]] | None = None) -> None:
    with st.expander("CSV로 참여자 일괄 등록", key=PREFIX + f"batch_expander_{_identifier(company)}", on_change="rerun"):
        st.caption(f"한 번에 최대 {MAX_BATCH_ROWS}명까지 등록합니다. 아이디와 이름은 필수이고 부서, 직급, 이메일과 연락처는 선택입니다. 아이디·이름 2열로 된 기존 양식도 쓸 수 있습니다. 아이디 규칙과 임시 비밀번호(kma)는 한 명씩 발급할 때와 같습니다.")
        st.download_button("CSV 양식 내려받기", CSV_TEMPLATE.encode("utf-8"), "tap_participants_template.csv", "text/csv", key=PREFIX + "batch_template")
        upload = st.file_uploader("참여자 CSV", type=["csv"], key=PREFIX + "batch_upload")
        if upload is None:
            return
        try:
            rows = parse_participant_csv(upload.getvalue(), str(company["slug"]))
        except ValueError as exc:
            st.error(str(exc))
            return
        existing = {str(row["login_id"]).lower(): row for row in users}
        duplicate_count = sum(row["login_id"] in existing for row in rows)
        st.dataframe([{"로그인 아이디": row["login_id"], "이름": row["display_name"], **{label: row.get(key, "") for key, (label, _) in PROFILE_FIELDS.items()}, "등록": "기존 계정 · 제외" if row["login_id"] in existing else "새 계정"} for row in rows], hide_index=True, width="stretch")
        pending = [row for row in rows if row["login_id"] not in existing]
        if duplicate_count:
            st.info(f"이미 등록된 {duplicate_count}개 계정은 변경하지 않습니다.")
        projects_by_id = {_identifier(row): row for row in projects or [] if str(row.get("company_id")) == _identifier(company)}
        project_id = st.selectbox(
            "등록하면서 배정할 프로젝트", list(projects_by_id), index=None, placeholder="배정하지 않음",
            format_func=lambda value: str(projects_by_id[value].get("name") or projects_by_id[value].get("project_name") or "교육평가 프로젝트"),
            key=PREFIX + "batch_project", help="고르면 CSV의 참여자 전원(이미 등록된 계정 포함)을 이 프로젝트에 함께 배정합니다.",
        ) if projects_by_id else None
        # Existing accounts listed in the CSV are assigned too; inactive ones cannot be.
        existing_ids = [_identifier(existing[row["login_id"]]) for row in rows
                        if row["login_id"] in existing and existing[row["login_id"]].get("active", True)
                        and existing[row["login_id"]].get("role") == "participant"] if project_id else []
        if pending and project_id:
            label = f"새 참여자 {len(pending)}명 등록 후 {len(pending) + len(existing_ids)}명 배정"
        elif project_id:
            label = f"기존 참여자 {len(existing_ids)}명 배정"
        else:
            label = f"새 참여자 {len(pending)}명 등록"
        if st.button(label, disabled=not (pending or existing_ids), key=PREFIX + "batch_create", type="primary"):
            password = _temporary_password("participant")
            with st.spinner("참여자 계정을 처리하는 중입니다."):
                try:
                    # One transaction: either every row is saved or none is.
                    if pending:
                        store.create_users(token, "participant", _identifier(company), pending, password,
                                           project_id=project_id, existing_user_ids=existing_ids)
                    else:
                        store.assign_participants(token, project_id, existing_ids)
                except Exception as exc:
                    LOGGER.error("Participant batch failed: %s", type(exc).__name__)
                    detail = str(exc) if type(exc).__name__ == "ConflictError" and str(exc).startswith("이미 사용 중인 아이디") else ""
                    st.error(f"{detail}. 아무 계정도 등록하지 않았습니다. 아이디를 바꿔 다시 올려 주세요." if detail else _safe_error(exc) + " 아무 계정도 등록하지 않았습니다.")
                    return
            _remember_credentials([{"login_id": row["login_id"], "display_name": row["display_name"], "temp_password": password} for row in pending], principal)
            assigned_count = len(pending) + len(existing_ids)
            if pending and project_id:
                _notice(f"참여자 {len(pending)}명 계정을 발급하고 {assigned_count}명을 프로젝트에 배정했습니다.")
            elif project_id:
                _notice(f"{assigned_count}명을 프로젝트에 배정했습니다.")
            else:
                _notice(f"참여자 {len(pending)}명 계정을 발급했습니다.")
            st.rerun()


def _render_manage_users(store: Any, token: str, principal: Mapping[str, Any], users: list[dict[str, Any]]) -> None:
    st.subheader("계정 관리")
    allowed = [row for row in users if row.get("role") in {"company", "participant"} and _identifier(row) != _identifier(principal)]
    if principal.get("role") == "company":
        allowed = [row for row in allowed if row.get("role") == "participant" and row.get("company_id") == principal.get("company_id")]
    selection_key = PREFIX + "manage_user"
    if not allowed:
        st.session_state[selection_key] = None
        st.info("관리할 계정이 없습니다.")
        return
    query = st.text_input(
        "계정 검색", key=PREFIX + "manage_user_search",
        placeholder="이름, 아이디, 회사명으로 검색",
        help="일부 글자로 검색할 수 있습니다. 영문 대소문자는 구분하지 않습니다.",
    ).strip().casefold()
    matched = [row for row in allowed if not query or any(
        query in str(row.get(field) or "").casefold()
        for field in ("display_name", "login_id", "company_name")
    )]
    by_id = {_identifier(row): row for row in matched}
    # A search must not silently change the target of reset/deactivation actions.
    if st.session_state.get(selection_key) not in by_id:
        st.session_state[selection_key] = None
    st.caption(f"검색 결과 {len(matched)}명 · 전체 {len(allowed)}명")
    if not matched:
        st.info("검색 결과가 없습니다. 이름, 아이디 또는 회사명을 다시 입력해 주세요.")
        return
    st.dataframe([{"로그인 아이디": row["login_id"], "이름": row.get("display_name", ""), "역할": ROLE_LABELS.get(row["role"], ""), "회사": row.get("company_name", ""), **{label: row.get(key, "") for key, (label, _) in PROFILE_FIELDS.items()}, "상태": "사용 중" if row.get("active", True) else "중지"} for row in matched], hide_index=True, width="stretch")
    selected = st.selectbox(
        "관리할 계정", list(by_id),
        format_func=lambda value: " · ".join(str(by_id[value].get(field) or "") for field in ("display_name", "login_id", "company_name") if by_id[value].get(field)),
        key=selection_key, index=None, placeholder="관리할 계정을 선택하세요",
    )
    if selected is None:
        return
    user = by_id[selected]
    _render_user_actions(store, token, principal, user)


def _render_user_actions(store: Any, token: str, principal: Mapping[str, Any], user: Mapping[str, Any]) -> None:
    selected = _identifier(user)
    st.caption("임시 비밀번호를 kma로 재발급합니다. 다시 로그인할 때 새 비밀번호로 변경해야 합니다.")
    left, right = st.columns(2)
    with left:
        if st.button("임시 비밀번호 재발급", key=PREFIX + "password_reset"):
            password = _temporary_password(str(user["role"]))
            ok, _ = _attempt(lambda: store.reset_password(token, selected, password))
            if ok:
                _remember_credentials([{"login_id": str(user["login_id"]), "display_name": str(user["display_name"]), "temp_password": password}], principal)
                _notice("새 임시 비밀번호를 발급했습니다. 해당 사용자는 다시 로그인해야 합니다.")
                st.rerun()
    with right:
        active = bool(user.get("active", True))
        if st.button("계정 사용 중지" if active else "계정 다시 활성화", key=PREFIX + "toggle_active"):
            ok, _ = _attempt(lambda: store.set_user_active(token, selected, not active))
            if ok:
                _notice("계정 사용을 중지했습니다." if active else "계정을 다시 활성화했습니다.")
                st.rerun()
    st.caption("비밀번호 재발급 또는 계정 중지 시 기존 로그인은 종료됩니다. 기존 비밀번호는 조회할 수 없습니다.")


def _empty_state(icon: str, title: str, text: str) -> None:
    st.html(f'<div class="tap-empty"><span class="tap-empty__icon" aria-hidden="true">{escape(icon)}</span>'
            f'<b>{escape(title)}</b><p>{escape(text)}</p></div>')


def _form_section(number: str, title: str, caption: str) -> None:
    st.html(f'<div class="tap-form-section"><span>{escape(number)}</span><div><b>{escape(title)}</b>'
            f'<p>{escape(caption)}</p></div></div>')


def _factor_section(title: str, caption: str, chosen: int, limit: int | None, *, show_count: bool = True) -> None:
    count = "" if not show_count else f'<span class="tap-pick-count{" is-full" if limit and chosen >= limit else ""}">' + (
        f"{chosen}/{limit} 선택" if limit else f"{chosen}개 자동 포함") + "</span>"
    st.html(f'<div class="tap-pick-head"><div><b>{escape(title)}</b><span>{escape(caption)}</span></div>{count}</div>')


def _factor_checkboxes(rows: list[Mapping[str, Any]], key_prefix: str, limit: int, *, title: str, caption: str) -> list[str]:
    """Checkbox tiles; once `limit` boxes are ticked the rest are disabled until one is cleared."""
    keys = {row["factor_code"]: f"{key_prefix}_{row['factor_code']}" for row in rows}
    chosen = [code for code, key in keys.items() if st.session_state.get(key)]
    _factor_section(title, caption, len(chosen), limit)
    with st.container(key=key_prefix + "_grid"):
        columns = st.columns(3, gap="small")
        for index, row in enumerate(rows):
            key = keys[row["factor_code"]]
            with columns[index % 3]:
                st.checkbox(row["factor_name_ko"], key=key, help=row.get("definition") or None,
                            disabled=not st.session_state.get(key) and len(chosen) >= limit)
    return [code for code, key in keys.items() if st.session_state.get(key)]


def _render_project_create(store: Any, token: str, *, show_heading: bool = True) -> None:
    if show_heading:
        st.subheader("교육평가 프로젝트 만들기")
    st.caption("교육 전후 비교에 사용할 일정과 측정역량을 등록합니다. 등록한 검사 구성은 고정됩니다.")
    rows = load_competencies()
    picker = st.container(key=PREFIX + "factor_picker")
    with picker:
        _factor_section("응답 대상", "대상에 따라 고를 수 있는 역량이 달라집니다.", 0, None, show_count=False)
        target_level = st.radio("응답 대상", list(LEVEL_LABELS), format_func=LEVEL_LABELS.get, horizontal=True,
                                key=PREFIX + "target_level", label_visibility="collapsed")
    available = [row for row in rows if row["active_for_scoring"] and applicable_to_level(row, target_level)]
    base = [row for row in available if row["library_type"] == "base"]
    labels = {row["factor_code"]: row["factor_name_ko"] for row in available}
    with picker:
        _factor_section("기본역량", "모든 프로젝트에 공통으로 측정합니다.", len(base), None)
        with st.container(key=PREFIX + "factor_base_grid"):
            columns = st.columns(3, gap="small")
            for index, row in enumerate(base):
                with columns[index % 3]:
                    st.checkbox(row["factor_name_ko"], value=True, disabled=True, help=row.get("definition") or None,
                                key=PREFIX + f"base_{target_level}_{row['factor_code']}")
        specialty = _factor_checkboxes(
            [row for row in available if row["library_type"] == "specialty"], PREFIX + f"specialty_{target_level}",
            MAX_SPECIALTY, title="전문·미래역량", caption=f"교육 목표에 맞는 역량을 최대 {MAX_SPECIALTY}개 고르세요.")
        job = _factor_checkboxes(
            [row for row in available if row["library_type"] == "job_function"], PREFIX + f"job_{target_level}",
            MAX_JOB_FUNCTION, title="직무역량", caption=f"대상 직무를 최대 {MAX_JOB_FUNCTION}개 고르세요.")
        selected = [row["factor_code"] for row in base] + specialty + job
        st.html(f'<div class="tap-pick-total">측정역량 <b>{len(selected)}개</b> · 문항 <b>{len(questions_for_factors(selected))}개</b>'
                '<span>역량에 마우스를 올리면 정의를 볼 수 있습니다.</span></div>')
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    with st.form(PREFIX + "project_create"):
        _form_section("01", "기본 정보", "참여자 화면과 리포트에 표시되는 이름입니다.")
        left, right = st.columns(2)
        name = left.text_input("프로젝트명", max_chars=120, placeholder="예: 2026 하반기 CS 역량 과정")
        course_name = right.text_input("교육과정명", max_chars=120, placeholder="예: 고객 서비스 역량 향상 교육")
        _form_section("02", "검사 일정", "기간 밖에는 참여자가 응답할 수 없습니다. 교육 후 검사는 교육 8~10주 후 시작을 권장합니다.")
        training = st.date_input("교육일", today + timedelta(days=8))
        left, right = st.columns(2)
        with left:
            pre_start = st.date_input("교육 전 검사 시작일", today)
            post_start = st.date_input("교육 후 검사 시작일", today + timedelta(days=64))
        with right:
            pre_end = st.date_input("교육 전 검사 마감일", today + timedelta(days=7))
            post_end = st.date_input("교육 후 검사 마감일", today + timedelta(days=71))
        _form_section("03", "리포트 기준", "조직 리포트에서 목표 대비 차이와 우선 확인할 역량을 정합니다.")
        target_mean = st.slider("조직 기대 행동빈도", 1.0, 5.0, 3.5, 0.1, help="교육 우선순위 논의를 위한 운영 목표이며 표준 규준이 아닙니다.")
        st.html('<div class="tap-pick-head tap-pick-head--form"><div><b>조직 우선역량</b>'
                '<span>리포트에서 먼저 살펴볼 역량을 최대 3개 고르세요.</span></div></div>')
        with st.container(key=PREFIX + "priority_grid"):
            columns = st.columns(3, gap="small")
            priorities = [code for index, code in enumerate(selected)
                          if columns[index % 3].checkbox(labels[code], key=PREFIX + f"priority_{target_level}_{code}")]
        delivery = st.radio("선호 교육방식", ["all", "offline", "online"], format_func={"all": "무관", "offline": "집합", "online": "온라인"}.get, horizontal=True)
        submitted = st.form_submit_button("프로젝트 등록", type="primary")
    if submitted:
        if len(priorities) > 3:
            st.error("조직 우선역량은 최대 3개까지 고를 수 있습니다.")
            return
        try:
            config = build_project_config(name, course_name, target_level, specialty + job, training, pre_start, pre_end, post_start, post_end, target_mean, priorities, delivery)
        except ValueError as exc:
            st.error(str(exc))
            return
        ok, _ = _attempt(lambda: store.create_project(token, name.strip(), config))
        if ok:
            _notice("프로젝트를 등록했습니다. 참여자를 배정하면 각자 계정에서 검사에 응답할 수 있습니다.")
            st.rerun()


def _participant_matches(row: Mapping[str, Any], query: str) -> bool:
    return not query or any(
        query in str(row.get(field) or "").casefold()
        for field in ("display_name", "user_name", "login_id", "department", "job_title")
    )


# Progress board: one status per assigned person, grouped by department. With
# 100 people a flat table hid who had not started or stopped half-way.
BOARD_PAGE_SIZE = 10
BOARD_MAX_RANGES = 4
STATUS_ORDER = ("미시작", "진행 중", "교육 전 완료", "교육 후 완료", "배정 해제")
NO_DEPARTMENT = "부서 미등록"
_CHOSEONG = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_INITIAL_ORDER = "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"


def participant_status(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return (status, progress text) for one assignment row."""
    if not row.get("active", True):
        return "배정 해제", ""
    total = int(row.get("question_count") or 0)
    if row.get("post_completed"):
        return "교육 후 완료", ""
    if row.get("post_answered"):
        return "진행 중", f"교육 후 {row['post_answered']}/{total}"
    if row.get("pre_completed"):
        return "교육 전 완료", ""
    if row.get("pre_answered"):
        return "진행 중", f"교육 전 {row['pre_answered']}/{total}"
    return "미시작", ""


def name_initial(name: Any) -> str:
    first = str(name or "").strip()[:1]
    if "가" <= first <= "힣":
        initial = _CHOSEONG[(ord(first) - 0xAC00) // 588]
        # Double consonants sort with their base letter (ㄲ under ㄱ).
        return {"ㄲ": "ㄱ", "ㄸ": "ㄷ", "ㅃ": "ㅂ", "ㅆ": "ㅅ", "ㅉ": "ㅈ"}.get(initial, initial)
    return "기타"


def initial_ranges(rows: list[Mapping[str, Any]], name_key: str = "user_name") -> list[tuple[str, list[Mapping[str, Any]]]]:
    """Split a long list into up to four initial-consonant tabs of similar size."""
    ordered = sorted(rows, key=lambda row: str(row.get(name_key) or ""))
    if len(ordered) <= BOARD_PAGE_SIZE:
        return [("", ordered)]
    letters = [*_INITIAL_ORDER, "기타"]
    buckets = {letter: [row for row in ordered if name_initial(row.get(name_key)) == letter] for letter in letters}
    letters = [letter for letter in letters if buckets[letter]]
    count = min(BOARD_MAX_RANGES, -(-len(ordered) // BOARD_PAGE_SIZE), len(letters))
    groups: list[list[str]] = [[]]
    taken = 0
    for index, letter in enumerate(letters):
        remaining_letters = len(letters) - index
        remaining_groups = count - len(groups)
        # Close the group near its proportional share, but leave a letter for every later group.
        if groups[-1] and remaining_groups and (taken >= len(ordered) * len(groups) / count or remaining_letters == remaining_groups):
            groups.append([])
        groups[-1].append(letter)
        taken += len(buckets[letter])
    result = []
    start = 0
    for number, group in enumerate(groups):
        members = [row for letter in group for row in buckets[letter]]
        # Labels cover the whole ㄱ~ㅎ span, including letters nobody starts with.
        consonants = [letter for letter in group if letter != "기타"]
        end = len(_INITIAL_ORDER) - 1 if number == len(groups) - 1 else _INITIAL_ORDER.index(consonants[-1])
        span = ""
        if consonants:
            span = _INITIAL_ORDER[start] if start == end else f"{_INITIAL_ORDER[start]}~{_INITIAL_ORDER[end]}"
            start = end + 1
        label = "·".join(part for part in (span, "기타" if "기타" in group else "") if part)
        result.append((f"{label} {len(members)}", members))
    return result


def _incomplete_phase(project: Mapping[str, Any]) -> str:
    """The phase whose non-completers need a reminder today."""
    config = project.get("config") or {}
    try:
        post_start = date.fromisoformat(str(config.get("post_start_date", "")))
    except ValueError:
        return "pre"
    return "post" if datetime.now(ZoneInfo("Asia/Seoul")).date() >= post_start else "pre"


def _board_row(row: Mapping[str, Any]) -> dict[str, str]:
    status, progress = participant_status(row)
    return {"이름": row.get("user_name", ""), "로그인 아이디": row.get("login_id", ""), "부서": row.get("department", ""),
            "직급": row.get("job_title", ""), "상태": status, "진행": progress}


def incomplete_csv(project: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> tuple[str, bytes, int]:
    """Reminder list for the current phase: (button label, CSV bytes, people)."""
    phase = _incomplete_phase(project)
    pending = [row for row in rows if row.get("active", True) and not row.get(phase + "_completed")]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["이름", "로그인 아이디", "부서", "직급", "상태", "진행"])
    for row in sorted(pending, key=lambda item: (str(item.get("department") or "~"), str(item.get("user_name") or ""))):
        writer.writerow([_csv_cell(value) for value in _board_row(row).values()])
    label = "교육 전" if phase == "pre" else "교육 후"
    return f"{label} 미완료자 명단 CSV ({len(pending)}명)", output.getvalue().encode("utf-8-sig"), len(pending)


def _board_page(page_key: str, page: int) -> None:
    st.session_state[page_key] = page


# People lists follow the LXP console (교육 개설 사람 목록, 조직원 목록): 가나다순,
# '전체' plus up to four initial-consonant ranges once a list passes ten people,
# and ten people per page.
PEOPLE_PAGE_SIZE = BOARD_PAGE_SIZE


def _move_people_page(page_key: str, page: int, clear_key: str | None = None) -> None:
    st.session_state[page_key] = page
    if clear_key:
        # A different page must not leave actions aimed at a hidden person.
        st.session_state[clear_key] = None


def _people_window(
    rows: list[Mapping[str, Any]], *, range_key: str, page_key: str, name_key: str, clear_key: str | None = None,
) -> tuple[list[Mapping[str, Any]], Callable[[], None]]:
    """Draw the range chips and return this page's people plus a pager to draw below them."""
    ordered = sorted(rows, key=lambda row: (name_initial(row.get(name_key)) == "기타", str(row.get(name_key) or "")))
    ranges = initial_ranges(ordered, name_key)
    visible = ordered
    if len(ranges) > 1:
        labels = [f"전체 {len(ordered)}", *(label for label, _ in ranges)]
        # Labels carry counts, so a new search result falls back to '전체'.
        if st.session_state.get(range_key) not in labels:
            st.session_state[range_key] = labels[0]
        chosen = st.segmented_control("이름 구간", labels, key=range_key, label_visibility="collapsed",
                                      on_change=_move_people_page, args=(page_key, 0, clear_key)) or labels[0]
        visible = ordered if chosen == labels[0] else dict(ranges)[chosen]
    pages = max(1, -(-len(visible) // PEOPLE_PAGE_SIZE))
    page = max(0, min(int(st.session_state.get(page_key, 0)), pages - 1))
    st.session_state[page_key] = page
    start = page * PEOPLE_PAGE_SIZE
    window = visible[start:start + PEOPLE_PAGE_SIZE]

    def pager() -> None:
        if pages == 1:
            return
        left, center, right = st.columns([1, 1, 1], vertical_alignment="center")
        with left:
            st.button("이전", key=page_key + "_previous", disabled=page == 0,
                      on_click=_move_people_page, args=(page_key, page - 1, clear_key))
        with center:
            st.caption(f"{len(visible)}명 중 {start + 1}~{start + len(window)} · {page + 1} / {pages} 페이지")
        with right:
            st.button("다음", key=page_key + "_next", disabled=page == pages - 1,
                      on_click=_move_people_page, args=(page_key, page + 1, clear_key))

    return window, pager


def _render_department(project_id: str, department: str, members: list[Mapping[str, Any]], everyone: list[Mapping[str, Any]], expanded: bool) -> None:
    active = [row for row in everyone if row.get("active", True)]
    phase = "post" if any(row.get("post_answered") or row.get("post_completed") for row in active) else "pre"
    done = sum(bool(row.get(phase + "_completed")) for row in active)
    phase_label = "교육 전" if phase == "pre" else "교육 후"
    digest = hashlib.sha256(department.encode("utf-8")).hexdigest()[:10]
    label = f"{department} · {phase_label} 완료 {done}/{len(active)}명" + (f" · 표시 {len(members)}명" if len(members) != len(everyone) else "")
    with st.expander(label, expanded=expanded, key=PREFIX + f"board_{project_id}_{digest}"):
        if active:
            st.progress(done / len(active))
        rows, pager = _people_window(members, range_key=PREFIX + f"board_range_{project_id}_{digest}",
                                     page_key=PREFIX + f"board_page_{project_id}_{digest}", name_key="user_name")
        st.dataframe([_board_row(row) for row in rows], hide_index=True, width="stretch")
        pager()


def _render_progress_board(project: Mapping[str, Any], everyone: list[Mapping[str, Any]], matched: list[Mapping[str, Any]]) -> None:
    project_id = _identifier(project)
    statuses = {str(row["id"]): participant_status(row)[0] for row in everyone}
    counts = {status: sum(value == status for value in statuses.values()) for status in STATUS_ORDER}
    options = ["전체", *(status for status in STATUS_ORDER if status != "배정 해제" or counts[status])]
    filter_key = PREFIX + f"board_status_{project_id}"
    if st.session_state.get(filter_key) not in options:
        st.session_state[filter_key] = "전체"
    chosen = st.pills("검사 상태", options, key=filter_key, label_visibility="collapsed",
                      format_func=lambda value: f"{value} {len(everyone) if value == '전체' else counts[value]}") or "전체"
    shown = [row for row in matched if chosen == "전체" or statuses[str(row["id"])] == chosen]
    label, content, pending = incomplete_csv(project, everyone)
    st.download_button(label, content, f"tap_incomplete_{project_id}.csv", "text/csv", disabled=not pending,
                       key=PREFIX + f"board_csv_{project_id}", help="이름, 아이디, 부서, 직급과 검사 상태만 담습니다. 사내 메신저로 응답을 독려할 때 쓰세요.")
    if not shown:
        st.info("이 상태에 해당하는 참여자가 없습니다.")
        return
    names = sorted({_department(row) for row in shown}, key=lambda name: (name == NO_DEPARTMENT, name))
    for name in names:
        _render_department(project_id, name, [row for row in shown if _department(row) == name],
                           [row for row in everyone if _department(row) == name], expanded=len(names) == 1)


def _department(row: Mapping[str, Any]) -> str:
    return str(row.get("department") or "").strip() or NO_DEPARTMENT


def _person_label(row: Mapping[str, Any]) -> str:
    return " · ".join(str(part) for part in (row.get("display_name"), row.get("login_id"), row.get("department"), row.get("job_title")) if part)


def _toggle_person(pick_key: str, value: str, box_key: str) -> None:
    picked = [item for item in st.session_state.get(pick_key) or [] if item != value]
    if st.session_state.get(box_key):
        picked.append(value)
    st.session_state[pick_key] = picked


def _pick_people(pick_key: str, values: list[str]) -> None:
    picked = list(st.session_state.get(pick_key) or [])
    st.session_state[pick_key] = picked + [value for value in values if value not in picked]


def _bulk_pick(
    rows: list[Mapping[str, Any]], pick_key: str, *, search_key: str, search_label: str, unit_label: str,
    group: Callable[[Mapping[str, Any]], str] = _department, group_label: str = "부서 전체 선택",
) -> list[str]:
    """Pick whole groups in one click, plus individuals found by search.

    Group chips stay visible and the individual picks are cut to the current
    search, so the selection never contains someone the screen does not show.
    """
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(group(row), []).append(row)
    names = sorted(groups, key=lambda name: (name == NO_DEPARTMENT, name))
    group_key = pick_key + "_groups"
    st.session_state[group_key] = [name for name in st.session_state.get(group_key) or [] if name in groups]
    chosen = st.pills(group_label, names, selection_mode="multi", key=group_key,
                      format_func=lambda name: f"{name} {len(groups[name])}") or []
    in_groups = {_identifier(row) for name in chosen for row in groups[name]}
    query = st.text_input(
        search_label, key=search_key, placeholder="이름, 아이디, 부서, 직급으로 검색",
        help="부서 전체 선택에 없는 사람을 한 명씩 더할 때 씁니다. 영문 대소문자는 구분하지 않습니다.",
    ).strip().casefold()
    matched = {_identifier(row): row for row in rows if _identifier(row) not in in_groups and _participant_matches(row, query)}
    picked = [value for value in st.session_state.get(pick_key) or [] if value in matched]
    st.session_state[pick_key] = picked
    if st.session_state.get(pick_key + "_query") != query:
        st.session_state[pick_key + "_query"] = query
        st.session_state[pick_key + "_page"] = 0
    st.caption(f"검색 결과 {len(matched)}명 · {unit_label} {len(rows)}명")
    if matched:
        window, pager = _people_window(list(matched.values()), range_key=pick_key + "_range",
                                       page_key=pick_key + "_page", name_key="display_name")
        page_ids = [_identifier(row) for row in window]
        if any(value not in picked for value in page_ids):
            st.button(f"이 페이지 {len(page_ids)}명 모두 선택", key=pick_key + "_page_all", type="tertiary",
                      icon=":material/done_all:", on_click=_pick_people, args=(pick_key, page_ids))
        for row in window:
            value = _identifier(row)
            box_key = f"{pick_key}_pick_{value}"
            st.session_state[box_key] = value in picked
            st.checkbox(_person_label(row), key=box_key, on_change=_toggle_person, args=(pick_key, value, box_key))
        pager()
    elif query:
        st.info("검색 결과가 없습니다. 검색어를 다시 입력해 주세요.")
    by_id = {_identifier(row): row for row in rows}
    selected = [value for value in by_id if value in in_groups or value in st.session_state[pick_key]]
    if selected:
        st.dataframe([{"이름": by_id[value].get("display_name", ""), "로그인 아이디": by_id[value].get("login_id", ""),
                       "부서": by_id[value].get("department", ""), "직급": by_id[value].get("job_title", "")} for value in selected],
                     hide_index=True, width="stretch", height=min(400, 38 + 35 * len(selected)))
    return selected


def _render_assignments(store: Any, token: str, project: Mapping[str, Any], users: list[dict[str, Any]]) -> None:
    project_id = _identifier(project)
    ok, assignments = _attempt(lambda: store.list_assignments(token, project_id))
    if not ok:
        return
    st.subheader("참여자 배정")
    participants = {_identifier(row): row for row in users if row.get("role") == "participant" and str(row.get("company_id")) == str(project.get("company_id"))}
    # Assignments remain scoped by the store; profile search uses this company's users only.
    assignments = [{**row, **{
        field: row.get(field) or participants.get(str(row["user_id"]), {}).get(field, "")
        for field in ("department", "job_title")
    }} for row in assignments]
    change_key = PREFIX + f"assignment_change_{project_id}"
    if assignments:
        query = st.text_input(
            "배정된 참여자 검색", key=PREFIX + f"assignment_search_{project_id}",
            placeholder="이름, 아이디, 부서, 직급으로 검색",
            help="일부 글자로 검색할 수 있습니다. 영문 대소문자는 구분하지 않습니다.",
        ).strip().casefold()
        matched = [row for row in assignments if _participant_matches(row, query)]
        by_assignment = {str(row["id"]): row for row in matched}
        if st.session_state.get(change_key) not in by_assignment:
            st.session_state[change_key] = None
        st.caption(f"검색 결과 {len(matched)}명 · 배정된 참여자 {len(assignments)}명")
        if matched:
            _render_progress_board(project, assignments, matched)
            with st.expander("참여자 배정 변경", key=PREFIX + f"assignment_panel_{project_id}"):
                assignment_id = st.selectbox("배정을 변경할 참여자", list(by_assignment), format_func=lambda value: f"{by_assignment[value].get('user_name', '')} · {by_assignment[value].get('login_id', '')}", key=change_key, index=None, placeholder="참여자를 선택하세요")
                if assignment_id is not None:
                    active = bool(by_assignment[assignment_id].get("active", True))
                    if st.button("프로젝트 배정 해제" if active else "프로젝트 다시 배정", key=PREFIX + f"assignment_toggle_{project_id}"):
                        ok, _ = _attempt(lambda: store.set_assignment_active(token, assignment_id, not active))
                        if ok:
                            _notice("프로젝트 배정을 해제했습니다. 기존 검사 결과는 보존됩니다." if active else "프로젝트에 다시 배정했습니다.")
                            st.rerun()
        else:
            st.info("배정된 참여자 검색 결과가 없습니다. 검색어를 다시 입력해 주세요.")
    else:
        st.session_state[change_key] = None
    assigned = {str(row["user_id"]) for row in assignments}
    candidates = {user_id: row for user_id, row in participants.items() if row.get("active", True) and user_id not in assigned}
    assign_key = PREFIX + f"assign_{project_id}"
    if not candidates:
        st.session_state[assign_key] = []
        st.info("배정할 새 참여자가 없습니다. 참여자 계정을 발급하거나 기존 배정 현황을 확인해 주세요.")
        return
    st.markdown("**참여자 추가**")
    selected = _bulk_pick(list(candidates.values()), assign_key, search_key=PREFIX + f"assign_search_{project_id}",
                          search_label="추가할 참여자 검색", unit_label="배정 가능한 참여자")
    if st.button(f"선택한 {len(selected)}명 배정", disabled=not selected, key=PREFIX + f"assign_save_{project_id}", type="primary"):
        # One transaction: a failure leaves nobody half-assigned.
        ok, count = _attempt(lambda: store.assign_participants(token, project_id, selected))
        if ok:
            _notice(f"참여자 {count}명을 배정했습니다.")
            st.rerun()


def _render_projects(store: Any, token: str, principal: Mapping[str, Any], projects: list[dict[str, Any]], users: list[dict[str, Any]]) -> None:
    st.subheader("프로젝트 현황")
    if principal.get("role") == "company":
        projects = [row for row in projects if row.get("company_id") == principal.get("company_id")]
    selection_key = PREFIX + "project_select"
    if not projects:
        st.session_state[selection_key] = None
        st.info("등록된 프로젝트가 없습니다.")
        return
    query = st.text_input(
        "프로젝트 검색", key=PREFIX + "project_search",
        placeholder="회사명, 프로젝트명, 교육명으로 검색",
        help="일부 글자로 검색할 수 있습니다. 영문 대소문자는 구분하지 않습니다.",
    ).strip().casefold()
    matched = [row for row in projects if not query or any(
        query in str(value or "").casefold() for value in (
            row.get("company_name"), row.get("name") or row.get("project_name"),
            (row.get("config") or {}).get("course_name"),
        )
    )]
    by_id = {_identifier(row): row for row in matched}
    if st.session_state.get(selection_key) not in by_id:
        st.session_state[selection_key] = None
    st.caption(f"검색 결과 {len(matched)}개 · 전체 {len(projects)}개")
    if not matched:
        st.info("검색 결과가 없습니다. 회사명, 프로젝트명 또는 교육명을 다시 입력해 주세요.")
        return
    selected = st.selectbox(
        "프로젝트 선택", list(by_id),
        format_func=lambda value: " · ".join(str(part) for part in (
            by_id[value].get("name") or by_id[value].get("project_name") or "교육평가 프로젝트",
            by_id[value].get("company_name"), (by_id[value].get("config") or {}).get("course_name"),
        ) if part),
        key=selection_key, index=None, placeholder="프로젝트를 선택하세요",
    )
    if selected is None:
        return
    project = by_id[selected]
    config = project.get("config", {})
    if config:
        st.caption(f"교육일 {config.get('training_date', '미설정')} · 교육 전 검사 {config.get('pre_start_date', '')} ~ {config.get('pre_end_date', '')} · 교육 후 검사 {config.get('post_start_date', '')} ~ {config.get('post_end_date', '')}")
    if principal.get("role") == "company":
        _render_assignments(store, token, project, users)
    from tap.account_reports import render_project_report
    render_project_report(store, token, project)



def _workspace_fields(fields: list[tuple[str, Any]]) -> None:
    """Render compact detail labels without treating account data as markup."""
    st.html('<dl class="tap-workspace-fields">' + ''.join(
        f"<dt>{escape(label)}</dt><dd>{escape(str(value or '미등록'))}</dd>"
        for label, value in fields
    ) + '</dl>')


def _workspace_page(selection_key: str, page_key: str, page: int) -> None:
    # A different page must not leave destructive buttons aimed at a hidden row.
    st.session_state[page_key] = page
    st.session_state[selection_key] = None


def _workspace_pick(
    rows: list[dict[str, Any]], *, selection_key: str, search_key: str,
    search_label: str, placeholder: str, label: str, unit: str,
    search_values: Callable[[Mapping[str, Any]], list[Any]],
    title: Callable[[Mapping[str, Any]], str], caption: Callable[[Mapping[str, Any]], str],
    name_key: str | None = None,
) -> Mapping[str, Any] | None:
    """Search, then pick one row. With name_key it is a people list (initials, ten per page)."""
    query = st.text_input(
        search_label, key=search_key, placeholder=placeholder,
        help="일부 글자로 검색할 수 있습니다. 영문 대소문자는 구분하지 않습니다.",
        persist_state="session",
    ).strip().casefold()
    matched = [row for row in rows if not query or any(
        query in str(value or "").casefold() for value in search_values(row)
    )]
    by_id = {_identifier(row): row for row in matched}
    if st.session_state.get(selection_key) not in by_id:
        st.session_state[selection_key] = None
    page_key = selection_key + "_page"
    query_key = search_key + "_previous"
    if st.session_state.get(query_key) != query:
        st.session_state[page_key] = 0
        st.session_state[query_key] = query
    st.caption(f"검색 결과 {len(matched)}{unit} · 전체 {len(rows)}{unit}")
    if not matched:
        st.info("검색 결과가 없습니다. 검색어를 다시 입력해 주세요." if rows else f"등록된 {_josa(label, '이', '가')} 없습니다.")
        return None
    if name_key:
        window, pager = _people_window(matched, range_key=selection_key + "_range", page_key=page_key,
                                       name_key=name_key, clear_key=selection_key)
        visible = [_identifier(row) for row in window]
    else:
        pages = max(1, (len(matched) + WORKSPACE_PAGE_SIZE - 1) // WORKSPACE_PAGE_SIZE)
        page = max(0, min(int(st.session_state.get(page_key, 0)), pages - 1))
        st.session_state[page_key] = page
        visible = list(by_id)[page * WORKSPACE_PAGE_SIZE:(page + 1) * WORKSPACE_PAGE_SIZE]

        def pager() -> None:
            if pages == 1:
                return
            left, center, right = st.columns([1, 1, 1], vertical_alignment="center")
            with left:
                st.button("이전", key=selection_key + "_previous_page", disabled=page == 0,
                          on_click=_workspace_page, args=(selection_key, page_key, page - 1))
            with center:
                st.caption(f"{page + 1} / {pages} 페이지")
            with right:
                st.button("다음", key=selection_key + "_next_page", disabled=page == pages - 1,
                          on_click=_workspace_page, args=(selection_key, page_key, page + 1))
    if st.session_state.get(selection_key) not in visible:
        st.session_state[selection_key] = None
    selected = st.radio(
        label, visible, format_func=lambda value: title(by_id[value]),
        captions=[caption(by_id[value]) for value in visible],
        key=selection_key, index=None, label_visibility="collapsed",
        width="stretch", persist_state="session",
    )
    pager()
    return by_id.get(selected)


def _company_pick(companies: list[dict[str, Any]], selection_key: str, search_label: str) -> Mapping[str, Any] | None:
    """Find a member company by typing instead of scrolling a dropdown."""
    # The panel key styles results as a card grid; see premium-workspace.css.
    with st.container(border=True, key="tap_company_pick_" + selection_key.removeprefix(PREFIX)):
        return _workspace_pick(
            companies, selection_key=selection_key, search_key=selection_key + "_search",
            search_label=search_label, placeholder="회사명 또는 사업자등록번호로 검색", label="회원사", unit="개",
            search_values=lambda row: [row.get("name"), _company_registration_label(row)],
            title=lambda row: str(row.get("name") or "회원사"),
            caption=lambda row: f"사업자등록번호 {_company_registration_label(row)}",
        )


def _render_workspace_users(store: Any, token: str, principal: Mapping[str, Any], users: list[dict[str, Any]]) -> None:
    allowed = [row for row in users if row.get("role") in {"company", "participant"} and _identifier(row) != _identifier(principal)]
    if principal.get("role") == "company":
        allowed = [row for row in allowed if row.get("role") == "participant" and row.get("company_id") == principal.get("company_id")]
    with st.container(key="tap_workspace_split"):
        left, right = st.columns([1.4, 1], gap="large")
        with left, st.container(border=True, key="tap_workspace_account_list"):
            if principal.get("role") == "kma":
                counts = {role: sum(row.get("role") == role for row in allowed) for role in ("company", "participant")}
                role_filter = st.segmented_control(
                    "계정 구분", ["all", "company", "participant"], key=PREFIX + "manage_user_role",
                    format_func=lambda value: f"전체 {len(allowed)}" if value == "all" else f"{ROLE_LABELS[value]} {counts[value]}",
                    default="all", label_visibility="collapsed", width="stretch",
                )
                if role_filter in counts:
                    allowed = [row for row in allowed if row.get("role") == role_filter]
            user = _workspace_pick(
                allowed, selection_key=PREFIX + "manage_user", search_key=PREFIX + "manage_user_search",
                search_label="계정 검색", placeholder="이름, 아이디, 부서, 회사명으로 검색", label="관리할 계정", unit="명",
                search_values=lambda row: [row.get(field) for field in ("display_name", "login_id", "company_name", "department", "job_title")],
                title=lambda row: f"{row.get('display_name', '')} · {row.get('login_id', '')}", name_key="display_name",
                caption=lambda row: " · ".join(part for part in (
                    str(row.get("company_name") or ""), ROLE_LABELS.get(row["role"], ""),
                    "사용 중" if row.get("active", True) else "중지",
                ) if part),
            )
        with right, st.container(border=True, key="tap_workspace_account_detail"):
            if user is None:
                _empty_state("manage_accounts", "계정 상세",
                             "왼쪽 목록에서 계정을 선택하면 로그인 정보와 부서·직급을 확인하고 비밀번호 재발급, 사용 중지를 할 수 있습니다.")
            else:
                st.caption("계정 상세")
                st.subheader(str(user.get("display_name") or "계정"))
                _workspace_fields([
                    ("아이디", user.get("login_id")), ("회사", user.get("company_name")),
                    ("역할", ROLE_LABELS.get(str(user.get("role")), "")),
                    ("상태", "사용 중" if user.get("active", True) else "중지"),
                    *((label, user.get(key)) for key, (label, _) in PROFILE_FIELDS.items()),
                ])
                _render_user_actions(store, token, principal, user)
    _render_bulk_accounts(store, token, principal, allowed)


BULK_ACTIONS = {"reset": "임시 비밀번호 재발급", "deactivate": "사용 중지", "activate": "다시 활성화"}


def _render_bulk_accounts(store: Any, token: str, principal: Mapping[str, Any], users: list[dict[str, Any]]) -> None:
    """Reissue or stop many accounts at once, e.g. a whole department after a course."""
    if not users:
        return
    with st.expander("여러 계정 한 번에 처리", key=PREFIX + "bulk_accounts", on_change="rerun"):
        action = st.segmented_control("처리할 작업", list(BULK_ACTIONS), format_func=BULK_ACTIONS.get, default="reset",
                                      key=PREFIX + "bulk_action", width="stretch") or "reset"
        wanted = {"reset": None, "deactivate": True, "activate": False}[action]
        rows = [row for row in users if wanted is None or bool(row.get("active", True)) == wanted]
        if not rows:
            st.info("이 작업을 할 계정이 없습니다.")
            return
        by_company = principal.get("role") == "kma"
        selected = _bulk_pick(
            rows, PREFIX + f"bulk_{action}", search_key=PREFIX + f"bulk_{action}_search", search_label="계정 검색",
            unit_label="대상 계정", group=(lambda row: str(row.get("company_name") or "회사 미등록")) if by_company else _department,
            group_label="회사 전체 선택" if by_company else "부서 전체 선택",
        )
        st.caption({"reset": "임시 비밀번호는 모두 kma로 재발급되고 기존 로그인은 종료됩니다. 다음 로그인 때 새 비밀번호로 바꿉니다.",
                    "deactivate": "사용 중지한 계정은 바로 로그아웃되고 로그인할 수 없습니다. 검사 결과는 보존됩니다.",
                    "activate": "다시 활성화한 계정은 기존 비밀번호로 로그인합니다."}[action])
        if st.button(f"선택한 {len(selected)}명 {BULK_ACTIONS[action]}", disabled=not selected, key=PREFIX + "bulk_save", type="primary"):
            # One transaction: either every selected account changes or none does.
            if action == "reset":
                password = _temporary_password("participant")
                ok, count = _attempt(lambda: store.reset_passwords(token, selected, password))
                if ok:
                    picked = {_identifier(row): row for row in rows}
                    _remember_credentials([{"login_id": str(picked[value]["login_id"]), "display_name": str(picked[value].get("display_name") or ""),
                                            "temp_password": password} for value in selected], principal)
            else:
                ok, count = _attempt(lambda: store.set_users_active(token, selected, action == "activate"))
            if ok:
                _notice(f"{count}명 계정을 {BULK_ACTIONS[action]}했습니다." if action != "reset" else f"{count}명에게 임시 비밀번호를 재발급했습니다.")
                st.rerun()


def _render_workspace_projects(store: Any, token: str, principal: Mapping[str, Any], projects: list[dict[str, Any]], users: list[dict[str, Any]]) -> None:
    if principal.get("role") == "company":
        projects = [row for row in projects if row.get("company_id") == principal.get("company_id")]
    with st.container(key="tap_workspace_split"):
        left, right = st.columns([1.4, 1], gap="large")
        with left, st.container(border=True, key="tap_workspace_project_list"):
            project = _workspace_pick(
                projects, selection_key=PREFIX + "project_select", search_key=PREFIX + "project_search",
                search_label="프로젝트 검색", placeholder="회사명, 사업자등록번호, 프로젝트명, 교육명으로 검색", label="프로젝트", unit="개",
                search_values=lambda row: [row.get("company_name"), row.get("company_registration_number"),
                                           row.get("name") or row.get("project_name"), (row.get("config") or {}).get("course_name")],
                title=lambda row: str(row.get("name") or row.get("project_name") or "교육평가 프로젝트"),
                caption=lambda row: " · ".join(str(part) for part in (row.get("company_name"), (row.get("config") or {}).get("course_name")) if part),
            )
        with right, st.container(border=True, key="tap_workspace_project_detail"):
            if project is None:
                _empty_state("folder_open", "프로젝트 상세",
                             "왼쪽 목록에서 프로젝트를 선택하면 일정과 참여자 배정, 참여 현황과 리포트가 열립니다.")
            else:
                st.caption("프로젝트 상세")
                st.subheader(str(project.get("name") or project.get("project_name") or "교육평가 프로젝트"))
                config = project.get("config") or {}
                _workspace_fields([
                    ("회사", project.get("company_name")), ("교육명", config.get("course_name")),
                    ("교육일", config.get("training_date") or "미설정"),
                    ("교육 전 검사", f"{config.get('pre_start_date', '미설정')} ~ {config.get('pre_end_date', '미설정')}"),
                    ("교육 후 검사", f"{config.get('post_start_date', '미설정')} ~ {config.get('post_end_date', '미설정')}"),
                ])
    if project is not None and principal.get("role") == "company":
        # Assigning participants is the next step after picking a project, so it
        # spans the full width right under the list/detail row, above the reports.
        with st.container(border=True, key="tap_workspace_assignments"):
            _render_assignments(store, token, project, users)
    if project is not None:
        with st.container(border=True, key="tap_workspace_project_reports"):
            from tap.account_reports import render_project_report
            render_project_report(store, token, project)


def _render_workspace(
    store: Any, token: str, principal: Mapping[str, Any], section: str,
    companies: list[dict[str, Any]], users: list[dict[str, Any]], projects: list[dict[str, Any]],
) -> None:
    role = principal["role"]
    company = next((row for row in companies if _identifier(row) == str(principal.get("company_id"))), None)
    if role == "company" and company is None:
        st.error("계정에 연결된 회사를 확인하지 못했습니다. KMA 관리자에게 문의해 주세요.")
        return
    if section == "companies":
        _render_companies(store, token, companies, show_heading=False)
    elif section == "projects":
        _render_workspace_projects(store, token, principal, projects, users)
    elif section == "create_project":
        _render_project_create(store, token, show_heading=False)
    elif section == "accounts":
        issuance_label = "교육담당자 계정 발급" if role == "kma" else "참여자 계정 발급"
        with st.expander(issuance_label, key=PREFIX + f"workspace_issue_{role}", on_change="rerun"):
            if role == "kma":
                active_companies = [row for row in companies if row.get("active", True)]
                if active_companies:
                    issue_company = _company_pick(active_companies, PREFIX + "issue_company_pick", "계정을 발급할 회사 검색")
                    if issue_company is not None:
                        _render_create_user(store, token, principal, issue_company, "company", show_heading=False)
                else:
                    st.info("먼저 회원사를 등록해 주세요.")
            else:
                _render_create_user(store, token, principal, company, "participant", show_heading=False)
                _render_batch(store, token, principal, company, users, projects)
        _render_workspace_users(store, token, principal, users)


def render_admin(store: Any, token: str, principal: Mapping[str, Any], *, section: str | None = None) -> None:
    """Render administrative controls; AccountStore enforces every permission."""
    role = principal.get("role")
    if role not in {"kma", "company"}:
        st.error("관리자 계정으로 로그인해 주세요.")
        return
    if section is not None and section not in WORKSPACE_SECTIONS[role]:
        st.error("이 계정에서 사용할 수 없는 메뉴입니다.")
        return
    st.title(WORKSPACE_SECTIONS[role][section] if section is not None else ("회원사·계정 관리" if role == "kma" else "교육 운영 관리"))
    if notice := st.session_state.pop(PREFIX + "notice", None):
        st.success(notice)
    _render_credentials(principal)
    ok, companies = _attempt(lambda: store.list_companies(token))
    if not ok:
        return
    users: list[dict[str, Any]] = []
    if section is None or section == "accounts" or (section == "projects" and role == "company"):
        ok, users = _attempt(lambda: store.list_users(token))
        if not ok:
            return
    projects: list[dict[str, Any]] = []
    # The participant CSV can assign a project right away, so it needs the list too.
    if section is None or section == "projects" or (section == "accounts" and role == "company"):
        ok, projects = _attempt(lambda: store.list_projects(token))
        if not ok:
            return
    company_names = {_identifier(row): str(row["name"]) for row in companies}
    company_numbers = {_identifier(row): _company_registration_label(row) for row in companies}
    projects = [{**row, "company_name": company_names.get(str(row.get("company_id")), ""),
                 "company_registration_number": company_numbers.get(str(row.get("company_id")), "")} for row in projects]
    users = [{**row, "company_name": company_names.get(str(row.get("company_id")), str(row.get("company_name") or ""))} for row in users]
    if section is not None:
        _render_workspace(store, token, principal, section, companies, users, projects)
        return
    if role == "kma":
        company_tab, user_tab, project_tab = st.tabs(["회원사", "교육담당자·계정", "프로젝트 현황"], key=PREFIX + "kma_tabs", on_change="rerun")
        with company_tab:
            _render_companies(store, token, companies)
        with user_tab:
            active_companies = [row for row in companies if row.get("active", True)]
            if active_companies:
                if (issue_company := _company_pick(active_companies, PREFIX + "issue_company_pick", "계정을 발급할 회사 검색")) is not None:
                    _render_create_user(store, token, principal, issue_company, "company")
            else:
                st.info("먼저 회원사를 등록해 주세요.")
            _render_manage_users(store, token, principal, users)
        with project_tab:
            _render_projects(store, token, principal, projects, users)
    else:
        company = next((row for row in companies if _identifier(row) == str(principal.get("company_id"))), None)
        if company is None:
            st.error("계정에 연결된 회사를 확인하지 못했습니다. KMA 관리자에게 문의해 주세요.")
            return
        st.caption(str(company["name"]))
        project_tab, create_tab, user_tab = st.tabs(["프로젝트·참여 현황", "프로젝트 만들기", "참여자 계정"], key=PREFIX + "company_tabs", on_change="rerun")
        with project_tab:
            _render_projects(store, token, principal, projects, users)
        with create_tab:
            _render_project_create(store, token)
        with user_tab:
            _render_create_user(store, token, principal, company, "participant")
            _render_batch(store, token, principal, company, users, projects)
            _render_manage_users(store, token, principal, users)
