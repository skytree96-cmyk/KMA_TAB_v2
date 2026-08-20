from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date
from html import escape
from time import time

import streamlit as st

from tap.runtime_guard import stop_on_stale


stop_on_stale(
    st,
    ("tap.baseline_transfer", "tap.github_demo_store", "tap.tenant", "tap.ui"),
)

from tap.baseline_transfer import BaselineValidationError, bootstrap_post_from_pre_baseline
from tap.config import LIKERT_OPTIONS
from tap.data import questions_for_factors
from tap.github_demo_store import (
    DemoStoreConfig,
    GitHubDemoStore,
    participant_key,
    project_payload_from_state,
    submission_payload_from_state,
)
from tap.state import (
    COMPANY_SCOPE_VERIFIED_KEY,
    DEMO_STORE_ACCESS_CODE_KEY,
    DEMO_STORE_ACCESS_CODE_WIDGET_KEY,
    PARTICIPANT_ID_WIDGET_KEY,
    activate_assessment_phase,
    ensure_state,
    load_demo_store_access_code_widget,
    load_participant_id_widget,
    reset_assessment,
    reset_all_assessments,
    save_demo_store_access_code_widget,
    save_participant_id_widget,
    sync_assessment_phase,
)
from tap.tenant import CompanyIdentity, TenantError
from tap.ui import callout, page_header, safe_switch_page, setup_page


setup_page("검사 참여", "2")
ensure_state(st.session_state)

# The two registered sidebar pages execute this shared implementation with a
# fixed phase. Reapply it on every Streamlit rerun so loading a stored project
# cannot overwrite the participant's explicit menu choice.
_forced_phase = globals().get("TAP_FORCED_ASSESSMENT_PHASE")
if _forced_phase in {"pre", "post"}:
    activate_assessment_phase(st.session_state, str(_forced_phase))
    st.session_state["current_assessment_phase"] = str(_forced_phase)


def _demo_access_code() -> str:
    return str(st.session_state.get(DEMO_STORE_ACCESS_CODE_KEY, "")).strip()


def _render_demo_store_access_gate(config: DemoStoreConfig) -> None:
    """Collect the shared planning-test code without blocking session/JSON use."""

    if not config.enabled:
        return
    load_demo_store_access_code_widget(st.session_state)
    st.text_input(
        "기획검증 접속코드",
        type="password",
        key=DEMO_STORE_ACCESS_CODE_WIDGET_KEY,
        on_change=save_demo_store_access_code_widget,
        args=(st.session_state,),
        help="합성 테스트 프로젝트 게시, 완료 결과 저장, 교육 전 결과 연결에만 사용합니다.",
    )
    if not config.write_enabled:
        st.caption("GitHub 쓰기 토큰 또는 서버 접속코드가 미설정되어 현 세션·JSON 방식으로만 진행됩니다.")
    elif config.access_granted(_demo_access_code()):
        st.caption("접속코드 확인 완료 · GitHub 합성 테스트 저장 기능을 사용할 수 있습니다.")
    elif _demo_access_code():
        st.warning("기획검증 접속코드가 일치하지 않습니다. 현 세션·JSON 데이터는 그대로 유지됩니다.")
    else:
        st.caption("GitHub 합성 테스트 저장·연결 기능을 사용하려면 전달받은 접속코드를 입력하세요.")


def _set_demo_store_notice(level: str, message: str) -> None:
    st.session_state["demo_store_notice"] = {"level": level, "message": message}


def _render_demo_store_notice() -> None:
    notice = st.session_state.pop("demo_store_notice", None)
    if not isinstance(notice, Mapping):
        return
    level = str(notice.get("level", "info"))
    message = str(notice.get("message", "")).strip()
    if message:
        getattr(st, level if level in {"success", "warning", "error", "info"} else "info")(message)


def _configured_demo_store() -> tuple[DemoStoreConfig | None, GitHubDemoStore | None]:
    try:
        config = DemoStoreConfig.from_sources(st.secrets)
    except Exception as exc:  # configuration errors must not break the session flow
        _set_demo_store_notice(
            "error",
            f"GitHub 테스트 저장 설정을 확인하지 못했습니다({type(exc).__name__}). 현 세션과 JSON 파일은 계속 사용할 수 있습니다.",
        )
        return None, None
    return (
        config,
        GitHubDemoStore(config, access_code=_demo_access_code()) if config.enabled else None,
    )


def _project_snapshot(payload: Mapping[str, object]) -> tuple[list[str], str, list[str]]:
    raw_selected = payload.get("selected_factors")
    if not isinstance(raw_selected, list) or not raw_selected:
        raise ValueError("선택 역량이 없습니다")
    selected = [str(value).strip() for value in raw_selected]
    if any(not value for value in selected) or len(selected) != len(set(selected)):
        raise ValueError("선택 역량 코드가 올바르지 않습니다")

    questions = questions_for_factors(selected)
    if not questions or {str(row["factor_code"]) for row in questions} != set(selected):
        raise ValueError("현재 문항은행에 없는 역량이 포함되어 있습니다")
    snapshot_rows = sorted(
        (
            str(row["question_code"]),
            str(row["revised_text"]),
            str(row.get("scoring_direction", "direct")),
        )
        for row in questions
    )
    snapshot_hash = hashlib.sha256(
        "\n".join("|".join(parts) for parts in snapshot_rows).encode("utf-8")
    ).hexdigest()
    expected_codes = [str(row["question_code"]) for row in questions]
    return selected, snapshot_hash, expected_codes


def _restore_demo_project(payload: Mapping[str, object], requested_code: str) -> str:
    """Restore only the project fields this assessment explicitly understands."""

    if str(payload.get("record_type", "")) != "project":
        raise ValueError("프로젝트 레코드가 아닙니다")
    project_id = str(payload.get("project_id", "")).strip()
    if not project_id or project_id.casefold() != requested_code.strip().casefold():
        raise ValueError("요청한 프로젝트 코드와 저장 데이터가 일치하지 않습니다")

    selected, snapshot_hash, expected_codes = _project_snapshot(payload)
    stored_hash = str(payload.get("question_snapshot_hash", ""))
    raw_codes = payload.get("question_snapshot_codes")
    if not isinstance(raw_codes, list):
        raise ValueError("문항 스냅샷 코드가 없습니다")
    stored_codes = [str(value) for value in raw_codes]
    if (
        stored_hash != snapshot_hash
        or len(stored_codes) != len(set(stored_codes))
        or set(stored_codes) != set(expected_codes)
        or str(payload.get("assessment_version", "")) != f"TAP-1.0+{snapshot_hash[:12]}"
    ):
        raise ValueError("현재 검사 버전·문항 스냅샷과 일치하지 않습니다")

    target_level = str(payload.get("target_level", ""))
    if target_level not in {"staff", "manager", "executive"}:
        raise ValueError("응답 대상이 올바르지 않습니다")
    parsed_dates: dict[str, str] = {}
    for key in (
        "project_start_date",
        "project_end_date",
        "training_date",
        "pre_start_date",
        "pre_end_date",
        "post_start_date",
        "post_end_date",
    ):
        value = str(payload.get(key, ""))
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("검사 일정이 올바르지 않습니다") from exc
        parsed_dates[key] = value
    if (
        parsed_dates["project_start_date"] != parsed_dates["pre_start_date"]
        or parsed_dates["project_end_date"] != parsed_dates["pre_end_date"]
        or not (
            parsed_dates["pre_start_date"]
            <= parsed_dates["pre_end_date"]
            < parsed_dates["training_date"]
            < parsed_dates["post_start_date"]
            <= parsed_dates["post_end_date"]
        )
    ):
        raise ValueError("교육 전·후 검사 일정의 순서가 올바르지 않습니다")

    raw_target_means = payload.get("target_means")
    if not isinstance(raw_target_means, Mapping):
        raise ValueError("목표점수 설정이 올바르지 않습니다")
    target_means: dict[str, float] = {}
    for code, raw_value in raw_target_means.items():
        code = str(code)
        if code not in selected:
            raise ValueError("선택하지 않은 역량의 목표점수가 포함되어 있습니다")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("목표점수 설정이 올바르지 않습니다") from exc
        if not 1.0 <= value <= 5.0:
            raise ValueError("목표점수 범위가 올바르지 않습니다")
        target_means[code] = value

    def selected_codes(key: str) -> list[str]:
        raw = payload.get(key)
        if not isinstance(raw, list):
            raise ValueError(f"{key} 설정이 올바르지 않습니다")
        values = [str(value) for value in raw]
        if len(values) > 3 or len(values) != len(set(values)) or not set(values) <= set(selected):
            raise ValueError(f"{key} 설정이 올바르지 않습니다")
        return values

    delivery_preference = str(payload.get("delivery_preference", "all"))
    if delivery_preference not in {"all", "offline", "online"}:
        raise ValueError("교육방식 설정이 올바르지 않습니다")
    allow_schedule_override = payload.get("allow_schedule_override")
    if not isinstance(allow_schedule_override, bool):
        raise ValueError("검사기간 예외 설정이 올바르지 않습니다")
    current_phase = str(payload.get("current_assessment_phase", "pre")).lower()
    if current_phase not in {"pre", "post"}:
        raise ValueError("검사 단계 설정이 올바르지 않습니다")

    raw_company_id = str(payload.get("company_id", "")).strip()
    company_values: dict[str, str]
    if raw_company_id:
        try:
            company = CompanyIdentity(
                company_id=raw_company_id,
                company_name=str(payload.get("company_name", "")).strip(),
                identity_source=str(
                    payload.get("company_identity_source", "")
                ).strip(),
            )
        except TenantError as exc:
            raise ValueError("프로젝트의 기업 범위 정보가 올바르지 않습니다") from exc
        if not company.company_name:
            raise ValueError("프로젝트의 회사명이 없습니다")
        company_values = {
            "company_id": company.company_id,
            "company_name": company.company_name,
            "company_identity_source": company.identity_source,
        }
    else:
        # Existing flat-path demo projects remain loadable, but may not inherit
        # a company scope left over from an earlier project in this browser.
        if any(
            str(payload.get(key, "")).strip()
            for key in ("company_name", "company_identity_source")
        ):
            raise ValueError("프로젝트의 기업 범위 정보가 불완전합니다")
        company_values = {
            "company_id": "",
            "company_name": "",
            "company_identity_source": "",
        }

    # No arbitrary payload keys are copied into session state. Responses and
    # participant identity always start empty for a newly loaded project.
    safe_values: dict[str, object] = {
        "project_id": project_id,
        "project_name": str(payload.get("project_name", "")).strip() or "이름 없는 교육평가 프로젝트",
        "course_name": str(payload.get("course_name", "")).strip() or "이름 없는 교육과정",
        **parsed_dates,
        "target_level": target_level,
        "selected_factors": selected,
        "target_means": target_means,
        "organization_priorities": selected_codes("organization_priorities"),
        "learner_interests": selected_codes("learner_interests"),
        "training_cause": "mixed_or_unknown",
        "delivery_preference": delivery_preference,
        "allow_schedule_override": allow_schedule_override,
        "question_snapshot_hash": snapshot_hash,
        "question_snapshot_codes": stored_codes,
        "assessment_version": f"TAP-1.0+{snapshot_hash[:12]}",
        "current_assessment_phase": current_phase,
        **company_values,
        # Loading a participant project is never equivalent to company-admin
        # verification.  The digest is intentionally not restored here.
        "company_access_digest": "",
    }
    reset_all_assessments(st.session_state)
    for key, value in safe_values.items():
        st.session_state[key] = value
    st.session_state["participant_id"] = ""
    st.session_state[COMPANY_SCOPE_VERIFIED_KEY] = False
    st.session_state.pop(PARTICIPANT_ID_WIDGET_KEY, None)
    activate_assessment_phase(st.session_state, current_phase)
    return project_id


def _load_demo_project(project_code: str) -> None:
    code = project_code.strip()
    if not code:
        st.error("프로젝트 코드를 입력해 주세요.")
        return
    config, store = _configured_demo_store()
    if config is None or store is None:
        st.error("GitHub 테스트 저장소가 설정되지 않아 프로젝트 코드를 불러올 수 없습니다.")
        return
    try:
        payload = store.load_project(code)
        if not isinstance(payload, Mapping):
            raise ValueError("해당 프로젝트를 찾지 못했습니다")
        restored_code = _restore_demo_project(payload, code)
    except Exception as exc:
        st.error(f"테스트 프로젝트를 불러오지 못했습니다: {exc}")
        return
    _set_demo_store_notice(
        "success",
        f"테스트 프로젝트 {restored_code}를 불러왔습니다. 교육 참여자 ID를 입력하고 검사를 시작해 주세요.",
    )
    st.rerun()


def _render_demo_project_entry() -> None:
    config, store = _configured_demo_store()
    if config is None or not config.enabled or store is None:
        st.info("GitHub 테스트 저장소가 미설정되어 현재 세션 또는 교육 전 기준파일(JSON)로 검사를 이어갑니다.")
        return
    try:
        query_value = st.query_params.get("project", "")
        query_code = str(query_value[0] if isinstance(query_value, list) and query_value else query_value).strip()
    except Exception:
        query_code = ""
    with st.container(border=True):
        st.markdown("### 테스트 프로젝트 코드로 시작")
        st.caption("교육담당자가 전달한 프로젝트 코드를 입력하면 일정·역량·동일 문항 스냅샷을 안전하게 불러옵니다.")
        _render_demo_store_access_gate(config)
        code = st.text_input(
            "프로젝트 코드",
            value=query_code,
            key="demo_project_code_input",
            placeholder="예: TAP-0123456789ABCDEF",
        )
        clicked = st.button("테스트 프로젝트 불러오기", type="primary", width="stretch")
    auto_load = bool(query_code) and st.session_state.get("demo_project_query_attempted") != query_code
    if auto_load:
        st.session_state["demo_project_query_attempted"] = query_code
    if clicked or auto_load:
        _load_demo_project(code or query_code)


def _restore_stored_pre_submission(
    payload: Mapping[str, object], expected_participant_key: str
) -> None:
    """Validate a stored snapshot and restore only its completed pre phase."""

    if str(payload.get("record_type", "")) != "submission":
        raise ValueError("검사결과 레코드가 아닙니다")
    if str(payload.get("project_id", "")) != str(st.session_state.get("project_id", "")):
        raise ValueError("프로젝트가 일치하지 않습니다")
    if str(payload.get("participant_key", "")) != expected_participant_key:
        raise ValueError("참여자 연결키가 일치하지 않습니다")
    stored_company_id = str(payload.get("company_id", "")).strip()
    current_company_id = str(st.session_state.get("company_id", "")).strip()
    if stored_company_id != current_company_id:
        raise ValueError("프로젝트의 기업 범위와 검사결과가 일치하지 않습니다")

    instrument = payload.get("instrument")
    if not isinstance(instrument, Mapping):
        raise ValueError("검사 도구 정보가 없습니다")
    stored_codes = instrument.get("question_snapshot_codes")
    stored_factors = instrument.get("selected_factors")
    response_scale = instrument.get("response_scale")
    if (
        str(instrument.get("assessment_version", ""))
        != str(st.session_state.get("assessment_version", ""))
        or str(instrument.get("question_snapshot_hash", ""))
        != str(st.session_state.get("question_snapshot_hash", ""))
        or not isinstance(stored_codes, list)
        or [str(value) for value in stored_codes]
        != [str(value) for value in st.session_state.get("question_snapshot_codes", [])]
        or not isinstance(stored_factors, list)
        or set(str(value) for value in stored_factors)
        != set(str(value) for value in st.session_state.get("selected_factors", []))
        or not isinstance(response_scale, Mapping)
        or response_scale.get("minimum") != 0
        or response_scale.get("maximum") != 5
    ):
        raise ValueError("현재 프로젝트의 검사 버전·문항 스냅샷과 일치하지 않습니다")

    phases = payload.get("phases")
    pre = phases.get("pre") if isinstance(phases, Mapping) else None
    if not isinstance(pre, Mapping) or pre.get("completed") is not True:
        raise ValueError("완료된 교육 전 검사결과가 없습니다")
    raw_responses = pre.get("responses")
    if not isinstance(raw_responses, Mapping):
        raise ValueError("교육 전 응답 형식이 올바르지 않습니다")
    responses = {str(code): score for code, score in raw_responses.items()}
    expected_codes = {str(value) for value in st.session_state.get("question_snapshot_codes", [])}
    if set(responses) != expected_codes or any(
        isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 5
        for score in responses.values()
    ):
        raise ValueError("교육 전 응답이 누락되었거나 허용 범위를 벗어났습니다")

    completed_at = pre.get("completed_at")
    if completed_at is not None:
        try:
            date.fromisoformat(str(completed_at))
        except ValueError as exc:
            raise ValueError("교육 전 완료일 형식이 올바르지 않습니다") from exc
    started_at = pre.get("started_at")
    duration_seconds = pre.get("duration_seconds")
    if started_at is not None and (
        isinstance(started_at, bool) or not isinstance(started_at, (int, float))
    ):
        raise ValueError("교육 전 시작시각 형식이 올바르지 않습니다")
    if duration_seconds is not None and (
        isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, (int, float))
        or duration_seconds < 0
    ):
        raise ValueError("교육 전 소요시간 형식이 올바르지 않습니다")

    st.session_state["responses_by_phase"]["pre"] = responses
    st.session_state["current_question_by_phase"]["pre"] = max(len(responses) - 1, 0)
    st.session_state["assessment_started_at_by_phase"]["pre"] = started_at
    st.session_state["assessment_completed_by_phase"]["pre"] = True
    st.session_state["assessment_completed_at_by_phase"]["pre"] = completed_at
    st.session_state["duration_seconds_by_phase"]["pre"] = duration_seconds
    activate_assessment_phase(st.session_state, "post")
    st.session_state["current_assessment_phase"] = "post"


def _render_stored_pre_submission_entry() -> None:
    config, store = _configured_demo_store()
    if config is None or store is None or not config.read_enabled:
        return
    with st.container(border=True):
        st.markdown("### 프로젝트 코드로 저장된 교육 전 결과 연결")
        st.caption(
            "교육 전 검사에서 사용한 추측하기 어려운 가명 교육 참여자 ID를 입력하면 원문 ID를 전송하지 않고 "
            "가명 연결키로 저장 결과를 조회합니다."
        )
        _render_demo_store_access_gate(config)
        load_participant_id_widget(st.session_state)
        st.text_input(
            "교육 참여자 ID",
            key=PARTICIPANT_ID_WIDGET_KEY,
            on_change=save_participant_id_widget,
            args=(st.session_state,),
            help="교육담당자가 무작위로 배정한 동일한 가명 ID를 입력하세요. 이름·사번은 사용하지 마세요. GitHub에는 원문 ID가 저장되지 않습니다.",
        )
        clicked = st.button("저장된 교육 전 결과 불러오기", type="primary", width="stretch")
    if not clicked:
        return
    if not config.write_enabled:
        st.error("GitHub 쓰기 토큰 또는 서버 접속코드가 미설정되어 저장 결과를 조회할 수 없습니다. 기준파일(JSON)을 사용해 주세요.")
        return
    if not config.access_granted(_demo_access_code()):
        st.error("기획검증 접속코드를 입력하거나 다시 확인해 주세요. 기준파일(JSON) 방식은 계속 사용할 수 있습니다.")
        return
    participant_id = str(st.session_state.get("participant_id", "")).strip()
    if not participant_id:
        st.error("교육 전 검사에서 사용한 교육 참여자 ID를 입력해 주세요.")
        return
    if not config.salt:
        st.error("참여자 연결용 salt가 설정되지 않아 저장 결과를 조회할 수 없습니다. 기준파일(JSON)을 사용해 주세요.")
        return
    try:
        pseudonym = participant_key(
            str(st.session_state.get("project_id", "")),
            participant_id,
            config.salt,
            company_id=str(st.session_state.get("company_id", "")).strip() or None,
        )
        payload = store.load_submission(
            str(st.session_state.get("project_id", "")),
            pseudonym,
            company_id=str(st.session_state.get("company_id", "")).strip() or None,
        )
        if not isinstance(payload, Mapping):
            raise ValueError("해당 참여자의 완료된 교육 전 결과를 찾지 못했습니다")
        _restore_stored_pre_submission(payload, pseudonym)
    except Exception as exc:
        st.error(f"저장된 교육 전 결과를 불러오지 못했습니다: {exc}")
        return
    _set_demo_store_notice(
        "success",
        "저장된 교육 전 검사결과를 안전하게 연결했습니다. 이제 교육 후 검사에 응답해 주세요.",
    )
    st.rerun()


def _retry_current_project_save() -> None:
    config, store = _configured_demo_store()
    if config is None or store is None or not config.write_enabled:
        _set_demo_store_notice("warning", "GitHub 쓰기 토큰 또는 서버 접속코드가 미설정되어 아직 저장할 수 없습니다. 현 세션·JSON 방식은 유지됩니다.")
        return
    if not config.access_granted(_demo_access_code()):
        _set_demo_store_notice("warning", "기획검증 접속코드를 입력하거나 다시 확인해 주세요. 현 세션·JSON 방식은 유지됩니다.")
        return
    try:
        store.save_project(project_payload_from_state(st.session_state))
    except Exception as exc:
        _set_demo_store_notice("error", f"GitHub 테스트 프로젝트 재저장에 실패했습니다({type(exc).__name__}).")
        return
    st.session_state["demo_store_project_pending"] = False
    _set_demo_store_notice("success", f"테스트 프로젝트 {st.session_state.get('project_id', '')}를 GitHub에 저장했습니다.")


def _save_completed_submission(phase: str) -> None:
    config, store = _configured_demo_store()
    if config is None or not config.enabled or store is None:
        st.session_state["demo_store_submission_pending_phase"] = None
        _set_demo_store_notice("info", "검사는 완료되었습니다. GitHub 저장소가 미설정되어 현 세션과 결과 파일 방식으로 보관합니다.")
        return
    if not config.write_enabled:
        st.session_state["demo_store_submission_pending_phase"] = phase
        _set_demo_store_notice("warning", "검사는 완료되었지만 GitHub 쓰기 토큰 또는 서버 접속코드가 미설정되어 결과를 저장하지 못했습니다. 현 세션·JSON 결과는 유지됩니다.")
        return
    if not config.access_granted(_demo_access_code()):
        st.session_state["demo_store_submission_pending_phase"] = phase
        _set_demo_store_notice("warning", "검사는 완료되었습니다. 기획검증 접속코드를 입력하거나 다시 확인하면 GitHub 저장을 재시도할 수 있으며, 현 세션·JSON 결과는 유지됩니다.")
        return
    try:
        store.save_submission(
            submission_payload_from_state(st.session_state, salt=config.salt)
        )
    except Exception as exc:
        st.session_state["demo_store_submission_pending_phase"] = phase
        _set_demo_store_notice("error", f"검사는 완료되었지만 GitHub 결과 저장에 실패했습니다({type(exc).__name__}). 아래에서 다시 시도할 수 있습니다.")
        return
    st.session_state["demo_store_submission_pending_phase"] = None
    _set_demo_store_notice("success", f"{phase_labels[phase]} 완료 결과를 GitHub 테스트 저장소에 누적했습니다.")


def _render_post_baseline_entry(*, key: str) -> None:
    """Restore a completed pre assessment before the post questionnaire starts."""
    with st.container(border=True):
        st.markdown("### 교육 후 검사 이어하기")
        st.markdown(
            "**1. 기준파일 선택 → 2. 교육 전 결과·참여자 ID 자동 복원 → "
            "3. 교육 후 검사 시작**"
        )
        st.caption(
            "교육 전 검사 완료 직후 개인 리포트에서 저장한 "
            "`tap_pre_baseline_…json` 파일을 선택하세요. "
            "일반 결과 JSON은 사용할 수 없습니다."
        )
        uploaded_baseline = st.file_uploader(
            "교육 전 검사 기준파일(JSON)",
            type=["json"],
            help=(
                "파일 안의 프로젝트·교육일·선택 역량·검사 버전·문항 스냅샷을 "
                "현재 문항은행과 확인한 뒤 교육 후 검사 상태를 자동으로 구성합니다."
            ),
            key=key,
        )
        if uploaded_baseline is None:
            return
        try:
            restored = bootstrap_post_from_pre_baseline(
                st.session_state,
                uploaded_baseline.getvalue(),
            )
        except BaselineValidationError as exc:
            st.error(f"기준파일을 불러오지 못했습니다: {exc}")
            return

        st.session_state["baseline_restore_notice"] = (
            f"교육 전 검사 {len(restored['responses'])}개 문항과 교육 참여자 ID를 "
            "복원했습니다. 이제 교육 후 검사에 응답해 주세요."
        )
        st.rerun()


if not st.session_state.selected_factors:
    bootstrap_phase = str(st.session_state.get("assessment_phase", "pre"))
    if _forced_phase not in {"pre", "post"}:
        # Backward-compatible landing for existing /assessment bookmarks.
        page_header(
            "검사 참여",
            "교육 전·후 검사 시작",
            "새 메뉴에서는 교육 전 검사와 교육 후 검사가 분리되어 있습니다. 기존 링크에서는 두 이어가기 방법을 모두 제공합니다.",
            badge="참여자",
        )
        _render_demo_project_entry()
        _render_post_baseline_entry(key="pre_baseline_bootstrap_uploader")
        st.markdown("#### 교육 전 검사를 시작하시나요?")
        st.caption("교육담당자가 먼저 교육과정·일정·측정역량을 설정해야 합니다.")
        if st.button("교육평가 프로젝트 설정으로 이동", type="primary"):
            st.switch_page("pages/1_project_setup.py")
    elif bootstrap_phase == "post":
        page_header(
            "검사 참여",
            "교육 후 검사 이어하기",
            "프로젝트 코드와 같은 교육 참여자 ID로 교육 전 완료결과를 연결하거나, 저장해 둔 기준파일을 불러오세요.",
            badge="교육 후",
        )
        _render_demo_project_entry()
        _render_post_baseline_entry(key="pre_baseline_bootstrap_uploader")
    else:
        page_header(
            "검사 참여",
            "교육 전 검사 시작",
            "교육담당자에게 받은 프로젝트 코드를 불러오거나, 이 브라우저에서 설정한 프로젝트로 시작합니다.",
            badge="교육 전",
        )
        _render_demo_project_entry()
        st.markdown("#### 교육 전 검사를 시작하시나요?")
        st.caption("교육담당자가 먼저 교육과정·일정·측정역량을 설정해야 합니다.")
        if st.button("교육평가 프로젝트 설정으로 이동", type="primary"):
            st.switch_page("pages/1_project_setup.py")
    st.stop()

phase = str(st.session_state.get("assessment_phase", "pre"))
if phase not in {"pre", "post"}:
    phase = "pre"
    st.session_state.assessment_phase = phase

phase_labels = {"pre": "교육 전 역량평가", "post": "교육 후 역량평가"}
phase_short_labels = {"pre": "교육 전", "post": "교육 후"}
period_start = st.session_state.get(f"{phase}_start_date", "미설정")
period_end = st.session_state.get(f"{phase}_end_date", "미설정")

questions = questions_for_factors(st.session_state.selected_factors)
if not questions:
    st.error("현재 프로젝트에서 응답할 문항을 찾지 못했습니다.")
    st.stop()

# 사전·사후의 문항과 제시 순서를 동일하게 고정해 문항 차이가 변화점수에 섞이지 않게 한다.
order_seed = str(st.session_state.get("project_name", "TAP"))
stored_order = [str(code) for code in st.session_state.get("question_snapshot_codes", [])]
question_by_code = {str(row["question_code"]): row for row in questions}
if stored_order and set(stored_order) == set(question_by_code):
    questions = [question_by_code[code] for code in stored_order]
else:
    questions = sorted(
        questions,
        key=lambda row: hashlib.sha256(f"{order_seed}|{row['question_code']}".encode("utf-8")).hexdigest(),
    )

snapshot_rows = sorted(
    (
        str(row["question_code"]),
        str(row["revised_text"]),
        str(row.get("scoring_direction", "direct")),
    )
    for row in questions
)
snapshot_hash = hashlib.sha256(
    "\n".join("|".join(parts) for parts in snapshot_rows).encode("utf-8")
).hexdigest()
stored_snapshot = str(st.session_state.get("question_snapshot_hash", ""))
if stored_snapshot and stored_snapshot != snapshot_hash:
    st.error("프로젝트 저장 후 문항 버전이 변경되어 비교를 중단했습니다. 교육담당자가 새 프로젝트로 다시 설정해 주세요.")
    st.stop()
if not stored_snapshot:
    st.session_state.question_snapshot_hash = snapshot_hash
    st.session_state.question_snapshot_codes = [str(row["question_code"]) for row in questions]
    st.session_state.assessment_version = f"TAP-1.0+{snapshot_hash[:12]}"

responses: dict[str, int] = st.session_state.responses
question_codes = {str(row["question_code"]) for row in questions}
answered = sum(code in responses for code in question_codes)
idx = min(max(int(st.session_state.current_question), 0), len(questions) - 1)
question = questions[idx]
completed_by_phase = st.session_state.get("assessment_completed_by_phase", {})
pre_complete = bool(completed_by_phase.get("pre", False))
post_complete = bool(completed_by_phase.get("post", False))

if phase == "post" and not pre_complete:
    page_header(
        "검사 참여",
        f"교육 후 검사 이어하기 · {st.session_state.get('course_name', '교육과정')}",
        "교육 전 검사 기준파일을 먼저 복원해야 동일 참여자·동일 문항의 변화를 비교할 수 있습니다.",
        badge="교육 후",
    )
    callout(
        "교육 전 검사 기준파일 필요",
        "교육 전 검사 완료 직후 저장한 기준파일을 선택하면 프로젝트와 참여자 ID가 자동으로 복원됩니다.",
        icon="!",
        tone="warn",
    )
    _render_stored_pre_submission_entry()
    st.caption("저장 결과를 사용할 수 없다면 아래 교육 전 검사 기준파일(JSON)로도 이어갈 수 있습니다.")
    _render_post_baseline_entry(key="pre_baseline_post_uploader")
    st.caption(
        "기준파일을 분실한 경우 현재 공개 데모에서는 교육 전·후 비교를 복원할 수 없습니다. "
        "교육담당자에게 문의해 주세요."
    )
    st.stop()

try:
    window_start = date.fromisoformat(str(period_start))
    window_end = date.fromisoformat(str(period_end))
except ValueError:
    window_start = window_end = None
today = date.today()
outside_window = bool(window_start and window_end and not (window_start <= today <= window_end))
if outside_window and not st.session_state.get("allow_schedule_override", True):
    st.warning(f"{phase_labels[phase]} 기간({period_start} ~ {period_end})이 아닙니다. 교육담당자에게 문의해 주세요.")
    st.stop()
if outside_window:
    st.caption(
        "공개 시연 환경 · 검사기간 예외가 허용되어 현재도 실제 검사 제출이 가능합니다. "
        "운영 전환 시 교육평가 프로젝트에서 예외 허용을 해제하세요."
    )

if st.session_state.assessment_started_at is None:
    st.session_state.assessment_started_at = time()
    sync_assessment_phase(st.session_state)

page_header(
    "검사 참여",
    f"{phase_labels[phase]} · {st.session_state.get('course_name', '교육과정')}",
    "사전·사후 모두 동일하게 최근 8주 동안 실제 업무에서 나타난 행동을 기준으로 응답해 주세요.",
    badge=phase_short_labels[phase],
)

demo_config, _ = _configured_demo_store()
if demo_config is not None and demo_config.enabled:
    with st.container(border=True):
        st.markdown("#### GitHub 기획검증 저장")
        _render_demo_store_access_gate(demo_config)

_render_demo_store_notice()
if st.session_state.get("demo_store_project_pending"):
    if st.button("GitHub 테스트 프로젝트 저장 다시 시도", width="stretch"):
        _retry_current_project_save()
        st.rerun()

restore_notice = st.session_state.pop("baseline_restore_notice", "")
if restore_notice:
    st.success(restore_notice)
    for warning in st.session_state.get("baseline_restore_warnings", []):
        st.warning(warning)

status_parts = [
    f"교육 전 {'완료' if pre_complete else '미완료'}",
    f"교육 후 {'완료' if post_complete else '미완료'}",
]
st.caption(
    f"검사 기간 {period_start} ~ {period_end} · 교육일 {st.session_state.get('training_date', '미설정')} "
    f"· {' · '.join(status_parts)}"
)

callout(
    "교육개발 목적의 자기보고형 변화검사",
    "양 시점의 동일 참여자·동일 문항 결과를 연결해 '교육 전후 관찰된 변화'를 봅니다. 채용·승진·보상·성과평가의 단독 판단자료로 사용하지 않습니다.",
    icon="i",
)

participant_id_missing = not str(st.session_state.get("participant_id", "")).strip()
load_participant_id_widget(st.session_state)
st.text_input(
    "교육 참여자 ID",
    key=PARTICIPANT_ID_WIDGET_KEY,
    on_change=save_participant_id_widget,
    args=(st.session_state,),
    disabled=pre_complete and not participant_id_missing,
    help="교육 전·후에 교육담당자가 무작위로 배정한 같은 가명 ID를 사용하세요. 이름·사번처럼 추측 가능한 직접 식별정보는 입력하지 마세요.",
)
if pre_complete and not participant_id_missing:
    st.caption("교육 전 검사에 사용한 ID로 자동 연결되어 변경할 수 없습니다.")
participant_id_missing = not str(st.session_state.get("participant_id", "")).strip()
if participant_id_missing:
    st.warning(
        "교육 전·후 결과를 연결할 교육 참여자 ID를 입력해 주세요. "
        "문항은 미리 볼 수 있지만 ID 입력 전에는 응답을 저장할 수 없습니다."
    )

def _finish_phase() -> None:
    """Complete and persist the active phase before opening its report."""
    st.session_state.assessment_completed = True
    st.session_state.assessment_completed_at_by_phase[phase] = date.today().isoformat()
    started = st.session_state.assessment_started_at or time()
    st.session_state.duration_seconds = max(0, time() - started)
    sync_assessment_phase(st.session_state)
    _save_completed_submission(phase)
    st.rerun()


def _render_transfer_environment() -> None:
    """Collect post-only context; these fields never enter competency scores."""
    stored = dict(st.session_state.get("post_transfer_responses", {}))
    st.progress(1.0, text=f"{len(questions)}/{len(questions)} 역량문항 응답 완료")
    st.markdown("### 현업전이 환경 확인")
    st.caption(
        "교육 내용을 실제 업무에 쓸 수 있었는지를 확인합니다. "
        "아래 응답은 역량점수에 합산하지 않고, 변화의 맥락과 후속조치를 정하는 데만 사용합니다."
    )
    transfer_options = [1, 2, 3, 4, 5]
    transfer_labels = {
        1: "전혀 그렇지 않다",
        2: "그렇지 않은 편이다",
        3: "보통이다",
        4: "그런 편이다",
        5: "매우 그렇다",
    }
    items = [
        ("application_opportunity", "교육에서 배운 내용을 업무에 적용할 기회가 있었다."),
        ("supervisor_support", "상사·리더가 배운 내용을 적용하도록 지원했다."),
        ("resources_authority", "적용에 필요한 도구·정보·권한이 충분했다."),
        ("time_process_support", "업무시간과 프로세스가 새로운 방식을 적용하기에 적합했다."),
    ]
    with st.form("post_transfer_environment_form"):
        values: dict[str, int] = {}
        for key, label in items:
            saved_value = stored.get(key)
            values[key] = st.radio(
                label,
                options=transfer_options,
                index=transfer_options.index(saved_value) if saved_value in transfer_options else None,
                format_func=lambda value: f"{value}. {transfer_labels[value]}",
                horizontal=True,
                key=f"transfer_{key}",
            )
        barriers = st.multiselect(
            "적용을 방해한 요인(복수 선택)",
            options=["적용 기회 부족", "상사·동료 지원 부족", "도구·정보·권한 부족", "시간·프로세스 제약", "특별한 방해요인 없음"],
            default=stored.get("barriers", []),
        )
        applied_content = st.text_area(
            "실제 업무에 적용한 교육 내용(선택)",
            value=str(stored.get("applied_content", "")),
            placeholder="예: 1:1 면담에서 질문·피드백 구조를 적용함",
        )
        submitted = st.form_submit_button("교육 후 검사 완료", type="primary", width="stretch")

    if submitted:
        if not str(st.session_state.get("participant_id", "")).strip():
            st.error("교육 참여자 ID를 입력한 뒤 교육 후 검사 완료를 다시 눌러 주세요.")
            return
        if any(value is None for value in values.values()):
            st.error("현업전이 항목 4개에 모두 응답해 주세요.")
            return
        st.session_state.post_transfer_responses = {
            **values,
            "barriers": barriers,
            "applied_content": applied_content.strip(),
        }
        _finish_phase()


if answered == len(questions) and phase == "post" and not st.session_state.assessment_completed:
    _render_transfer_environment()
    st.stop()

if st.session_state.assessment_completed:
    st.success(f"{phase_labels[phase]}가 완료되었습니다.")
    pending_phase = st.session_state.get("demo_store_submission_pending_phase")
    if pending_phase == phase:
        if st.button("GitHub 검사결과 저장 다시 시도", width="stretch"):
            _save_completed_submission(phase)
            st.rerun()
    if phase == "pre":
        result_col, post_col = st.columns(2)
        with result_col:
            if st.button("교육 전 결과 보기", width="stretch"):
                safe_switch_page("pages/3_individual_report.py")
        with post_col:
            if st.button("교육 후 검사로 이동", type="primary", width="stretch"):
                safe_switch_page("pages/8_post_assessment.py")
    elif st.button("교육 전·후 비교 리포트 보기", type="primary", width="stretch"):
        safe_switch_page("pages/3_individual_report.py")
    st.stop()

options = list(LIKERT_OPTIONS)
current_value = responses.get(question["question_code"])
with st.container(border=True):
    st.markdown('<span class="tap-question-stage-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="tap-assessment-progress-head">
          <div class="tap-assessment-progress-count"><b>{idx + 1}</b><span>/ {len(questions)}</span></div>
          <div class="tap-assessment-progress-status">{answered}개 응답 완료</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.progress((idx + 1) / len(questions))
    st.markdown(
        f"""
        <section class="tap-question-panel">
          <div class="tap-question-meta">
            <span class="tap-factor-pill">{escape(str(question['factor_name_ko']))}</span>
            <span class="tap-period-pill">최근 8주</span>
          </div>
          <p class="tap-question-number">{phase_short_labels[phase]} 업무행동 · 문항 {idx + 1}</p>
          <h2>{escape(question['revised_text'])}</h2>
        </section>
        """,
        unsafe_allow_html=True,
    )

    with st.form(f"question_form_{phase}_{question['question_code']}"):
        st.markdown(
            """
            <div class="tap-response-head tap-response-anchor">
              <b>얼마나 자주 했습니까?</b>
              <span>해당 행동을 할 상황이 없었다면 0을 선택하세요.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        choice = st.radio(
            "응답",
            options=options,
            index=options.index(current_value) if current_value in options else None,
            format_func=lambda value: LIKERT_OPTIONS[value],
            horizontal=True,
            label_visibility="collapsed",
        )
        if idx == len(questions) - 1:
            submit_label = "저장하고 현업전이 문항" if phase == "post" else "교육 전 결과 보기"
        else:
            submit_label = "다음 문항 →"
        submitted = st.form_submit_button(submit_label, type="primary", width="stretch")

    if submitted:
        if not str(st.session_state.get("participant_id", "")).strip():
            st.error("교육 참여자 ID를 입력한 뒤 다음 문항을 다시 눌러 주세요. 선택한 응답은 그대로 유지됩니다.")
        elif choice is None:
            st.error("응답을 선택해 주세요. 수행 기회가 없었다면 '수행 기회 없음'을 선택하세요.")
        else:
            responses[question["question_code"]] = int(choice)
            st.session_state.responses = responses
            if idx == len(questions) - 1:
                sync_assessment_phase(st.session_state)
                if phase == "post":
                    st.rerun()
                else:
                    _finish_phase()
            else:
                st.session_state.current_question = idx + 1
                sync_assessment_phase(st.session_state)
                st.rerun()

    left, right = st.columns(2)
    with left:
        if st.button("← 이전 문항", disabled=idx == 0, width="stretch"):
            st.session_state.current_question = idx - 1
            sync_assessment_phase(st.session_state)
            st.rerun()
    with right:
        with st.popover(f"{phase_short_labels[phase]} 검사 초기화", width="stretch"):
            st.write(f"현재 {phase_short_labels[phase]} 응답만 모두 지웁니다. 다른 시점의 응답은 유지됩니다.")
            if st.button("초기화 확인", type="secondary"):
                reset_assessment(st.session_state, phase)
                st.rerun()
