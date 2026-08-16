from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import date, timedelta
from math import isfinite
from typing import Any, Mapping, MutableMapping

from tap.data import questions_for_factors
from tap.runtime_guard import source_fingerprint
from tap.state import PARTICIPANT_ID_WIDGET_KEY


__tap_source_sha256__ = source_fingerprint(__file__)


BASELINE_FORMAT = "tap-pre-assessment-baseline"
BASELINE_SCHEMA_VERSION = 3
SUPPORTED_BASELINE_SCHEMA_VERSIONS = frozenset({1, 2, 3})
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
_PROJECT_FIELDS_V1 = {
    "project_name",
    "course_name",
    "target_level",
    "training_date",
    "pre_end_date",
    "pre_completed_at",
    "target_means",
}
_PROJECT_FIELDS_V2 = _PROJECT_FIELDS_V1 | {
    "project_id",
    "pre_start_date",
    "post_start_date",
    "post_end_date",
    "organization_priorities",
    "learner_interests",
    "delivery_preference",
}
_PROJECT_FIELDS_V3 = _PROJECT_FIELDS_V2 | {"allow_schedule_override"}
_PROJECT_FIELDS_BY_VERSION = {
    1: _PROJECT_FIELDS_V1,
    2: _PROJECT_FIELDS_V2,
    3: _PROJECT_FIELDS_V3,
}
_INSTRUMENT_FIELDS = {
    "assessment_version",
    "question_snapshot_hash",
    "question_snapshot_codes",
    "response_scale",
}
_DELIVERY_PREFERENCES = frozenset({"all", "offline", "online"})
_V2_LIST_FIELDS = frozenset({"organization_priorities", "learner_interests"})


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


def _clean_optional_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise BaselineValidationError(f"{label} 형식이 올바르지 않습니다.")
    if any(not isinstance(item, str) for item in value):
        raise BaselineValidationError(f"{label}은 문자열 목록이어야 합니다.")
    cleaned = [item.strip() for item in value]
    if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
        raise BaselineValidationError(f"{label}에는 빈 값이나 중복 값이 없어야 합니다.")
    return cleaned


def _parse_iso_date(value: Any, label: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise BaselineValidationError(f"{label}이 비어 있거나 올바르지 않습니다.")
    cleaned = value.strip()
    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError as exc:
        raise BaselineValidationError(f"{label}은 YYYY-MM-DD 형식이어야 합니다.") from exc
    if parsed.isoformat() != cleaned:
        raise BaselineValidationError(f"{label}은 YYYY-MM-DD 형식이어야 합니다.")
    return parsed


def _deterministic_project_id(prefix: str, material: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return prefix + hashlib.sha256(canonical).hexdigest()[:16].upper()


def _validate_project_schedule(
    project: Mapping[str, Any],
    *,
    allow_schedule_override: bool,
) -> dict[str, Any]:
    required_strings = _PROJECT_FIELDS_V2 - {"target_means"} - _V2_LIST_FIELDS
    for field in required_strings:
        if not isinstance(project.get(field), str) or not str(project[field]).strip():
            raise BaselineValidationError(f"기준파일의 {field} 값이 비어 있거나 올바르지 않습니다.")

    priorities = _clean_optional_string_list(
        project.get("organization_priorities"), "조직 우선역량"
    )
    interests = _clean_optional_string_list(project.get("learner_interests"), "학습 희망역량")
    delivery = str(project.get("delivery_preference", "")).strip()
    if delivery not in _DELIVERY_PREFERENCES:
        raise BaselineValidationError("교육방식 선호는 all, offline, online 중 하나여야 합니다.")

    pre_start = _parse_iso_date(project.get("pre_start_date"), "사전검사 시작일")
    pre_completed = _parse_iso_date(project.get("pre_completed_at"), "사전검사 완료일")
    pre_end = _parse_iso_date(project.get("pre_end_date"), "사전검사 종료일")
    training = _parse_iso_date(project.get("training_date"), "교육일")
    post_start = _parse_iso_date(project.get("post_start_date"), "사후검사 시작일")
    post_end = _parse_iso_date(project.get("post_end_date"), "사후검사 종료일")
    if not (pre_start <= pre_end < training < post_start <= post_end):
        raise BaselineValidationError(
            "검사 일정은 사전 시작≤사전 종료<교육일<사후 시작≤사후 종료 순서여야 합니다."
        )
    if not allow_schedule_override and not (pre_start <= pre_completed <= pre_end):
        raise BaselineValidationError(
            "검사 일정상 사전 완료일은 설정된 사전검사 기간 안이어야 합니다."
        )

    normalized = dict(project)
    normalized["organization_priorities"] = priorities
    normalized["learner_interests"] = interests
    normalized["delivery_preference"] = delivery
    return normalized


def _validate_v2_project(project: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_project_schedule(project, allow_schedule_override=False)


def _validate_v3_project(project: Mapping[str, Any]) -> dict[str, Any]:
    allow_schedule_override = project.get("allow_schedule_override")
    if not isinstance(allow_schedule_override, bool):
        raise BaselineValidationError(
            "v3 기준파일의 allow_schedule_override 값은 true 또는 false여야 합니다."
        )
    normalized = _validate_project_schedule(
        project,
        allow_schedule_override=allow_schedule_override,
    )
    normalized["allow_schedule_override"] = allow_schedule_override
    return normalized


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
    allow_schedule_override = state.get("allow_schedule_override", False)
    if not isinstance(allow_schedule_override, bool):
        raise BaselineValidationError("검사기간 예외 허용 설정이 올바르지 않습니다.")
    project = {
        "project_id": str(state.get("project_id", "")).strip(),
        "project_name": str(state.get("project_name", "")).strip(),
        "course_name": str(state.get("course_name", "")).strip(),
        "target_level": str(state.get("target_level", "")).strip(),
        "training_date": str(state.get("training_date", "")).strip(),
        "pre_start_date": str(state.get("pre_start_date", "")).strip(),
        "pre_end_date": str(state.get("pre_end_date", "")).strip(),
        "post_start_date": str(state.get("post_start_date", "")).strip(),
        "post_end_date": str(state.get("post_end_date", "")).strip(),
        "pre_completed_at": str(
            dict(state.get("assessment_completed_at_by_phase") or {}).get("pre")
            or state.get("pre_end_date", "")
        ).strip(),
        "target_means": dict(target_means) if isinstance(target_means, Mapping) else {},
        "organization_priorities": deepcopy(state.get("organization_priorities") or []),
        "learner_interests": deepcopy(state.get("learner_interests") or []),
        "delivery_preference": str(state.get("delivery_preference", "all")).strip(),
        "allow_schedule_override": allow_schedule_override,
    }
    if not project["project_id"]:
        project["project_id"] = _deterministic_project_id(
            "TAP-",
            {
                "project_name": project["project_name"],
                "course_name": project["course_name"],
                "target_level": project["target_level"],
                "training_date": project["training_date"],
                "pre_start_date": project["pre_start_date"],
                "pre_end_date": project["pre_end_date"],
                "post_start_date": project["post_start_date"],
                "post_end_date": project["post_end_date"],
                "selected_factors": selected_factors,
                "question_snapshot_hash": snapshot_hash,
            },
        )
    project = _validate_v3_project(project)
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
    schema_version = payload.get("schema_version")
    if (
        payload.get("format") != BASELINE_FORMAT
        or isinstance(schema_version, bool)
        or schema_version not in SUPPORTED_BASELINE_SCHEMA_VERSIONS
    ):
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
    expected_project_fields = _PROJECT_FIELDS_BY_VERSION[int(schema_version)]
    if not isinstance(project, dict) or set(project) != expected_project_fields:
        raise BaselineValidationError("프로젝트 메타데이터 구성이 올바르지 않습니다.")
    string_fields = (
        expected_project_fields
        - {"target_means", "allow_schedule_override"}
        - _V2_LIST_FIELDS
    )
    if any(
        not isinstance(project[field], str)
        for field in string_fields
    ) or not isinstance(project.get("target_means"), dict):
        raise BaselineValidationError("프로젝트 메타데이터 값의 형식이 올바르지 않습니다.")
    if int(schema_version) == 2:
        project = _validate_v2_project(project)
    elif int(schema_version) >= 3:
        project = _validate_v3_project(project)

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
    if int(schema_version) >= 2:
        project_identity_fields.update(
            {
                "project_id": "프로젝트 ID",
                "pre_start_date": "사전검사 시작일",
                "post_start_date": "사후검사 시작일",
                "post_end_date": "사후검사 종료일",
            }
        )
    for field, label in project_identity_fields.items():
        baseline_value = str(project.get(field, "")).strip()
        current_value = str(current_state.get(field, "")).strip()
        if baseline_value != current_value:
            raise BaselineValidationError(
                f"기준파일의 {label}이 현재 프로젝트와 일치하지 않습니다. "
                "교육 전 검사에 사용한 프로젝트를 먼저 선택해 주세요."
            )
    if int(schema_version) >= 2:
        current_priorities = _clean_optional_string_list(
            current_state.get("organization_priorities", []), "현재 조직 우선역량"
        )
        current_interests = _clean_optional_string_list(
            current_state.get("learner_interests", []), "현재 학습 희망역량"
        )
        current_delivery = str(current_state.get("delivery_preference", "all")).strip()
        if set(project["organization_priorities"]) != set(current_priorities):
            raise BaselineValidationError("기준파일의 조직 우선역량이 현재 프로젝트와 일치하지 않습니다.")
        if set(project["learner_interests"]) != set(current_interests):
            raise BaselineValidationError("기준파일의 학습 희망역량이 현재 프로젝트와 일치하지 않습니다.")
        if project["delivery_preference"] != current_delivery:
            raise BaselineValidationError("기준파일의 교육방식 선호가 현재 프로젝트와 일치하지 않습니다.")
    if int(schema_version) >= 3:
        current_override = current_state.get(
            "allow_schedule_override",
            project["allow_schedule_override"],
        )
        if not isinstance(current_override, bool):
            raise BaselineValidationError("현재 프로젝트의 검사기간 예외 허용 설정이 올바르지 않습니다.")
        if project["allow_schedule_override"] != current_override:
            raise BaselineValidationError(
                "기준파일의 검사기간 예외 허용 설정이 현재 프로젝트와 일치하지 않습니다."
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
    normalized["project"] = deepcopy(project)
    normalized["instrument"]["question_snapshot_codes"] = payload_codes
    normalized["instrument"]["question_snapshot_hash"] = payload_hash
    normalized["responses"] = responses
    return normalized


def _bootstrap_payload_preview(raw: bytes | str) -> dict[str, Any]:
    """Read only enough JSON to configure a temporary validation context."""

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
    return payload


def _current_question_bank_snapshot(
    selected_factors: list[str],
) -> tuple[list[str], str]:
    """Return the active code set and legacy-compatible hash for factors."""

    questions = questions_for_factors(selected_factors)
    current_factors = {str(row.get("factor_code", "")).strip() for row in questions}
    if not questions or current_factors != set(selected_factors):
        raise BaselineValidationError(
            "기준파일의 선택 역량을 현재 문항은행에서 찾을 수 없습니다."
        )
    codes = [str(row.get("question_code", "")).strip() for row in questions]
    if any(not code for code in codes) or len(codes) != len(set(codes)):
        raise BaselineValidationError("현재 문항은행의 문항 코드 구성이 올바르지 않습니다.")
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
    return codes, snapshot_hash


def _normalize_legacy_project(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Derive deterministic v2-era state from a validated v1 project."""

    project = dict(payload["project"])
    pre_end = _parse_iso_date(project.get("pre_end_date"), "v1 사전검사 종료일")
    training = _parse_iso_date(project.get("training_date"), "v1 교육일")
    completed_value = str(project.get("pre_completed_at", "")).strip() or pre_end.isoformat()
    pre_completed = _parse_iso_date(completed_value, "v1 사전검사 완료일")
    if not (pre_completed <= pre_end < training):
        raise BaselineValidationError(
            "v1 검사 일정은 사전 완료≤사전 종료<교육일 순서여야 합니다."
        )

    pre_start = min(pre_end - timedelta(days=11), pre_completed)
    post_start = training + timedelta(days=56)
    post_end = training + timedelta(days=70)
    project_id = _deterministic_project_id(
        "TAP-LEGACY-",
        {
            "project_name": project.get("project_name", ""),
            "course_name": project.get("course_name", ""),
            "target_level": project.get("target_level", ""),
            "training_date": training.isoformat(),
            "pre_end_date": pre_end.isoformat(),
            "selected_factors": payload["selected_factors"],
            "target_means": project.get("target_means", {}),
            "question_snapshot_hash": payload["instrument"]["question_snapshot_hash"],
        },
    )
    project.update(
        {
            "project_id": project_id,
            "pre_start_date": pre_start.isoformat(),
            "pre_end_date": pre_end.isoformat(),
            "pre_completed_at": pre_completed.isoformat(),
            "training_date": training.isoformat(),
            "post_start_date": post_start.isoformat(),
            "post_end_date": post_end.isoformat(),
            "organization_priorities": [],
            "learner_interests": [],
            "delivery_preference": "all",
        }
    )
    warnings = [
        "v1 기준파일에 없던 프로젝트 ID와 검사 일정을 결정적 규칙으로 재구성했습니다.",
        "v1 기준파일에 없던 조직 우선역량·학습 희망역량·교육방식 선호를 빈 목록·전체 방식으로 초기화했습니다.",
    ]
    return project, warnings


def bootstrap_post_from_pre_baseline(
    state: MutableMapping[str, Any],
    raw: bytes | str,
) -> dict[str, Any]:
    """Atomically configure a fresh session and restore a completed pre wave.

    The uploaded file is first validated in a detached context.  The live
    mapping is updated once, and only after its project, instrument and item
    responses match the current question bank.  Existing post data is never
    re-paired to an uploaded baseline.
    """

    phase_store = state.get("responses_by_phase")
    stored_post = phase_store.get("post") if isinstance(phase_store, Mapping) else None
    active_post = (
        state.get("responses")
        if str(state.get("assessment_phase", "")).lower() == "post"
        else None
    )
    completed_store = state.get("assessment_completed_by_phase")
    post_completed = bool(
        completed_store.get("post") if isinstance(completed_store, Mapping) else False
    )
    if (
        bool(stored_post)
        or bool(active_post)
        or bool(state.get("post_responses"))
        or bool(state.get("post_transfer_responses"))
        or post_completed
    ):
        raise BaselineValidationError(
            "기존 교육 후 응답이 있어 기준파일을 자동 연결할 수 없습니다. "
            "교육 후 검사를 초기화한 뒤 다시 시도해 주세요."
        )

    preview = _bootstrap_payload_preview(raw)
    preview_project = preview.get("project")
    preview_instrument = preview.get("instrument")
    if not isinstance(preview_project, dict) or not isinstance(preview_instrument, dict):
        raise BaselineValidationError("기준파일의 프로젝트 또는 검사 도구 정보가 올바르지 않습니다.")

    # Build a detached state that represents the project carried by the file.
    # validate_pre_baseline performs the complete schema/checksum/value checks.
    candidate = deepcopy(dict(state))
    candidate.update(
        {
            "assessment_phase": "post",
            "participant_id": preview.get("participant_id", ""),
            "selected_factors": preview.get("selected_factors", []),
            "target_means": preview_project.get("target_means", {}),
            "assessment_version": preview_instrument.get("assessment_version", ""),
            "question_snapshot_hash": preview_instrument.get("question_snapshot_hash", ""),
            "question_snapshot_codes": preview_instrument.get("question_snapshot_codes", []),
        }
    )
    for field in _PROJECT_FIELDS_V3 - {"target_means", "pre_completed_at"}:
        if field in preview_project:
            candidate[field] = preview_project[field]

    payload = validate_pre_baseline(raw, candidate)
    selected_factors = list(payload["selected_factors"])
    instrument = payload["instrument"]
    payload_codes = list(instrument["question_snapshot_codes"])
    payload_hash = str(instrument["question_snapshot_hash"])
    current_codes, current_hash = _current_question_bank_snapshot(selected_factors)
    if set(payload_codes) != set(current_codes):
        raise BaselineValidationError(
            "기준파일의 문항 코드가 현재 문항은행과 일치하지 않습니다."
        )
    if payload_hash != current_hash:
        raise BaselineValidationError(
            "기준파일의 문항 스냅샷이 현재 문항은행과 일치하지 않습니다."
        )

    existing_hash = str(state.get("question_snapshot_hash", "")).strip().lower()
    if existing_hash and existing_hash != payload_hash:
        raise BaselineValidationError(
            "현재 세션에 다른 문항 스냅샷이 설정되어 있어 기준파일을 연결할 수 없습니다."
        )
    existing_codes = [
        str(code).strip() for code in (state.get("question_snapshot_codes") or [])
    ]
    if existing_codes and set(existing_codes) != set(payload_codes):
        raise BaselineValidationError(
            "현재 세션의 문항 코드가 기준파일과 일치하지 않습니다."
        )

    if int(payload["schema_version"]) == 1:
        project, restore_warnings = _normalize_legacy_project(payload)
    else:
        project = dict(payload["project"])
        restore_warnings = []
    responses = dict(payload["responses"])
    updates: dict[str, Any] = {
        "assessment_phase": "post",
        "current_assessment_phase": "post",
        "participant_id": payload["participant_id"],
        PARTICIPANT_ID_WIDGET_KEY: payload["participant_id"],
        "project_name": project["project_name"],
        "course_name": project["course_name"],
        "target_level": project["target_level"],
        "training_date": project["training_date"],
        "project_id": project["project_id"],
        "pre_start_date": project["pre_start_date"],
        "pre_end_date": project["pre_end_date"],
        "post_start_date": project["post_start_date"],
        "post_end_date": project["post_end_date"],
        "project_start_date": project["pre_start_date"],
        "project_end_date": project["pre_end_date"],
        "selected_factors": selected_factors,
        "target_means": dict(project["target_means"]),
        "organization_priorities": list(project["organization_priorities"]),
        "learner_interests": list(project["learner_interests"]),
        "delivery_preference": project["delivery_preference"],
        "allow_schedule_override": bool(
            project.get(
                "allow_schedule_override",
                state.get("allow_schedule_override", True),
            )
        ),
        "baseline_restore_warnings": restore_warnings,
        "assessment_version": instrument["assessment_version"],
        "question_snapshot_hash": payload_hash,
        "question_snapshot_codes": payload_codes,
        "responses_by_phase": {"pre": responses, "post": {}},
        "current_question_by_phase": {"pre": max(len(responses) - 1, 0), "post": 0},
        "assessment_started_at_by_phase": {"pre": None, "post": None},
        "assessment_completed_by_phase": {"pre": True, "post": False},
        "assessment_completed_at_by_phase": {
            "pre": project["pre_completed_at"],
            "post": None,
        },
        "duration_seconds_by_phase": {"pre": None, "post": None},
        "post_transfer_responses": {},
        "pre_responses": responses,
        "post_responses": {},
        "responses": {},
        "current_question": 0,
        "assessment_started_at": None,
        "assessment_completed": False,
        "duration_seconds": None,
        "share_consent": False,
    }

    state.update(updates)
    return payload


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
