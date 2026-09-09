"""Account-bound participant assessments backed by the production store.

Only assignment records returned for the authenticated account enter this UI.
The active draft is reloaded on independent reruns. Form callbacks commit before
rendering the next question, without an additional rerun; the verified receipt
is consumed once by that render. Report records are never persistently cached.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from collections.abc import Mapping, MutableMapping
from datetime import date, datetime, timedelta, timezone
from time import time
from typing import Any

import streamlit as st

from tap.config import LIKERT_OPTIONS
from tap.data import questions_for_factors
from tap.scoring import score_pre_post_responses, score_responses


PREFIX = "_tap_participant_"
PHASE_LABELS = {"pre": "교육 전 검사", "post": "교육 후 검사"}
TRANSFER_ITEMS = (
    ("application_opportunity", "교육에서 배운 내용을 업무에 적용할 기회가 있었다."),
    ("supervisor_support", "상사·리더가 배운 내용을 적용하도록 지원했다."),
    ("resources_authority", "적용에 필요한 도구·정보·권한이 충분했다."),
    ("time_process_support", "업무시간과 프로세스가 새로운 방식을 적용하기에 적합했다."),
)
TRANSFER_LABELS = {
    1: "전혀 그렇지 않다", 2: "그렇지 않은 편이다", 3: "보통이다",
    4: "그런 편이다", 5: "매우 그렇다",
}
BARRIERS = (
    "적용 기회 부족", "상사·동료 지원 부족", "도구·정보·권한 부족",
    "시간·프로세스 제약", "특별한 방해요인 없음",
)


def _reset_scope(state: MutableMapping[str, Any], owner: str, assignment_id: str | None = None) -> None:
    """Discard all participant widgets when credentials or assignment change."""
    owner_changed = state.get(PREFIX + "owner") != owner
    assignment_changed = assignment_id is not None and state.get(PREFIX + "assignment") != assignment_id
    if not owner_changed and not assignment_changed:
        return
    keep = set() if owner_changed else {PREFIX + "owner", PREFIX + "selector"}
    for key in list(state):
        if str(key).startswith(PREFIX) and key not in keep:
            del state[key]
    state[PREFIX + "owner"] = owner
    if assignment_id is not None:
        state[PREFIX + "assignment"] = assignment_id


def _project_questions(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Use the assigned immutable text snapshot and verify its identity/hash."""
    selected = config.get("selected_factors")
    codes = config.get("question_snapshot_codes")
    if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected):
        raise ValueError("배정된 프로젝트의 측정역량 설정을 확인해 주세요.")
    base = questions_for_factors(selected)
    questions = config.get("question_snapshot", base)
    expected = {str(q["question_code"]): q for q in base}
    if not isinstance(questions, list) or not questions or len(questions) != len(expected):
        raise ValueError("배정된 검사 문항 스냅샷을 확인해 주세요.")
    for question in questions:
        reference = expected.get(str(question.get("question_code"))) if isinstance(question, Mapping) else None
        if (reference is None or question.get("factor_code") != reference["factor_code"]
                or question.get("scoring_direction", "direct") != reference.get("scoring_direction", "direct")
                or not isinstance(question.get("revised_text"), str) or not question["revised_text"].strip()):
            raise ValueError("배정된 검사 문항 스냅샷을 확인해 주세요.")
    if {q["factor_code"] for q in questions} != set(selected):
        raise ValueError("현재 문항은행에서 배정된 역량을 찾을 수 없습니다.")
    question_by_code = {str(q["question_code"]): q for q in questions}
    if not isinstance(codes, list) or len(set(codes)) != len(codes) or set(codes) != set(question_by_code):
        raise ValueError("배정된 검사 문항이 현재 문항은행과 일치하지 않습니다.")
    snapshot = sorted((str(q["question_code"]), str(q["revised_text"]), str(q.get("scoring_direction", "direct"))) for q in questions)
    digest = hashlib.sha256("\n".join("|".join(parts) for parts in snapshot).encode("utf-8")).hexdigest()
    if config.get("question_snapshot_hash") != digest:
        raise ValueError("프로젝트 생성 이후 문항이 변경되었습니다. 교육담당자에게 문의해 주세요.")
    version = config.get("assessment_version")
    if version and version != f"TAP-1.0+{digest[:12]}":
        raise ValueError("검사 버전이 일치하지 않습니다. 교육담당자에게 문의해 주세요.")
    return [question_by_code[code] for code in codes]


def _checked_record(record: Any, assignment_id: str, phase: str, question_codes: set[str]) -> dict[str, Any] | None:
    if record is None:
        return None
    if not isinstance(record, Mapping) or str(record.get("assignment_id")) != assignment_id or record.get("phase") != phase:
        raise ValueError("검사 저장 결과의 배정 정보가 일치하지 않습니다.")
    payload = record.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(record.get("completed"), bool):
        raise ValueError("검사 저장 결과를 확인하지 못했습니다.")
    responses = payload.get("responses", {})
    if not isinstance(responses, Mapping) or not set(responses) <= question_codes or any(type(v) is not int or not 0 <= v <= 5 for v in responses.values()):
        raise ValueError("저장된 검사 응답의 형식이 올바르지 않습니다.")
    if record["completed"] and set(responses) != question_codes:
        raise ValueError("완료된 검사에 누락된 응답이 있습니다. 교육담당자에게 문의해 주세요.")
    return dict(record)


def _error_message(action: str, exc: Exception) -> str:
    # Store validation errors contain useful user-facing messages. Unexpected
    # connection/runtime failures must not expose SQL or infrastructure details.
    detail = str(exc) if isinstance(exc, ValueError) else "잠시 후 다시 시도해 주세요. 계속되면 교육담당자에게 문의해 주세요."
    return f"{action} {detail}"


def _show_error(action: str, exc: Exception) -> None:
    st.error(_error_message(action, exc))


def _save(store: Any, token: str, assignment_id: str, phase: str, payload: dict[str, Any], completed: bool, codes: set[str], *, callback: bool = False, notify: bool = True) -> bool:
    try:
        receipt = _checked_record(store.save_assessment(token, assignment_id, phase, payload, completed), assignment_id, phase, codes)
        if receipt is None or receipt["completed"] is not completed or dict(receipt["payload"].get("responses", {})) != payload["responses"]:
            raise ValueError("저장 확인 응답이 일치하지 않아 다음 단계로 진행하지 않았습니다.")
        if "current_question" in payload and receipt["payload"].get("current_question") != payload["current_question"]:
            raise ValueError("저장된 진행 위치를 확인하지 못해 현재 문항을 유지했습니다.")
        if phase == "post" and dict(receipt["payload"].get("post_transfer_responses", {})) != dict(payload.get("post_transfer_responses", {})):
            raise ValueError("현업전이 응답의 저장을 확인하지 못했습니다.")
    except Exception as exc:
        if callback:
            st.session_state.pop(PREFIX + "saved_record", None)
            st.session_state[PREFIX + "error"] = _error_message("응답을 저장하지 못했습니다.", exc)
        else:
            _show_error("응답을 저장하지 못했습니다.", exc)
        return False
    if callback:
        st.session_state[PREFIX + "saved_record"] = {
            "owner": st.session_state[PREFIX + "owner"], "record": deepcopy(receipt),
        }
    if notify:
        st.session_state[PREFIX + "notice"] = "최종 제출이 완료되었습니다." if completed else "응답이 저장되었습니다. 다음에 로그인하면 이어서 참여할 수 있습니다."
    return True


def _choose_phase(phase: str) -> None:
    st.session_state[PREFIX + "phase"] = phase
    st.session_state[PREFIX + "focus"] = True


def _exit_focus() -> None:
    st.session_state[PREFIX + "focus"] = False


def _go_to_question(phase: str, cursor: int) -> None:
    st.session_state[PREFIX + phase + "_cursor"] = cursor


def _submit_question(store: Any, token: str, assignment_id: str, owner: str, phase: str, cursor: int,
                     question_code: str, codes: set[str]) -> None:
    """Save before Streamlit's automatic form rerun, never after an old render."""
    cursor_key = PREFIX + phase + "_cursor"
    # A queued click from an old project, account, phase, or question must not
    # overwrite the active draft or advance it a second time.
    if (st.session_state.get(PREFIX + "owner") != owner
            or st.session_state.get(PREFIX + "assignment") != assignment_id
            or st.session_state.get(PREFIX + "phase") != phase
            or st.session_state.get(cursor_key) != cursor):
        return
    choice = st.session_state.get(PREFIX + f"{phase}_response_{question_code}")
    if type(choice) is not int or choice not in LIKERT_OPTIONS:
        st.session_state[PREFIX + "error"] = "응답을 선택해 주세요. 수행 기회가 없었다면 0을 선택하세요."
        return
    st.session_state.pop(PREFIX + "saved_record", None)
    try:
        # Merge only this answer into the latest authorized server draft. A
        # form may have remained open while another browser saved other items.
        latest = _checked_record(store.load_assessment(token, assignment_id, phase), assignment_id, phase, codes)
        next_payload = _current_payload(latest, phase)
    except Exception as exc:
        st.session_state[PREFIX + "error"] = _error_message("현재 응답을 확인하지 못했습니다.", exc)
        return
    next_payload["responses"][question_code] = choice
    next_payload["current_question"] = cursor + 1
    next_payload["duration_seconds"] = max(0.0, time() - next_payload["started_at"])
    if _save(store, token, assignment_id, phase, next_payload, False, codes, callback=True, notify=False):
        st.session_state[cursor_key] = cursor + 1


def _current_payload(record: Mapping[str, Any] | None, phase: str) -> dict[str, Any]:
    saved = dict(record.get("payload", {})) if record else {}
    start_key = PREFIX + phase + "_started_at"
    if start_key not in st.session_state:
        st.session_state[start_key] = time()
    started = saved.get("started_at", st.session_state[start_key])
    if isinstance(started, bool) or not isinstance(started, (int, float)) or started <= 0:
        started = st.session_state[start_key]
    payload: dict[str, Any] = {
        "responses": dict(saved.get("responses", {})),
        "started_at": started,
        "duration_seconds": max(0.0, time() - started),
        "current_question": int(saved.get("current_question", 0)),
    }
    if phase == "post":
        payload["post_transfer_responses"] = dict(saved.get("post_transfer_responses", {}))
    return payload


def _render_results(questions: list[dict[str, Any]], config: Mapping[str, Any], pre: Mapping[str, Any], post: Mapping[str, Any] | None = None) -> None:
    targets = config.get("target_means", {})
    pre_responses = pre["payload"]["responses"]
    if post is not None and post.get("completed"):
        st.subheader("나의 교육 전·후 리포트")
        results = score_pre_post_responses(questions, pre_responses, post["payload"]["responses"], targets)
        st.dataframe([
            {"역량": r["factor_name_ko"], "교육 전(1~5)": r["pre_score"], "교육 후(1~5)": r["post_score"],
             "관찰 변화": r["self_reported_change"], "공통 유효문항": r["paired_valid_items"], "문항 수": r["total_items"], "산출 상태": r["status"]}
            for r in results
        ], hide_index=True, width="stretch")
        st.caption("두 시점 모두 1~5로 답한 동일 문항만 비교합니다. 0(수행 기회 없음)은 제외하며, 공통 유효문항이 부족한 역량은 산출하지 않습니다. 관찰된 자기보고 변화이며 교육의 인과효과를 뜻하지 않습니다.")
        chart_rows = [{"역량": r["factor_name_ko"], "시점": label, "행동빈도": r[key]}
                      for r in results for key, label in (("pre_score", "교육 전"), ("post_score", "교육 후"))
                      if r[key] is not None]
        if chart_rows:
            st.bar_chart(chart_rows, x="역량", y="행동빈도", color="시점", stack=False,
                         horizontal=True, height=max(240, len(results) * 64), width="stretch")
        transfer = post["payload"].get("post_transfer_responses", {})
        if transfer:
            with st.expander("내 현업전이 환경 응답"):
                for code, label in TRANSFER_ITEMS:
                    st.write(f"{label} — {TRANSFER_LABELS.get(transfer.get(code), '미응답')}")
                if transfer.get("barriers"):
                    st.write("적용 방해요인: " + ", ".join(transfer["barriers"]))
                if transfer.get("applied_content"):
                    st.write(transfer["applied_content"])
    else:
        st.subheader("나의 교육 전 검사 결과")
        results = score_responses(questions, pre_responses, targets, assessment_phase="pre")
        st.dataframe([
            {"역량": r["factor_name_ko"], "행동빈도(1~5)": r["score_1_to_5"], "유효문항": r["valid_items"],
             "수행 기회 없음": r["na_items"], "문항 수": r["total_items"], "산출 상태": r["status"]}
            for r in results
        ], hide_index=True, width="stretch")
        st.caption("0(수행 기회 없음)은 점수에 합산하지 않습니다. 유효응답이 부족한 역량은 산출하지 않습니다. 교육 후 검사까지 완료하면 동일 문항의 변화를 확인할 수 있습니다.")


def _render_review(store: Any, token: str, assignment_id: str, phase: str, questions: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    codes = {q["question_code"] for q in questions}
    st.progress(1.0, text=f"{len(questions)}/{len(questions)} 역량문항 응답 완료")
    with st.expander("제출 전 내 응답 확인", expanded=True):
        st.dataframe([
            {"문항": i + 1, "질문": q["revised_text"], "응답": LIKERT_OPTIONS[payload["responses"][q["question_code"]]]}
            for i, q in enumerate(questions)
        ], hide_index=True, width="stretch")
    st.button("역량문항 응답 수정", key=PREFIX + "review_back", on_click=_go_to_question, args=(phase, 0))
    st.caption("최종 제출 후에는 응답을 변경할 수 없습니다.")
    if phase == "pre":
        if st.button("교육 전 검사 최종 제출", type="primary", key=PREFIX + "finish_pre", width="stretch"):
            if _save(store, token, assignment_id, phase, payload, True, codes):
                st.rerun()
        return

    st.subheader("현업전이 환경 확인")
    st.caption("교육 내용을 실제 업무에 적용할 수 있었는지 확인합니다. 아래 응답은 역량점수에 합산하지 않고, 변화의 맥락과 후속조치에만 사용합니다.")
    stored = payload.get("post_transfer_responses", {})
    with st.form(PREFIX + "transfer_form"):
        values = {}
        for key, label in TRANSFER_ITEMS:
            value = stored.get(key)
            values[key] = st.radio(label, options=list(TRANSFER_LABELS), index=value - 1 if type(value) is int and 1 <= value <= 5 else None,
                                   format_func=lambda x: f"{x}. {TRANSFER_LABELS[x]}", horizontal=True, key=PREFIX + "transfer_" + key)
        barriers = st.multiselect("적용을 방해한 요인(복수 선택)", options=list(BARRIERS), default=stored.get("barriers", []), key=PREFIX + "barriers")
        applied = st.text_area("실제 업무에 적용한 교육 내용(선택)", value=str(stored.get("applied_content", "")), key=PREFIX + "applied", max_chars=2000)
        draft = st.form_submit_button("현업전이 응답 임시저장")
        finish = st.form_submit_button("교육 후 검사 최종 제출", type="primary", width="stretch")
    if not draft and not finish:
        return
    if "특별한 방해요인 없음" in barriers and len(barriers) > 1:
        st.error("'특별한 방해요인 없음'은 다른 방해요인과 함께 선택할 수 없습니다.")
        return
    if finish and any(v is None for v in values.values()):
        st.error("현업전이 항목 4개에 모두 응답해 주세요.")
        return
    payload["post_transfer_responses"] = {**{k: v for k, v in values.items() if v is not None}, "barriers": barriers, "applied_content": applied.strip()}
    if _save(store, token, assignment_id, phase, payload, bool(finish), codes):
        st.rerun()


def _render_question(store: Any, token: str, assignment_id: str, phase: str, questions: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    responses = payload["responses"]
    codes = {q["question_code"] for q in questions}
    cursor_key = PREFIX + phase + "_cursor"
    cursor = max(0, min(int(st.session_state.get(cursor_key, payload["current_question"])), len(questions)))
    if cursor == len(questions) and set(responses) != codes:
        cursor = next(i for i, q in enumerate(questions) if q["question_code"] not in responses)
    st.session_state[cursor_key] = cursor
    if cursor == len(questions):
        payload["current_question"] = cursor
        _render_review(store, token, assignment_id, phase, questions, payload)
        return
    question = questions[cursor]
    code = question["question_code"]
    current = responses.get(code)
    st.progress(len(responses) / len(questions), text=f"{len(responses)}/{len(questions)}문항 저장됨")
    with st.container(border=True, key=PREFIX + "question_stage"):
        st.caption(f"{question['factor_name_ko']} · 문항 {cursor + 1}/{len(questions)} · 최근 8주")
        st.subheader(question["revised_text"])
        st.write("얼마나 자주 했습니까? 해당 행동을 할 상황이 없었다면 0을 선택하세요.")
        with st.form(PREFIX + f"{phase}_question_{code}"):
            st.radio("응답", options=list(LIKERT_OPTIONS), index=list(LIKERT_OPTIONS).index(current) if current in LIKERT_OPTIONS else None,
                     format_func=lambda x: f"{x}. {LIKERT_OPTIONS[x]}", horizontal=True, key=PREFIX + f"{phase}_response_{code}")
            st.form_submit_button(
                "저장하고 제출 준비" if cursor == len(questions) - 1 else "저장하고 다음 문항 →",
                type="primary", width="stretch", on_click=_submit_question,
                args=(store, token, assignment_id, st.session_state[PREFIX + "owner"], phase, cursor, code, codes),
            )
        st.button("← 이전 문항", disabled=cursor == 0, key=PREFIX + phase + "_previous", on_click=_go_to_question, args=(phase, cursor - 1))


def render_participant(store: Any, token: str, principal: Mapping[str, Any]) -> None:
    """Render only this authenticated participant's assigned projects/results."""
    user_id = str(principal.get("id", ""))
    owner = hashlib.sha256(f"{token}|{user_id}".encode("utf-8")).hexdigest()
    _reset_scope(st.session_state, owner)
    # A verified commit receipt replaces only the read immediately following
    # that save. Pop before any early return; later reruns always reload the DB.
    saved_record = st.session_state.pop(PREFIX + "saved_record", None)
    try:
        assignments = store.list_assignments(token)
        if not isinstance(assignments, list) or any(not isinstance(a, Mapping) or str(a.get("user_id")) != user_id for a in assignments):
            raise ValueError("본인에게 배정된 프로젝트를 확인하지 못했습니다.")
        assignments = [a for a in assignments if a.get("active", True)]
    except Exception as exc:
        _reset_scope(st.session_state, owner, "")
        st.session_state[PREFIX + "focus"] = False
        _show_error("프로젝트를 불러오지 못했습니다.", exc)
        return
    if not assignments:
        _reset_scope(st.session_state, owner, "")
        st.info("아직 배정된 프로젝트가 없습니다. 교육담당자가 배정하면 이곳에 자동으로 표시됩니다.")
        return
    by_id = {str(a["id"]): a for a in assignments}
    selected = st.session_state.get(PREFIX + "assignment")
    if selected not in by_id:
        st.session_state[PREFIX + "focus"] = False
    focused = bool(st.session_state.get(PREFIX + "focus"))
    if not focused:
        st.title("나의 교육평가")
        st.caption(f"{principal.get('display_name') or principal.get('login_id') or '참여자'}님의 배정 프로젝트와 검사 결과입니다.")
    if focused:
        assignment_id = selected
    elif len(by_id) == 1:
        assignment_id = next(iter(by_id))
    else:
        selector = PREFIX + "selector"
        if st.session_state.get(selector) not in by_id:
            st.session_state.pop(selector, None)
        options = list(by_id)
        assignment_id = st.selectbox("참여할 프로젝트", options, index=options.index(selected) if selected in options else 0, format_func=lambda key: str(by_id[key]["project_name"]), key=selector)
    _reset_scope(st.session_state, owner, assignment_id)
    st.session_state.setdefault(PREFIX + "focus", False)
    assignment = by_id[assignment_id]
    config = assignment.get("config", {})
    try:
        if not isinstance(config, Mapping):
            raise ValueError("프로젝트 설정 형식이 올바르지 않습니다.")
        questions = _project_questions(config)
        codes = {q["question_code"] for q in questions}
    except Exception as exc:
        _show_error("검사를 불러오지 못했습니다.", exc)
        return
    # These flags come from this rerun's authorized assignment query. Read the
    # inactive phase's answers only when a completed comparison needs them.
    pre_complete = bool(assignment.get("pre_completed"))
    post_complete = bool(assignment.get("post_completed"))
    if not st.session_state.get(PREFIX + "focus"):
        st.subheader(str(assignment["project_name"]))
        st.caption(f"교육과정: {config.get('course_name', assignment['project_name'])} · 교육일: {config.get('training_date', '미설정')}")
        st.caption(f"교육 전 {'완료' if pre_complete else '미완료'} · 교육 후 {'완료' if post_complete else '미완료'}")
        if pre_complete and post_complete:
            st.button("나의 전·후 리포트 보기", key=PREFIX + "open_report", on_click=_choose_phase,
                      args=("post",), type="primary", width="stretch")
        before, after = st.columns(2)
        before.button("교육 전 검사", key=PREFIX + "enter_pre", on_click=_choose_phase, args=("pre",), type="primary", width="stretch")
        after.button("교육 후 검사", key=PREFIX + "enter_post", on_click=_choose_phase, args=("post",), width="stretch")
        return
    phase = st.session_state.get(PREFIX + "phase", "pre")
    if phase not in PHASE_LABELS:
        phase = "pre"
        st.session_state[PREFIX + "phase"] = phase
    st.html('<span class="tap-assessment-focus" aria-hidden="true"></span>')
    st.button("내 교육으로 돌아가기", key=PREFIX + "exit_focus", on_click=_exit_focus)
    st.caption(f"{PHASE_LABELS[phase]} · {assignment['project_name']}")
    # A permanent block keeps form/question positions stable when a save error
    # or completion message appears. Per-question progress already confirms save.
    with st.container(key=PREFIX + "messages"):
        notice = st.session_state.pop(PREFIX + "notice", "")
        error = st.session_state.pop(PREFIX + "error", "")
        if notice:
            st.success(notice)
        if error:
            st.error(error)
    try:
        receipt = saved_record.get("record") if isinstance(saved_record, Mapping) and saved_record.get("owner") == owner else None
        if (isinstance(receipt, Mapping) and str(receipt.get("assignment_id")) == assignment_id
                and receipt.get("phase") == phase
                and receipt.get("completed") == (pre_complete if phase == "pre" else post_complete)):
            active_record = _checked_record(receipt, assignment_id, phase, codes)
        else:
            active_record = _checked_record(store.load_assessment(token, assignment_id, phase), assignment_id, phase, codes)
    except Exception as exc:
        _show_error("검사를 불러오지 못했습니다.", exc)
        return
    if active_record and active_record["completed"]:
        st.success(f"{PHASE_LABELS[phase]}가 최종 제출되었습니다. 제출된 응답은 변경할 수 없습니다.")
        if phase == "pre":
            _render_results(questions, config, active_record)
        else:
            try:
                pre = _checked_record(store.load_assessment(token, assignment_id, "pre"), assignment_id, "pre", codes)
                if pre is None or not pre["completed"]:
                    raise ValueError("완료된 교육 전 검사 결과를 확인하지 못했습니다.")
            except Exception as exc:
                _show_error("비교 결과를 불러오지 못했습니다.", exc)
                return
            _render_results(questions, config, pre, active_record)
        if phase == "pre" and not post_complete:
            st.button("교육 후 검사 열기", on_click=_choose_phase, args=("post",), key=PREFIX + "open_post", type="primary")
        return
    if phase == "post" and not pre_complete:
        st.info("교육 전 검사를 먼저 완료해 주세요. 교육 후에는 같은 계정의 교육 전 결과가 자동으로 연결됩니다.")
        st.button("교육 전 검사로 이동", on_click=_choose_phase, args=("pre",), key=PREFIX + "open_pre", type="primary")
        return
    try:
        start = date.fromisoformat(str(config.get(f"{phase}_start_date", "")))
        end = date.fromisoformat(str(config.get(f"{phase}_end_date", "")))
        if start > end:
            raise ValueError("검사 시작일이 종료일보다 늦습니다.")
    except ValueError:
        st.error("검사 기간이 올바르게 설정되지 않았습니다. 교육담당자에게 문의해 주세요.")
        return
    today = datetime.now(timezone(timedelta(hours=9))).date()
    if not start <= today <= end:
        st.info("아직 검사 기간이 시작되지 않았습니다." if today < start else "검사 기간이 종료되었습니다. 교육담당자에게 문의해 주세요.")
        return
    st.caption("최근 8주 동안 실제 업무에서 나타난 행동을 기준으로 응답해 주세요.")
    _render_question(store, token, assignment_id, phase, questions, _current_payload(active_record, phase))
