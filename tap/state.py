from __future__ import annotations

from copy import deepcopy
from typing import Any, MutableMapping, cast


ASSESSMENT_PHASES = ("pre", "post")
PARTICIPANT_ID_WIDGET_KEY = "_participant_id_input"


DEFAULTS: dict[str, Any] = {
    "active_role": "company",
    "project_name": "2026 하반기 공통역량 진단",
    "project_id": "",
    "project_start_date": "2026-08-17",
    "project_end_date": "2026-08-28",
    "course_name": "공통역량 교육",
    "participant_id": "",
    "assessment_version": "TAP-1.0",
    "question_snapshot_hash": "",
    "question_snapshot_codes": [],
    "allow_schedule_override": True,
    "training_date": "2026-09-01",
    "pre_start_date": "2026-08-17",
    "pre_end_date": "2026-08-28",
    "post_start_date": "2026-10-27",
    "post_end_date": "2026-11-10",
    "target_level": "manager",
    "selected_factors": [],
    "assessment_phase": "pre",
    "responses_by_phase": {"pre": {}, "post": {}},
    "current_question_by_phase": {"pre": 0, "post": 0},
    "assessment_started_at_by_phase": {"pre": None, "post": None},
    "assessment_completed_by_phase": {"pre": False, "post": False},
    "assessment_completed_at_by_phase": {"pre": None, "post": None},
    "duration_seconds_by_phase": {"pre": None, "post": None},
    "post_transfer_responses": {},
    # The flat keys remain as aliases for the active phase so existing pages and
    # persisted Streamlit sessions keep working during the pre/post migration.
    "responses": {},
    "current_question": 0,
    "assessment_started_at": None,
    "assessment_completed": False,
    "duration_seconds": None,
    "target_means": {},
    "organization_priorities": [],
    "learner_interests": [],
    "training_cause": "mixed_or_unknown",
    "delivery_preference": "all",
}


def _normalise_phase(phase: Any) -> str:
    value = str(phase or "pre").lower()
    if value not in ASSESSMENT_PHASES:
        raise ValueError(f"assessment phase must be one of {ASSESSMENT_PHASES}, got {phase!r}")
    return value


def load_participant_id_widget(state: MutableMapping[str, Any]) -> str:
    """Restore the durable participant ID into a temporary widget key.

    Streamlit removes widget-owned keys when the user leaves their page. The
    canonical ``participant_id`` therefore remains application state while the
    text input uses a disposable key recreated for the post assessment.
    """
    participant_id = str(state.get("participant_id", ""))
    state[PARTICIPANT_ID_WIDGET_KEY] = participant_id
    return participant_id


def save_participant_id_widget(state: MutableMapping[str, Any]) -> str:
    """Persist the temporary participant-ID widget value across pages."""
    participant_id = str(state.get(PARTICIPANT_ID_WIDGET_KEY, "")).strip()
    state["participant_id"] = participant_id
    return participant_id


def _ensure_phase_mapping(
    state: MutableMapping[str, Any], key: str, default_value: Any
) -> MutableMapping[str, Any]:
    value = state.get(key)
    if not isinstance(value, MutableMapping):
        value = {}
        state[key] = value
    for phase in ASSESSMENT_PHASES:
        if phase not in value:
            value[phase] = deepcopy(default_value)
    return cast(MutableMapping[str, Any], value)


def _load_phase_aliases(state: MutableMapping[str, Any], phase: str) -> None:
    responses = _ensure_phase_mapping(state, "responses_by_phase", {})
    current_questions = _ensure_phase_mapping(state, "current_question_by_phase", 0)
    started_at = _ensure_phase_mapping(state, "assessment_started_at_by_phase", None)
    completed = _ensure_phase_mapping(state, "assessment_completed_by_phase", False)
    durations = _ensure_phase_mapping(state, "duration_seconds_by_phase", None)
    completed_at = _ensure_phase_mapping(state, "assessment_completed_at_by_phase", None)

    # Keep the response object shared, not merely copied. Existing code mutates
    # ``state.responses`` in-place; the phase store must see those writes.
    if not isinstance(responses[phase], dict):
        responses[phase] = dict(responses[phase] or {})
    state["responses"] = responses[phase]
    state["current_question"] = int(current_questions[phase] or 0)
    state["assessment_started_at"] = started_at[phase]
    state["assessment_completed"] = bool(completed[phase])
    state["duration_seconds"] = durations[phase]


def _save_phase_aliases(state: MutableMapping[str, Any], phase: str) -> None:
    responses = _ensure_phase_mapping(state, "responses_by_phase", {})
    current_questions = _ensure_phase_mapping(state, "current_question_by_phase", 0)
    started_at = _ensure_phase_mapping(state, "assessment_started_at_by_phase", None)
    completed = _ensure_phase_mapping(state, "assessment_completed_by_phase", False)
    durations = _ensure_phase_mapping(state, "duration_seconds_by_phase", None)

    flat_responses = state.get("responses", {})
    flat_responses = flat_responses if isinstance(flat_responses, dict) else dict(flat_responses or {})
    stored_responses = responses.get(phase)
    if isinstance(stored_responses, dict) and stored_responses is not flat_responses:
        # A caller may update the explicit phase store directly. Prefer a
        # populated phase map over a stale empty legacy alias; otherwise the
        # active flat API remains authoritative for backward compatibility.
        if stored_responses and not flat_responses:
            flat_responses = stored_responses
            state["responses"] = stored_responses
    responses[phase] = flat_responses
    current_questions[phase] = int(state.get("current_question", 0) or 0)
    started_at[phase] = state.get("assessment_started_at")
    completed[phase] = bool(state.get("assessment_completed", False))
    durations[phase] = state.get("duration_seconds")


def ensure_state(state: MutableMapping[str, Any]) -> None:
    original_keys = set(state.keys())
    for key, value in DEFAULTS.items():
        if key not in state:
            state[key] = deepcopy(value)

    # 프로젝트 생성 단계의 원인 사전판정은 제거됐다. 이전 세션의 숨은 값이
    # 새 추천 결과를 계속 차단하지 않도록 중립 상태로 마이그레이션한다.
    if state.get("training_cause") != "mixed_or_unknown":
        state["training_cause"] = "mixed_or_unknown"

    phase = _normalise_phase(state.get("assessment_phase"))
    state["assessment_phase"] = phase
    responses = _ensure_phase_mapping(state, "responses_by_phase", {})

    # One-time compatibility migration: legacy sessions only have the flat
    # response store. They represent a pre-training baseline.
    flat_responses = state.get("responses")
    if phase == "pre" and not responses["pre"] and isinstance(flat_responses, dict) and flat_responses:
        responses["pre"] = flat_responses
        _ensure_phase_mapping(state, "current_question_by_phase", 0)["pre"] = int(
            state.get("current_question", 0) or 0
        )
        _ensure_phase_mapping(state, "assessment_started_at_by_phase", None)["pre"] = state.get(
            "assessment_started_at"
        )
        _ensure_phase_mapping(state, "assessment_completed_by_phase", False)["pre"] = bool(
            state.get("assessment_completed", False)
        )
        _ensure_phase_mapping(state, "duration_seconds_by_phase", None)["pre"] = state.get(
            "duration_seconds"
        )
    # Canonical phase maps win when a serialized session is restored without
    # legacy flat keys. Only migrate scalar aliases when callers supplied them
    # explicitly; freshly inserted defaults must not overwrite stored progress.
    had_flat_progress = any(
        key in original_keys
        for key in ("current_question", "assessment_started_at", "assessment_completed", "duration_seconds")
    )
    if had_flat_progress and not any(
        bool(_ensure_phase_mapping(state, key, default).get(phase))
        for key, default in (
            ("current_question_by_phase", 0),
            ("assessment_started_at_by_phase", None),
            ("assessment_completed_by_phase", False),
            ("duration_seconds_by_phase", None),
        )
    ):
        _save_phase_aliases(state, phase)
    _load_phase_aliases(state, phase)


def activate_assessment_phase(state: MutableMapping[str, Any], phase: str) -> None:
    """Persist the active phase and expose ``phase`` through legacy flat keys."""
    ensure_state(state)
    current_phase = _normalise_phase(state.get("assessment_phase"))
    _save_phase_aliases(state, current_phase)
    selected_phase = _normalise_phase(phase)
    state["assessment_phase"] = selected_phase
    _load_phase_aliases(state, selected_phase)


def sync_assessment_phase(state: MutableMapping[str, Any]) -> None:
    """Save flat compatibility keys into the currently active phase store."""
    # Do not call ``ensure_state`` here.  ``ensure_state`` intentionally loads
    # the canonical phase map back into the flat compatibility aliases.  When
    # a page has just changed an alias (for example ``current_question``), that
    # reload would discard the new value before it can be persisted.  The save
    # helper creates/repairs every phase mapping it needs on its own.
    _save_phase_aliases(state, _normalise_phase(state.get("assessment_phase")))


def phase_responses(state: MutableMapping[str, Any], phase: str | None = None) -> dict[str, int]:
    """Return the mutable response dictionary for one assessment phase."""
    ensure_state(state)
    selected_phase = _normalise_phase(phase or state.get("assessment_phase"))
    responses = _ensure_phase_mapping(state, "responses_by_phase", {})
    if not isinstance(responses[selected_phase], dict):
        responses[selected_phase] = dict(responses[selected_phase] or {})
    return cast(dict[str, int], responses[selected_phase])


def reset_assessment(state: MutableMapping[str, Any], phase: str | None = None) -> None:
    """Reset one phase; omitting ``phase`` preserves the legacy active-phase API."""
    ensure_state(state)
    selected_phase = _normalise_phase(phase or state.get("assessment_phase"))
    responses = _ensure_phase_mapping(state, "responses_by_phase", {})
    current_questions = _ensure_phase_mapping(state, "current_question_by_phase", 0)
    started_at = _ensure_phase_mapping(state, "assessment_started_at_by_phase", None)
    completed = _ensure_phase_mapping(state, "assessment_completed_by_phase", False)
    durations = _ensure_phase_mapping(state, "duration_seconds_by_phase", None)
    completed_at = _ensure_phase_mapping(state, "assessment_completed_at_by_phase", None)

    responses[selected_phase] = {}
    current_questions[selected_phase] = 0
    started_at[selected_phase] = None
    completed[selected_phase] = False
    durations[selected_phase] = None
    completed_at[selected_phase] = None
    if selected_phase == "post":
        state["post_transfer_responses"] = {}
    if selected_phase == state.get("assessment_phase"):
        _load_phase_aliases(state, selected_phase)


def reset_all_assessments(state: MutableMapping[str, Any]) -> None:
    """Clear both phases when a project or question set changes."""
    ensure_state(state)
    reset_assessment(state, "pre")
    reset_assessment(state, "post")
    activate_assessment_phase(state, "pre")
