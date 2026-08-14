from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from math import isfinite
from typing import Any, Mapping, MutableMapping

from tap.state import PARTICIPANT_ID_WIDGET_KEY


BASELINE_FORMAT = "tap-pre-assessment-baseline"
BASELINE_SCHEMA_VERSION = 1
MAX_BASELINE_BYTES = 1_000_000
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_FIELDS = {
    "format",
    "schema_version",
    "assessment_phase",
    "completed",
    "participant_id",
    "project",
    "instrument",
    "selected_factors",
    "responses",
    "integrity",
}
_PROJECT_FIELDS = {
    "project_name",
    "course_name",
    "target_level",
    "training_date",
    "pre_end_date",
    "pre_completed_at",
    "target_means",
}
_INSTRUMENT_FIELDS = {
    "assessment_version",
    "question_snapshot_hash",
    "question_snapshot_codes",
    "response_scale",
}


class BaselineValidationError(ValueError):
    """Raised when a pre-assessment continuity file is unsafe or incompatible."""


def _checksum(payload: Mapping[str, Any]) -> str:
    checksum_payload = {key: value for key, value in payload.items() if key != "integrity"}
    canonical = json.dumps(
        checksum_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _invalid_id(participant_id: str) -> bool:
    return (
        not participant_id
        or len(participant_id) > 128
        or any(character in "\r\n\t\x00" for character in participant_id)
    )


def _clean_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise BaselineValidationError(f"{label} 정보가 없거나 올바르지 않습니다.")
    cleaned = [str(item).strip() for item in value]
    if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
        raise BaselineValidationError(f"{label}에는 비어 있거나 중복된 값이 없어야 합니다.")
    return cleaned


def _validated_responses(value: Any, expected_codes: list[str]) -> dict[str, int]:
    if not isinstance(value, dict):
        raise BaselineValidationError("사전검사 문항 응답 형식이 올바르지 않습니다.")

    responses: dict[str, int] = {}
    for raw_code, raw_score in value.items():
        code = str(raw_code).strip()
        if not code:
            raise BaselineValidationError("문항 코드가 비어 있습니다.")
        if isinstance(raw_score, bool) or not isinstance(raw_score, int) or not 0 <= raw_score <= 5:
            raise BaselineValidationError(
                f"{code} 응답값이 허용 범위(정수 0~5)를 벗어났습니다."
            )
        responses[code] = raw_score

    expected = set(expected_codes)
    actual = set(responses)
    if actual != expected:
        missing = len(expected - actual)
        extra = len(actual - expected)
        raise BaselineValidationError(
            "완료된 사전검사의 전체 문항 응답이 필요합니다"
            f"(누락 {missing}개, 알 수 없는 문항 {extra}개)."
        )
    return responses


def _state_context(state: Mapping[str, Any]) -> tuple[list[str], list[str], str, str]:
    selected_factors = [str(item).strip() for item in state.get("selected_factors", [])]
    snapshot_codes = [str(item).strip() for item in state.get("question_snapshot_codes", [])]
    assessment_version = str(state.get("assessment_version", "")).strip()
    snapshot_hash = str(state.get("question_snapshot_hash", "")).strip().lower()
    return selected_factors, snapshot_codes, assessment_version, snapshot_hash


def build_pre_baseline_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build a portable, item-level pre-assessment baseline.

    The payload intentionally contains no name, email, employee number, or
    other direct identifier. ``participant_id`` is the pseudonymous matching
    key entered by the learner.
    """

    participant_id = str(state.get("participant_id", "")).strip()
    if not participant_id:
        raise BaselineValidationError("교육 참여자 ID가 없어 기준파일을 만들 수 없습니다.")
    if _invalid_id(participant_id):
        raise BaselineValidationError("교육 참여자 ID 형식이 올바르지 않습니다.")

    selected_factors, snapshot_codes, assessment_version, snapshot_hash = _state_context(state)
    selected_factors = _clean_string_list(selected_factors, "선택 역량")
    snapshot_codes = _clean_string_list(snapshot_codes, "문항 스냅샷")
    if not assessment_version:
        raise BaselineValidationError("검사 버전 정보가 없어 기준파일을 만들 수 없습니다.")
    if not _SHA256_PATTERN.fullmatch(snapshot_hash):
        raise BaselineValidationError("문항 스냅샷 해시가 올바르지 않습니다.")

    completed_by_phase = state.get("assessment_completed_by_phase", {})
    if not isinstance(completed_by_phase, Mapping) or completed_by_phase.get("pre") is not True:
        raise BaselineValidationError("완료된 교육 전 검사만 기준파일로 저장할 수 있습니다.")
    responses_by_phase = state.get("responses_by_phase", {})
    if not isinstance(responses_by_phase, Mapping):
        raise BaselineValidationError("사전검사 응답 저장소가 올바르지 않습니다.")
    responses = _validated_responses(responses_by_phase.get("pre"), snapshot_codes)

    target_means = state.get("target_means", {})
    project = {
        "project_name": str(state.get("project_name", "")).strip(),
        "course_name": str(state.get("course_name", "")).strip(),
        "target_level": str(state.get("target_level", "")).strip(),
        "training_date": str(state.get("training_date", "")).strip(),
        "pre_end_date": str(state.get("pre_end_date", "")).strip(),
        "pre_completed_at": str(
            dict(state.get("assessment_completed_at_by_phase") or {}).get("pre")
            or state.get("pre_end_date", "")
        ).strip(),
        "target_means": dict(target_means) if isinstance(target_means, Mapping) else {},
    }
    payload = {
        "format": BASELINE_FORMAT,
        "schema_version": BASELINE_SCHEMA_VERSION,
        "assessment_phase": "pre",
        "completed": True,
        "participant_id": participant_id,
        "project": project,
        "instrument": {
            "assessment_version": assessment_version,
            "question_snapshot_hash": snapshot_hash,
            "question_snapshot_codes": snapshot_codes,
            "response_scale": {"minimum": 0, "maximum": 5},
        },
        "selected_factors": selected_factors,
        "responses": responses,
    }
    payload["integrity"] = {
        "algorithm": "sha256",
        "checksum": _checksum(payload),
        "assurance": "checksum-only-not-a-signature",
    }
    return payload


def pre_baseline_json_bytes(state: Mapping[str, Any]) -> bytes:
    """Serialize a validated pre-assessment baseline as UTF-8 JSON."""

    payload = build_pre_baseline_payload(state)
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def validate_pre_baseline(
    raw: bytes | str,
    current_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Parse and validate a baseline against the active post instrument."""

    if str(current_state.get("assessment_phase", "")).lower() != "post":
        raise BaselineValidationError("사전 기준파일은 교육 후 검사에서만 불러올 수 있습니다.")

    if isinstance(raw, bytes):
        if len(raw) > MAX_BASELINE_BYTES:
            raise BaselineValidationError("기준파일이 허용 크기(1MB)를 초과했습니다.")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BaselineValidationError("UTF-8 JSON 파일만 불러올 수 있습니다.") from exc
    elif isinstance(raw, str):
        if len(raw.encode("utf-8")) > MAX_BASELINE_BYTES:
            raise BaselineValidationError("기준파일이 허용 크기(1MB)를 초과했습니다.")
        text = raw
    else:
        raise BaselineValidationError("기준파일 데이터 형식이 올바르지 않습니다.")

    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise BaselineValidationError("올바른 TAP 사전검사 JSON 파일이 아닙니다.") from exc
    if not isinstance(payload, dict):
        raise BaselineValidationError("기준파일의 최상위 형식이 올바르지 않습니다.")
    if set(payload) != _TOP_LEVEL_FIELDS:
        raise BaselineValidationError("기준파일 필드 구성이 TAP 스키마와 일치하지 않습니다.")
    if payload.get("format") != BASELINE_FORMAT or payload.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise BaselineValidationError("지원하지 않는 TAP 기준파일 형식 또는 버전입니다.")
    if payload.get("assessment_phase") != "pre" or payload.get("completed") is not True:
        raise BaselineValidationError("완료된 교육 전 검사 기준파일만 불러올 수 있습니다.")

    participant_id = str(payload.get("participant_id", "")).strip()
    if _invalid_id(participant_id):
        raise BaselineValidationError("기준파일의 교육 참여자 ID가 올바르지 않습니다.")

    integrity = payload.get("integrity")
    if not isinstance(integrity, dict) or set(integrity) != {
        "algorithm",
        "checksum",
        "assurance",
    }:
        raise BaselineValidationError("기준파일의 무결성 정보가 올바르지 않습니다.")
    supplied_checksum = str(integrity.get("checksum", "")).lower()
    if (
        integrity.get("algorithm") != "sha256"
        or integrity.get("assurance") != "checksum-only-not-a-signature"
        or not _SHA256_PATTERN.fullmatch(supplied_checksum)
        or supplied_checksum != _checksum(payload)
    ):
        raise BaselineValidationError(
            "파일 내용이 저장 이후 변경되었거나 손상되었습니다. SHA-256은 전자서명이 아닌 변경 확인용 검사값입니다."
        )

    payload_factors = _clean_string_list(payload.get("selected_factors"), "선택 역량")
    project = payload.get("project")
    if not isinstance(project, dict) or set(project) != _PROJECT_FIELDS:
        raise BaselineValidationError("프로젝트 메타데이터 구성이 올바르지 않습니다.")
    if any(
        not isinstance(project[field], str)
        for field in _PROJECT_FIELDS - {"target_means"}
    ) or not isinstance(project.get("target_means"), dict):
        raise BaselineValidationError("프로젝트 메타데이터 값의 형식이 올바르지 않습니다.")

    try:
        baseline_targets = {
            str(code): round(float(value), 6)
            for code, value in project["target_means"].items()
        }
        current_targets = {
            str(code): round(float(value), 6)
            for code, value in dict(current_state.get("target_means") or {}).items()
        }
    except (TypeError, ValueError) as exc:
        raise BaselineValidationError("프로젝트 목표값 형식이 올바르지 않습니다.") from exc
    if any(not isfinite(value) or not 1 <= value <= 5 for value in baseline_targets.values()):
        raise BaselineValidationError("프로젝트 목표값은 1~5 범위의 유한한 수여야 합니다.")
    if baseline_targets != current_targets:
        raise BaselineValidationError(
            "기준파일의 역량 목표값이 현재 프로젝트와 일치하지 않습니다. "
            "교육 전 검사에 사용한 프로젝트를 먼저 선택해 주세요."
        )

    project_identity_fields = {
        "project_name": "프로젝트명",
        "course_name": "교육과정명",
        "target_level": "대상 직급",
        "training_date": "교육일",
        "pre_end_date": "사전검사 종료일",
    }
    for field, label in project_identity_fields.items():
        baseline_value = str(project.get(field, "")).strip()
        current_value = str(current_state.get(field, "")).strip()
        if baseline_value != current_value:
            raise BaselineValidationError(
                f"기준파일의 {label}이 현재 프로젝트와 일치하지 않습니다. "
                "교육 전 검사에 사용한 프로젝트를 먼저 선택해 주세요."
            )
    instrument = payload.get("instrument")
    if not isinstance(instrument, dict) or set(instrument) != _INSTRUMENT_FIELDS:
        raise BaselineValidationError("검사 도구 정보가 올바르지 않습니다.")
    if instrument.get("response_scale") != {"minimum": 0, "maximum": 5}:
        raise BaselineValidationError("기준파일의 응답 척도가 현재 지원 범위(0~5)와 다릅니다.")
    payload_codes = _clean_string_list(instrument.get("question_snapshot_codes"), "문항 스냅샷")
    payload_version = str(instrument.get("assessment_version", "")).strip()
    payload_hash = str(instrument.get("question_snapshot_hash", "")).strip().lower()
    if not _SHA256_PATTERN.fullmatch(payload_hash):
        raise BaselineValidationError("기준파일의 문항 스냅샷 해시가 올바르지 않습니다.")

    current_factors, current_codes, current_version, current_hash = _state_context(current_state)
    current_factors = _clean_string_list(current_factors, "현재 선택 역량")
    current_codes = _clean_string_list(current_codes, "현재 문항 스냅샷")
    if set(payload_factors) != set(current_factors):
        raise BaselineValidationError("교육 전·후 검사의 선택 역량이 일치하지 않습니다.")
    if payload_version != current_version:
        raise BaselineValidationError("교육 전·후 검사 버전이 일치하지 않습니다.")
    if payload_hash != current_hash or set(payload_codes) != set(current_codes):
        raise BaselineValidationError("교육 전·후 문항 스냅샷이 일치하지 않습니다.")

    responses = _validated_responses(payload.get("responses"), payload_codes)
    normalized = deepcopy(payload)
    normalized["participant_id"] = participant_id
    normalized["selected_factors"] = payload_factors
    normalized["instrument"]["question_snapshot_codes"] = payload_codes
    normalized["instrument"]["question_snapshot_hash"] = payload_hash
    normalized["responses"] = responses
    return normalized


def restore_pre_baseline(
    state: MutableMapping[str, Any],
    raw: bytes | str,
) -> dict[str, Any]:
    """Validate and restore a pre baseline without touching post responses."""

    payload = validate_pre_baseline(raw, state)
    participant_id = payload["participant_id"]
    responses = dict(payload["responses"])

    responses_by_phase = state.get("responses_by_phase")
    if not isinstance(responses_by_phase, MutableMapping):
        responses_by_phase = {"pre": {}, "post": {}}
        state["responses_by_phase"] = responses_by_phase
    existing_post = responses_by_phase.get("post")
    current_participant_id = str(state.get("participant_id", "")).strip()
    if existing_post and current_participant_id and current_participant_id != participant_id:
        raise BaselineValidationError(
            "현재 교육 후 응답이 다른 참여자 ID로 저장되어 있습니다. 교육 후 검사를 초기화한 뒤 다시 불러오세요."
        )

    completed_by_phase = state.get("assessment_completed_by_phase")
    if not isinstance(completed_by_phase, MutableMapping):
        completed_by_phase = {"pre": False, "post": False}
        state["assessment_completed_by_phase"] = completed_by_phase
    current_by_phase = state.get("current_question_by_phase")
    if not isinstance(current_by_phase, MutableMapping):
        current_by_phase = {"pre": 0, "post": 0}
        state["current_question_by_phase"] = current_by_phase
    completed_at_by_phase = state.get("assessment_completed_at_by_phase")
    if not isinstance(completed_at_by_phase, MutableMapping):
        completed_at_by_phase = {"pre": None, "post": None}
        state["assessment_completed_at_by_phase"] = completed_at_by_phase

    responses_by_phase["pre"] = responses
    completed_by_phase["pre"] = True
    current_by_phase["pre"] = max(len(responses) - 1, 0)
    completed_at_by_phase["pre"] = payload["project"]["pre_completed_at"]
    state["participant_id"] = participant_id
    state[PARTICIPANT_ID_WIDGET_KEY] = participant_id
    return payload
