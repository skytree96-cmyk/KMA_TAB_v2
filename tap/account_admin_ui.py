"""Account and project administration for authenticated production users."""
from __future__ import annotations

import csv
import hashlib
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
MAX_CSV_BYTES = 256 * 1024
PROFILE_FIELDS = {"department": ("부서", 100), "job_title": ("직급", 80), "email": ("이메일", 254), "phone": ("연락처", 40)}


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


def _login_id(value: str, company_prefix: str | None = None) -> str:
    value = value.strip().lower()
    if not value:
        raise ValueError("아이디를 입력해 주세요.")
    if company_prefix:
        company_prefix = company_prefix.strip().lower()
        if not value.startswith(company_prefix + "-"):
            value = f"{company_prefix}-{value}"
        if len(value) <= len(company_prefix) + 1:
            raise ValueError("회사 식별정보 뒤에 사용할 아이디를 입력해 주세요.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", value):
        raise ValueError("아이디는 영문 소문자·숫자로 시작하는 3~64자의 영문·숫자·점·밑줄·하이픈으로 입력해 주세요.")
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
            raise ValueError(f"{label}은 줄바꿈 없이 {limit}자 이내로 입력해 주세요.")
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
        raise ValueError("UTF-8 형식의 CSV 파일을 올려 주세요.") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    try:
        fields = reader.fieldnames or []
        if fields[:2] != ["login_id", "display_name"] or len(fields) != len(set(fields)) or not set(fields[2:]).issubset(PROFILE_FIELDS):
            raise ValueError("첫 두 열은 login_id,display_name이어야 합니다. 선택 열은 department,job_title,email,phone만 사용할 수 있습니다. 아래 양식을 사용해 주세요.")
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
        st.info("임시 비밀번호는 이 발급 화면에서만 확인할 수 있습니다. 필요한 정보를 내려받아 해당 사용자에게 전달한 후 닫아 주세요. 첫 로그인 때 비밀번호를 변경합니다.")
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
    if pre_end >= training_date or post_start <= training_date:
        raise ValueError("교육 전 검사는 교육일 전에 마감하고, 교육 후 검사는 교육일 다음 날부터 시작해야 합니다.")
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


def _render_companies(store: Any, token: str, companies: list[dict[str, Any]]) -> None:
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
    by_id = {_identifier(row): row for row in companies}
    selected = st.selectbox("사업자등록번호를 변경할 회사", list(by_id), format_func=lambda value: f"{by_id[value]['name']} · {_company_registration_label(by_id[value])}", key=PREFIX + "registration_company")
    current_number = _company_registration_label(by_id[selected])
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


def _render_create_user(store: Any, token: str, principal: Mapping[str, Any], company: Mapping[str, Any], role: str) -> None:
    if role not in {"company", "participant"}:
        st.error("교육담당자 또는 참여자 계정만 발급할 수 있습니다.")
        return
    label = ROLE_LABELS[role]
    st.subheader(f"{label} 계정 발급")
    st.caption(f"회사: {company['name']} · 사업자등록번호: {_company_registration_label(company)}")
    if role == "participant":
        st.caption(f"참여자 아이디 앞에는 회사 식별정보 {company['slug']}-가 자동으로 붙습니다. 이미 붙여 입력한 경우에는 한 번만 사용합니다.")
    else:
        st.caption("교육담당자는 입력한 아이디로 로그인합니다. 아이디는 전체 회원사에서 중복 없이 사용합니다.")
    st.caption("영문 대문자는 소문자로 저장됩니다. 로그인에는 이메일을 사용하지 않습니다.")
    st.info(f"{label}의 임시 비밀번호는 kma로 자동 발급됩니다. 첫 로그인 때 새 비밀번호로 변경해야 합니다.")
    with st.form(PREFIX + f"user_create_{role}_{_identifier(company)}", clear_on_submit=True):
        login_input = st.text_input("아이디", max_chars=80, placeholder="예: user001", help="영문 소문자·숫자·점·밑줄·하이픈을 사용할 수 있습니다. 완성된 로그인 아이디는 3~64자이며, 영문 소문자 또는 숫자로 시작해야 합니다.")
        name = st.text_input("이름", max_chars=80)
        profile_input: dict[str, str] = {}
        if role == "participant":
            st.caption("부서·직급·이메일·연락처는 선택 입력입니다.")
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


def _render_batch(store: Any, token: str, principal: Mapping[str, Any], company: Mapping[str, Any], users: list[dict[str, Any]]) -> None:
    with st.expander("CSV로 참여자 일괄 등록", key=PREFIX + f"batch_expander_{_identifier(company)}", on_change="rerun"):
        st.caption(f"UTF-8 CSV · 한 번에 최대 {MAX_BATCH_ROWS}명 · 아이디·이름은 필수이며 부서·직급·이메일·연락처는 선택입니다. 기존 아이디·이름 2열 양식도 사용할 수 있습니다. 참여자 아이디 앞에는 회사 식별정보가 자동으로 붙습니다. 임시 비밀번호는 모두 kma이며, 첫 로그인 때 변경해야 합니다.")
        st.download_button("CSV 양식 내려받기", "\ufefflogin_id,display_name,department,job_title,email,phone\nuser001,참여자1,,,,\nuser002,참여자2,,,,\n".encode("utf-8"), "tap_participants_template.csv", "text/csv", key=PREFIX + "batch_template")
        upload = st.file_uploader("참여자 CSV", type=["csv"], key=PREFIX + "batch_upload")
        if upload is None:
            return
        try:
            rows = parse_participant_csv(upload.getvalue(), str(company["slug"]))
        except ValueError as exc:
            st.error(str(exc))
            return
        existing = {str(row["login_id"]).lower() for row in users}
        duplicate_count = sum(row["login_id"] in existing for row in rows)
        st.dataframe([{"로그인 아이디": row["login_id"], "이름": row["display_name"], **{label: row.get(key, "") for key, (label, _) in PROFILE_FIELDS.items()}, "등록": "기존 계정 · 제외" if row["login_id"] in existing else "새 계정"} for row in rows], hide_index=True, width="stretch")
        pending = [row for row in rows if row["login_id"] not in existing]
        if duplicate_count:
            st.info(f"이미 등록된 {duplicate_count}개 계정은 변경하지 않습니다.")
        if st.button(f"새 참여자 {len(pending)}명 등록", disabled=not pending, key=PREFIX + "batch_create"):
            issued: list[dict[str, str]] = []
            failures: list[str] = []
            with st.spinner("참여자 계정을 발급하고 있습니다."):
                for row in pending:
                    password = _temporary_password("participant")
                    try:
                        store.create_user(token, row["login_id"], row["display_name"], "participant", _identifier(company), password, profile={key: row.get(key, "") for key in PROFILE_FIELDS})
                    except Exception as exc:
                        LOGGER.error("Participant batch account creation failed: %s", type(exc).__name__)
                        failures.append(f"{row['login_id']}: {_safe_error(exc)}")
                        if type(exc).__name__ in {"AuthenticationError", "AuthorizationError", "RateLimitError"}:
                            break
                    else:
                        issued.append({"login_id": row["login_id"], "display_name": row["display_name"], "temp_password": password})
                        _remember_credentials([issued[-1]], principal)
            _notice(f"참여자 {len(issued)}명 계정을 발급했습니다.")
            if failures:
                st.session_state[PREFIX + "batch_failures"] = failures
            st.rerun()


def _render_manage_users(store: Any, token: str, principal: Mapping[str, Any], users: list[dict[str, Any]]) -> None:
    st.subheader("계정 관리")
    allowed = [row for row in users if row.get("role") in {"company", "participant"} and _identifier(row) != _identifier(principal)]
    if principal.get("role") == "company":
        allowed = [row for row in allowed if row.get("role") == "participant"]
    if not allowed:
        st.info("관리할 계정이 없습니다.")
        return
    st.dataframe([{"로그인 아이디": row["login_id"], "이름": row.get("display_name", ""), "역할": ROLE_LABELS.get(row["role"], ""), "회사": row.get("company_name", ""), **{label: row.get(key, "") for key, (label, _) in PROFILE_FIELDS.items()}, "상태": "사용 중" if row.get("active", True) else "중지"} for row in allowed], hide_index=True, width="stretch")
    by_id = {_identifier(row): row for row in allowed}
    selected = st.selectbox("관리할 계정", list(by_id), format_func=lambda value: f"{by_id[value]['display_name']} · {by_id[value]['login_id']}", key=PREFIX + "manage_user")
    user = by_id[selected]
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


def _render_project_create(store: Any, token: str) -> None:
    st.subheader("교육평가 프로젝트 만들기")
    st.caption("교육 전·후 비교에 사용할 일정과 측정역량을 등록합니다. 등록한 검사 구성은 고정됩니다.")
    rows = load_competencies()
    target_level = st.radio("응답 대상", list(LEVEL_LABELS), format_func=LEVEL_LABELS.get, horizontal=True, key=PREFIX + "target_level")
    available = [row for row in rows if row["active_for_scoring"] and applicable_to_level(row, target_level)]
    base = [row for row in available if row["library_type"] == "base"]
    st.write("기본역량: " + " · ".join(row["factor_name_ko"] for row in base))
    labels = {row["factor_code"]: row["factor_name_ko"] for row in available}
    specialty = st.multiselect(f"전문·미래역량 · 최대 {MAX_SPECIALTY}개", [row["factor_code"] for row in available if row["library_type"] == "specialty"], format_func=labels.get, max_selections=MAX_SPECIALTY, key=PREFIX + f"specialty_{target_level}")
    job = st.multiselect(f"직무역량 · 최대 {MAX_JOB_FUNCTION}개", [row["factor_code"] for row in available if row["library_type"] == "job_function"], format_func=labels.get, max_selections=MAX_JOB_FUNCTION, key=PREFIX + f"job_{target_level}")
    selected = [row["factor_code"] for row in base] + specialty + job
    st.caption(f"측정역량 {len(selected)}개 · {len(questions_for_factors(selected))}문항")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    with st.form(PREFIX + "project_create"):
        name = st.text_input("프로젝트명", max_chars=120)
        course_name = st.text_input("교육과정명", max_chars=120)
        training = st.date_input("교육일", today + timedelta(days=8))
        left, right = st.columns(2)
        with left:
            pre_start = st.date_input("교육 전 검사 시작일", today)
            post_start = st.date_input("교육 후 검사 시작일", today + timedelta(days=64))
        with right:
            pre_end = st.date_input("교육 전 검사 마감일", today + timedelta(days=7))
            post_end = st.date_input("교육 후 검사 마감일", today + timedelta(days=71))
        st.caption("검사 기간은 한국시간 기준입니다. 교육 후 검사는 교육 8~10주 후 시작을 권장합니다.")
        target_mean = st.slider("조직 기대 행동빈도", 1.0, 5.0, 3.5, 0.1, help="교육 우선순위 논의를 위한 운영 목표이며 표준 규준이 아닙니다.")
        priorities = st.multiselect("조직 우선역량 · 최대 3개", selected, format_func=labels.get, max_selections=3)
        delivery = st.radio("선호 교육방식", ["all", "offline", "online"], format_func={"all": "무관", "offline": "집합", "online": "온라인"}.get, horizontal=True)
        submitted = st.form_submit_button("프로젝트 등록", type="primary")
    if submitted:
        try:
            config = build_project_config(name, course_name, target_level, specialty + job, training, pre_start, pre_end, post_start, post_end, target_mean, priorities, delivery)
        except ValueError as exc:
            st.error(str(exc))
            return
        ok, _ = _attempt(lambda: store.create_project(token, name.strip(), config))
        if ok:
            _notice("프로젝트를 등록했습니다. 참여자를 배정하면 각 계정에서 검사를 진행할 수 있습니다.")
            st.rerun()


def _render_assignments(store: Any, token: str, project: Mapping[str, Any], users: list[dict[str, Any]]) -> None:
    project_id = _identifier(project)
    ok, assignments = _attempt(lambda: store.list_assignments(token, project_id))
    if not ok:
        return
    st.subheader("참여자 배정")
    if assignments:
        st.dataframe([{"이름": row.get("user_name", ""), "로그인 아이디": row.get("login_id", ""), "배정 상태": "배정 중" if row.get("active", True) else "배정 해제", "교육 전 검사": "완료" if row.get("pre_completed") else "미완료", "교육 후 검사": "완료" if row.get("post_completed") else "미완료"} for row in assignments], hide_index=True, width="stretch")
        with st.expander("참여자 배정 변경"):
            by_assignment = {str(row["id"]): row for row in assignments}
            assignment_id = st.selectbox("배정을 변경할 참여자", list(by_assignment), format_func=lambda value: f"{by_assignment[value].get('user_name', '')} · {by_assignment[value].get('login_id', '')}", key=PREFIX + f"assignment_change_{project_id}")
            active = bool(by_assignment[assignment_id].get("active", True))
            if st.button("프로젝트 배정 해제" if active else "프로젝트 다시 배정", key=PREFIX + f"assignment_toggle_{project_id}"):
                ok, _ = _attempt(lambda: store.set_assignment_active(token, assignment_id, not active))
                if ok:
                    _notice("프로젝트 배정을 해제했습니다. 기존 검사 결과는 보존됩니다." if active else "프로젝트에 다시 배정했습니다.")
                    st.rerun()
    assigned = {str(row["user_id"]) for row in assignments}
    candidates = {_identifier(row): row for row in users if row.get("role") == "participant" and row.get("active", True) and _identifier(row) not in assigned and str(row.get("company_id")) == str(project.get("company_id"))}
    if not candidates:
        st.info("배정할 새 참여자가 없습니다. 참여자 계정을 발급하거나 기존 배정 현황을 확인해 주세요.")
        return
    selected = st.multiselect("추가할 참여자", list(candidates), format_func=lambda value: f"{candidates[value]['display_name']} · {candidates[value]['login_id']}", key=PREFIX + f"assign_{project_id}")
    if st.button(f"선택한 {len(selected)}명 배정", disabled=not selected, key=PREFIX + f"assign_save_{project_id}"):
        count = 0
        for user_id in selected:
            ok, _ = _attempt(lambda user_id=user_id: store.assign_participant(token, project_id, user_id))
            if not ok:
                break
            count += 1
        if count:
            _notice(f"참여자 {count}명을 배정했습니다.")
        if count == len(selected):
            st.rerun()


def _render_projects(store: Any, token: str, principal: Mapping[str, Any], projects: list[dict[str, Any]], users: list[dict[str, Any]]) -> None:
    st.subheader("프로젝트 현황")
    if not projects:
        st.info("등록된 프로젝트가 없습니다.")
        return
    by_id = {_identifier(row): row for row in projects}
    selected = st.selectbox("프로젝트 선택", list(by_id), format_func=lambda value: str(by_id[value].get("name") or by_id[value].get("project_name") or "교육평가 프로젝트") + (f" · {by_id[value]['company_name']}" if by_id[value].get("company_name") else ""), key=PREFIX + "project_select")
    project = by_id[selected]
    config = project.get("config", {})
    if config:
        st.caption(f"교육일 {config.get('training_date', '미설정')} · 사전 {config.get('pre_start_date', '')} ~ {config.get('pre_end_date', '')} · 사후 {config.get('post_start_date', '')} ~ {config.get('post_end_date', '')}")
    if principal.get("role") == "company":
        _render_assignments(store, token, project, users)
    from tap.account_reports import render_project_report
    render_project_report(store, token, project)


def render_admin(store: Any, token: str, principal: Mapping[str, Any]) -> None:
    """Render administrative controls; AccountStore enforces every permission."""
    role = principal.get("role")
    if role not in {"kma", "company"}:
        st.error("관리자 계정으로 로그인해 주세요.")
        return
    st.title("회원사·계정 관리" if role == "kma" else "교육 운영 관리")
    if notice := st.session_state.pop(PREFIX + "notice", None):
        st.success(notice)
    if failures := st.session_state.pop(PREFIX + "batch_failures", None):
        st.warning("일부 계정은 등록하지 못했습니다. 성공한 계정의 로그인 정보를 먼저 확인한 뒤 실패한 행을 다시 등록해 주세요.")
        for failure in failures:
            st.write(failure)
    _render_credentials(principal)
    ok, companies = _attempt(lambda: store.list_companies(token))
    if not ok:
        return
    ok, users = _attempt(lambda: store.list_users(token))
    if not ok:
        return
    ok, projects = _attempt(lambda: store.list_projects(token))
    if not ok:
        return
    company_names = {_identifier(row): str(row["name"]) for row in companies}
    projects = [{**row, "company_name": company_names.get(str(row.get("company_id")), "")} for row in projects]
    if role == "kma":
        company_tab, user_tab, project_tab = st.tabs(["회원사", "교육담당자·계정", "프로젝트 현황"], key=PREFIX + "kma_tabs", on_change="rerun")
        with company_tab:
            _render_companies(store, token, companies)
        with user_tab:
            active_companies = {_identifier(row): row for row in companies if row.get("active", True)}
            if active_companies:
                company_id = st.selectbox("계정을 발급할 회사", list(active_companies), format_func=lambda value: f"{active_companies[value]['name']} · {_company_registration_label(active_companies[value])}", key=PREFIX + "issue_company")
                _render_create_user(store, token, principal, active_companies[company_id], "company")
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
            _render_batch(store, token, principal, company, users)
            _render_manage_users(store, token, principal, users)
