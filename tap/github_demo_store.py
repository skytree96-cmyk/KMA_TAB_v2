from __future__ import annotations

"""Small GitHub-backed persistence layer for the public TAP demo.

This module is intentionally limited to *synthetic demo data*.  It writes one
project snapshot and one pre/post snapshot per pseudonymous participant.  Page
code should call ``save_submission`` only when a phase is completed; GitHub's
Contents API is not a per-question database.
"""

import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Mapping, MutableMapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from tap.runtime_guard import source_fingerprint


__tap_source_sha256__ = source_fingerprint(__file__)


SCHEMA_VERSION = 1
ROOT_PATH = "tap-demo/v1"
DEFAULT_BRANCH = "demo-data"
DEFAULT_API_URL = "https://api.github.com"
MAX_CONFLICT_RETRIES = 3

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PARTICIPANT_KEY_RE = re.compile(r"^p_[0-9a-f]{64}$")
_REPOSITORY_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_FORBIDDEN_SUBMISSION_KEYS = {
    "participantid",
    "participantidinput",
    "employeenumber",
    "employeeid",
    "email",
    "phone",
    "phonenumber",
}
_TRANSITION_SCORE_KEYS = {
    "application_opportunity",
    "supervisor_support",
    "resources_authority",
    "time_process_support",
}
_TRANSITION_BARRIERS = {
    "적용 기회 부족",
    "상사·동료 지원 부족",
    "도구·정보·권한 부족",
    "시간·프로세스 제약",
    "특별한 방해요인 없음",
}

_PROJECT_FIELDS = (
    "project_id",
    "project_name",
    "course_name",
    "project_start_date",
    "project_end_date",
    "target_level",
    "training_date",
    "pre_start_date",
    "pre_end_date",
    "post_start_date",
    "post_end_date",
    "allow_schedule_override",
    "target_means",
    "organization_priorities",
    "learner_interests",
    "training_cause",
    "delivery_preference",
    "current_assessment_phase",
    "selected_factors",
    "assessment_version",
    "question_snapshot_hash",
    "question_snapshot_codes",
)


class DemoStoreError(RuntimeError):
    """Raised when demo-store configuration, validation, or I/O fails."""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _mapping_value(mapping: Any, key: str) -> Any:
    if mapping is None:
        return None
    try:
        return mapping.get(key)
    except (AttributeError, KeyError, TypeError):
        try:
            return mapping[key]
        except (KeyError, TypeError):
            return None


def _first(mapping: Any, *keys: str) -> Any:
    for key in keys:
        value = _mapping_value(mapping, key)
        if value is not None and _clean(value):
            return value
    return None


def _secret_sections(secrets: Any) -> list[Any]:
    sections: list[Any] = []
    for name in ("github_demo_store", "github_demo"):
        section = _mapping_value(secrets, name)
        if section is not None:
            sections.append(section)
    sections.append(secrets)
    return sections


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None or _clean(value) == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = _clean(value).lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise DemoStoreError(
        "GitHub 데모 저장소 enabled 값은 true/false 형식이어야 합니다."
    )


@dataclass(frozen=True)
class DemoStoreConfig:
    """Configuration for a GitHub Contents API demo store.

    Owner/repository are enough for public reads.  Writes additionally require
    a token.  The salt is needed only when converting a raw participant ID into
    its non-reversible storage key.
    """

    enabled: bool = False
    owner: str = ""
    repo: str = ""
    token: str = field(default="", repr=False)
    branch: str = DEFAULT_BRANCH
    salt: str = field(default="", repr=False)
    access_code: str = field(default="", repr=False)
    report_preview_code: str = field(default="", repr=False)
    api_url: str = DEFAULT_API_URL
    root_path: str = ROOT_PATH

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            object.__setattr__(self, "enabled", _parse_bool(self.enabled))
        for text_field in (
            "owner",
            "repo",
            "token",
            "branch",
            "salt",
            "access_code",
            "report_preview_code",
            "api_url",
            "root_path",
        ):
            object.__setattr__(self, text_field, _clean(getattr(self, text_field)))

        if self.enabled and not (self.owner and self.repo):
            raise DemoStoreError(
                "GitHub 데모 저장소가 enabled=true이지만 owner/repo가 설정되지 않았습니다."
            )
        if self.owner and not _REPOSITORY_PART_RE.fullmatch(self.owner):
            raise DemoStoreError("GitHub owner 형식이 올바르지 않습니다.")
        if self.repo and not _REPOSITORY_PART_RE.fullmatch(self.repo):
            raise DemoStoreError("GitHub repo 형식이 올바르지 않습니다.")
        if not self.branch or any(char in self.branch for char in "?#\r\n\t"):
            raise DemoStoreError("GitHub 데이터 브랜치 형식이 올바르지 않습니다.")
        if not self.api_url.startswith("https://"):
            raise DemoStoreError("GitHub API URL은 https 주소여야 합니다.")
        if self.branch.lower() in {"main", "master"}:
            raise DemoStoreError("합성 데이터 브랜치는 코드 기본 브랜치와 분리해야 합니다.")
        if self.root_path != ROOT_PATH:
            raise DemoStoreError(f"데모 저장 경로는 {ROOT_PATH!r}로 고정됩니다.")

    @property
    def configured(self) -> bool:
        return bool(self.owner and self.repo)

    @property
    def write_enabled(self) -> bool:
        return bool(
            self.enabled
            and self.configured
            and self.token
            and self.access_code
        )

    @property
    def read_enabled(self) -> bool:
        return bool(self.enabled and self.configured)

    def access_granted(self, candidate: Any) -> bool:
        """Constant-time check for the shared synthetic-test write gate."""

        return bool(
            self.write_enabled
            and hmac.compare_digest(self.access_code, _clean(candidate))
        )

    def report_preview_granted(self, candidate: Any) -> bool:
        """Constant-time check for the read-only small-sample report preview.

        A separately configured preview code takes precedence. Falling back
        to the legacy shared access code keeps existing planning-demo setups
        working, but this gate is not a substitute for production RBAC.
        Unlike the write gate, report preview does not require a GitHub token.
        """

        configured_code = self.report_preview_code or self.access_code
        return bool(
            self.enabled
            and self.configured
            and configured_code
            and hmac.compare_digest(configured_code, _clean(candidate))
        )

    @classmethod
    def from_sources(
        cls,
        secrets: Any = None,
        environ: Mapping[str, str] | None = None,
    ) -> "DemoStoreConfig":
        """Build configuration from Streamlit secrets and/or environment.

        Environment variables take precedence.  Supported canonical names are
        ``TAP_DEMO_GITHUB_OWNER``, ``..._REPO``, ``..._TOKEN``, ``..._BRANCH``,
        ``..._SALT``, ``..._ACCESS_CODE``, ``..._REPORT_PREVIEW_CODE`` and
        ``..._API_URL``. A
        ``[github_demo_store]`` secrets section may use the corresponding
        short names.
        """

        env = os.environ if environ is None else environ
        sections = _secret_sections(secrets)

        def secret(*names: str) -> Any:
            for section in sections:
                value = _first(section, *names)
                if value is not None:
                    return value
            return None

        enabled = _parse_bool(
            _first(env, "GITHUB_DEMO_STORE_ENABLED", "TAP_DEMO_GITHUB_ENABLED")
            or secret("enabled"),
            default=False,
        )
        repository_slug = _clean(
            _first(
                env,
                "GITHUB_DEMO_STORE_REPOSITORY",
                "TAP_DEMO_GITHUB_REPOSITORY",
                "GITHUB_DEMO_REPOSITORY",
            )
            or secret("repository", "github_repository")
        )
        slug_owner = ""
        slug_repo = ""
        if repository_slug:
            parts = repository_slug.removesuffix(".git").split("/")
            if len(parts) == 2:
                slug_owner, slug_repo = parts

        owner = _clean(
            _first(
                env,
                "GITHUB_DEMO_STORE_OWNER",
                "TAP_DEMO_GITHUB_OWNER",
                "GITHUB_DEMO_OWNER",
            )
            or secret("owner", "github_owner")
            or slug_owner
        )
        repo = _clean(
            _first(
                env,
                "GITHUB_DEMO_STORE_REPO",
                "TAP_DEMO_GITHUB_REPO",
                "GITHUB_DEMO_REPO",
            )
            or secret("repo", "github_repo")
            or slug_repo
        ).removesuffix(".git")
        token = _clean(
            _first(
                env,
                "GITHUB_DEMO_STORE_TOKEN",
                "TAP_DEMO_GITHUB_TOKEN",
                "GITHUB_DEMO_TOKEN",
            )
            or secret("token", "github_token")
        )
        branch = _clean(
            _first(
                env,
                "GITHUB_DEMO_STORE_BRANCH",
                "TAP_DEMO_GITHUB_BRANCH",
                "GITHUB_DEMO_BRANCH",
            )
            or secret("branch", "github_branch")
            or DEFAULT_BRANCH
        )
        salt = _clean(
            _first(
                env,
                "GITHUB_DEMO_STORE_PARTICIPANT_SALT",
                "TAP_DEMO_GITHUB_SALT",
                "GITHUB_DEMO_SALT",
                "TAP_DEMO_PARTICIPANT_SALT",
            )
            or secret("salt", "participant_salt", "participant_hash_salt")
        )
        access_code = _clean(
            _first(
                env,
                "GITHUB_DEMO_STORE_ACCESS_CODE",
                "TAP_DEMO_GITHUB_ACCESS_CODE",
            )
            or secret("access_code", "test_access_code")
        )
        report_preview_code = _clean(
            _first(
                env,
                "GITHUB_DEMO_STORE_REPORT_PREVIEW_CODE",
                "TAP_DEMO_GITHUB_REPORT_PREVIEW_CODE",
                "GITHUB_DEMO_STORE_ADMIN_PREVIEW_CODE",
                "TAP_DEMO_GITHUB_ADMIN_PREVIEW_CODE",
            )
            or secret("report_preview_code", "admin_preview_code")
        )
        api_url = _clean(
            _first(env, "TAP_DEMO_GITHUB_API_URL", "GITHUB_DEMO_API_URL")
            or secret("api_url")
            or DEFAULT_API_URL
        ).rstrip("/")
        return cls(
            enabled=enabled,
            owner=owner,
            repo=repo,
            token=token,
            branch=branch,
            salt=salt,
            access_code=access_code,
            report_preview_code=report_preview_code,
            api_url=api_url,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    raise DemoStoreError(f"JSON으로 저장할 수 없는 값이 있습니다: {type(value).__name__}")


def _project_id(value: Any) -> str:
    cleaned = _clean(value)
    if not _PROJECT_ID_RE.fullmatch(cleaned):
        raise DemoStoreError("project_id는 영문·숫자로 시작하는 128자 이하의 안전한 값이어야 합니다.")
    return cleaned


def participant_key(project_id: str, participant_id: str, salt: str) -> str:
    """Return a deterministic HMAC key without retaining the raw participant ID."""

    project = _project_id(project_id)
    participant = _clean(participant_id)
    secret = _clean(salt)
    if not participant or len(participant) > 128 or any(char in participant for char in "\r\n\t\x00"):
        raise DemoStoreError("교육 참여자 ID 형식이 올바르지 않습니다.")
    if not secret:
        raise DemoStoreError("참여자 ID 가명처리를 위한 demo-store salt가 필요합니다.")
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{project}\x00{participant}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"p_{digest}"


def project_payload_from_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Create an allow-listed project snapshot sufficient to restore the demo."""

    project = _project_id(state.get("project_id"))
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "demo_only": True,
        "record_type": "project",
    }
    for field in _PROJECT_FIELDS:
        payload[field] = _json_safe(state.get(field))
    payload["project_id"] = project
    payload["selected_factors"] = list(payload.get("selected_factors") or [])
    payload["question_snapshot_codes"] = list(payload.get("question_snapshot_codes") or [])
    payload["target_means"] = dict(payload.get("target_means") or {})
    payload["organization_priorities"] = list(payload.get("organization_priorities") or [])
    payload["learner_interests"] = list(payload.get("learner_interests") or [])
    payload["current_assessment_phase"] = (
        _clean(payload.get("current_assessment_phase") or state.get("assessment_phase"))
        or "pre"
    ).lower()
    created_at = _clean(state.get("project_created_at") or state.get("created_at")) or _now_iso()
    payload["created_at"] = created_at
    payload["updated_at"] = _now_iso()
    _validate_project_payload(payload)
    return payload


def _phase_value(state: Mapping[str, Any], mapping_key: str, phase: str, default: Any) -> Any:
    mapping = state.get(mapping_key)
    if isinstance(mapping, Mapping) and phase in mapping:
        return mapping.get(phase)
    if _clean(state.get("assessment_phase") or "pre").lower() == phase:
        aliases = {
            "responses_by_phase": "responses",
            "assessment_started_at_by_phase": "assessment_started_at",
            "assessment_completed_by_phase": "assessment_completed",
            "duration_seconds_by_phase": "duration_seconds",
        }
        alias = aliases.get(mapping_key)
        if alias:
            return state.get(alias, default)
    return default


def _phase_snapshot(state: Mapping[str, Any], phase: str) -> dict[str, Any]:
    responses = _phase_value(state, "responses_by_phase", phase, {})
    completed_at_map = state.get("assessment_completed_at_by_phase")
    completed_at = completed_at_map.get(phase) if isinstance(completed_at_map, Mapping) else None
    return {
        "responses": _json_safe(dict(responses or {})) if isinstance(responses, Mapping) else {},
        "completed": bool(_phase_value(state, "assessment_completed_by_phase", phase, False)),
        "completed_at": _json_safe(completed_at),
        "started_at": _json_safe(
            _phase_value(state, "assessment_started_at_by_phase", phase, None)
        ),
        "duration_seconds": _json_safe(
            _phase_value(state, "duration_seconds_by_phase", phase, None)
        ),
    }


def submission_payload_from_state(
    state: Mapping[str, Any],
    *,
    salt: str | None = None,
) -> dict[str, Any]:
    """Create one pseudonymous pre/post snapshot from Streamlit session state."""

    project = _project_id(state.get("project_id"))
    raw_participant_id = _clean(state.get("participant_id"))
    selected_salt = _clean(
        salt
        or state.get("demo_store_salt")
        or state.get("github_demo_salt")
        or state.get("participant_hash_salt")
    )
    pseudonym = participant_key(project, raw_participant_id, selected_salt)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "demo_only": True,
        "record_type": "submission",
        "project_id": project,
        "participant_key": pseudonym,
        "instrument": {
            "assessment_version": _json_safe(state.get("assessment_version")),
            "question_snapshot_hash": _json_safe(state.get("question_snapshot_hash")),
            "question_snapshot_codes": _json_safe(list(state.get("question_snapshot_codes") or [])),
            "selected_factors": _json_safe(list(state.get("selected_factors") or [])),
            "response_scale": {"minimum": 0, "maximum": 5},
        },
        "phases": {
            "pre": _phase_snapshot(state, "pre"),
            "post": _phase_snapshot(state, "post"),
        },
        "transition_responses": _json_safe(
            {
                key: value
                for key, value in dict(state.get("post_transfer_responses") or {}).items()
                if key in _TRANSITION_SCORE_KEYS or key == "barriers"
            }
        ),
        "updated_at": _now_iso(),
    }
    _validate_submission_payload(payload)
    return payload


def _normalized_key(value: Any) -> str:
    return "".join(char for char in str(value).lower() if char.isalnum())


def _reject_direct_identifiers(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _normalized_key(key) in _FORBIDDEN_SUBMISSION_KEYS:
                raise DemoStoreError(f"직접 식별자 필드는 데모 제출 데이터에 저장할 수 없습니다: {key}")
            _reject_direct_identifiers(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_direct_identifiers(item)


def _validate_response_map(value: Any, label: str) -> None:
    if not isinstance(value, Mapping):
        raise DemoStoreError(f"{label} 응답은 객체 형식이어야 합니다.")
    for raw_code, score in value.items():
        if not _clean(raw_code):
            raise DemoStoreError(f"{label} 문항 코드가 비어 있습니다.")
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 5:
            raise DemoStoreError(f"{label} 응답값은 0~5 정수여야 합니다.")


def _validate_common(payload: Mapping[str, Any], record_type: str) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise DemoStoreError(f"지원하지 않는 데모 저장 스키마입니다: {payload.get('schema_version')!r}")
    if payload.get("demo_only") is not True:
        raise DemoStoreError("데모 저장 데이터에는 demo_only=true가 필요합니다.")
    if payload.get("record_type") != record_type:
        raise DemoStoreError(f"record_type은 {record_type!r}이어야 합니다.")
    _project_id(payload.get("project_id"))


def _validate_project_payload(payload: Mapping[str, Any]) -> None:
    _validate_common(payload, "project")
    if _clean(payload.get("current_assessment_phase") or "pre").lower() not in {
        "pre",
        "post",
    }:
        raise DemoStoreError("current_assessment_phase는 pre 또는 post여야 합니다.")
    selected_factors = payload.get("selected_factors")
    if not isinstance(selected_factors, list):
        raise DemoStoreError("selected_factors는 목록이어야 합니다.")
    if (
        not selected_factors
        or any(not isinstance(code, str) or not _clean(code) for code in selected_factors)
        or len(selected_factors) != len(set(selected_factors))
    ):
        raise DemoStoreError("selected_factors는 중복 없는 비어 있지 않은 문자열 목록이어야 합니다.")
    if not isinstance(payload.get("target_means"), Mapping):
        raise DemoStoreError("target_means는 객체여야 합니다.")
    if not isinstance(payload.get("question_snapshot_codes"), list):
        raise DemoStoreError("question_snapshot_codes는 목록이어야 합니다.")


def _validate_submission_payload(payload: Mapping[str, Any]) -> None:
    _validate_common(payload, "submission")
    _reject_direct_identifiers(payload)
    if not _PARTICIPANT_KEY_RE.fullmatch(_clean(payload.get("participant_key"))):
        raise DemoStoreError("participant_key 형식이 올바르지 않습니다.")
    instrument = payload.get("instrument")
    if not isinstance(instrument, Mapping):
        raise DemoStoreError("submission instrument가 필요합니다.")
    codes = instrument.get("question_snapshot_codes")
    if (
        not isinstance(codes, list)
        or not codes
        or len(codes) != len(set(str(code) for code in codes))
        or any(not _clean(code) for code in codes)
    ):
        raise DemoStoreError("문항 스냅샷 코드는 목록이어야 합니다.")
    expected_codes = {str(code) for code in codes}
    phases = payload.get("phases")
    if not isinstance(phases, Mapping) or set(phases) != {"pre", "post"}:
        raise DemoStoreError("submission에는 pre/post 단계가 모두 필요합니다.")
    for phase in ("pre", "post"):
        snapshot = phases.get(phase)
        if not isinstance(snapshot, Mapping):
            raise DemoStoreError(f"{phase} 단계 스냅샷이 올바르지 않습니다.")
        _validate_response_map(snapshot.get("responses"), phase)
        if not isinstance(snapshot.get("completed"), bool):
            raise DemoStoreError(f"{phase} 완료 상태는 true/false여야 합니다.")
        response_codes = set(str(code) for code in snapshot.get("responses", {}))
        if not response_codes <= expected_codes:
            raise DemoStoreError(f"{phase} 응답에 현재 문항 스냅샷 밖의 코드가 있습니다.")
        if snapshot.get("completed") and response_codes != expected_codes:
            raise DemoStoreError(f"{phase} 완료 스냅샷에는 모든 문항 응답이 필요합니다.")
    if phases["post"].get("completed") and not phases["pre"].get("completed"):
        raise DemoStoreError("교육 후 완료 결과에는 완료된 교육 전 결과가 필요합니다.")
    transition = payload.get("transition_responses")
    if not isinstance(transition, Mapping):
        raise DemoStoreError("전이응답은 객체 형식이어야 합니다.")
    if not set(transition) <= (_TRANSITION_SCORE_KEYS | {"barriers"}):
        raise DemoStoreError("GitHub 테스트 저장소에는 허용된 전이응답만 저장할 수 있습니다.")
    for key in _TRANSITION_SCORE_KEYS & set(transition):
        value = transition[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
            raise DemoStoreError(f"{key} 전이응답은 1~5 정수여야 합니다.")
    barriers = transition.get("barriers", [])
    if (
        not isinstance(barriers, list)
        or len(barriers) != len(set(str(value) for value in barriers))
        or not set(str(value) for value in barriers) <= _TRANSITION_BARRIERS
    ):
        raise DemoStoreError("전이 방해요인 목록이 올바르지 않습니다.")
    if phases["post"].get("completed") and not _TRANSITION_SCORE_KEYS <= set(transition):
        raise DemoStoreError("교육 후 완료 스냅샷에는 현업전이 4개 응답이 필요합니다.")


def _completed_phase_identity(payload: Mapping[str, Any], phase: str) -> dict[str, Any]:
    """Return the immutable, scoring-relevant identity of a completed phase.

    ``started_at``, ``completed_at``, ``duration_seconds``, and the record-level
    ``updated_at`` are deliberately excluded. A caller may recreate those
    operational fields while retrying the same completion. Project,
    participant, and instrument are included so that this helper remains safe
    even if it is reused outside the current merge preconditions.
    """

    phases = payload.get("phases")
    snapshot = phases.get(phase) if isinstance(phases, Mapping) else None
    responses = snapshot.get("responses") if isinstance(snapshot, Mapping) else None
    identity: dict[str, Any] = {
        "project_id": payload.get("project_id"),
        "participant_key": payload.get("participant_key"),
        "instrument": _json_safe(payload.get("instrument")),
        "phase": phase,
        "completed": bool(snapshot.get("completed")) if isinstance(snapshot, Mapping) else False,
        "responses": _json_safe(dict(responses or {})) if isinstance(responses, Mapping) else {},
    }
    if phase == "post":
        transition = payload.get("transition_responses")
        transition_map = dict(transition) if isinstance(transition, Mapping) else {}
        identity["transition_responses"] = {
            **{
                key: transition_map.get(key)
                for key in sorted(_TRANSITION_SCORE_KEYS)
                if key in transition_map
            },
            "barriers": sorted(str(value) for value in transition_map.get("barriers", [])),
        }
    return identity


class _UrllibTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> tuple[int, Mapping[str, str], bytes]:
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed configured API host
                return int(response.status), dict(response.headers.items()), response.read()
        except HTTPError as exc:
            return int(exc.code), dict(exc.headers.items()), exc.read()
        except (URLError, TimeoutError, OSError) as exc:
            raise DemoStoreError(f"GitHub 데모 저장소에 연결할 수 없습니다: {exc}") from exc


def _decode_transport_response(response: Any) -> tuple[int, Mapping[str, str], bytes]:
    if isinstance(response, tuple) and len(response) == 3:
        status, headers, body = response
    elif isinstance(response, Mapping):
        status = response.get("status", response.get("status_code", 0))
        headers = response.get("headers", {})
        body = response.get("body", response.get("data", response.get("json", b"")))
    else:
        status = getattr(response, "status", getattr(response, "status_code", 0))
        headers = getattr(response, "headers", {})
        body = response.read() if hasattr(response, "read") else getattr(response, "body", b"")
    if isinstance(body, (dict, list)):
        body = json.dumps(body, ensure_ascii=False).encode("utf-8")
    elif isinstance(body, str):
        body = body.encode("utf-8")
    elif body is None:
        body = b""
    return int(status), headers if isinstance(headers, Mapping) else {}, bytes(body)


def _github_message(payload: Any) -> str:
    if isinstance(payload, Mapping):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return "응답 본문 없음"


class GitHubDemoStore:
    """GitHub Contents API repository for synthetic TAP demo snapshots."""

    def __init__(
        self,
        config: DemoStoreConfig,
        transport: Any = None,
        *,
        access_code: str = "",
    ) -> None:
        if not isinstance(config, DemoStoreConfig):
            raise DemoStoreError("GitHubDemoStore에는 DemoStoreConfig가 필요합니다.")
        self.config = config
        self.transport = transport or _UrllibTransport()
        self._access_code = _clean(access_code)

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.config.configured,
            "enabled": self.config.enabled,
            "read_enabled": self.config.read_enabled,
            "write_enabled": self.config.access_granted(self._access_code),
            "owner": self.config.owner,
            "repo": self.config.repo,
            "branch": self.config.branch,
            "root_path": self.config.root_path,
            "demo_only": True,
        }

    def _require_read(self) -> None:
        if not self.config.enabled:
            raise DemoStoreError("GitHub 데모 저장소가 비활성화되어 있습니다.")
        if not self.config.configured:
            raise DemoStoreError("GitHub 데모 저장소 owner/repo가 설정되지 않았습니다.")

    def _require_write(self) -> None:
        self._require_read()
        if not self.config.write_enabled:
            raise DemoStoreError(
                "GitHub 데모 저장소 쓰기에는 token과 테스트 접속코드 설정이 필요합니다."
            )
        if not self.config.access_granted(self._access_code):
            raise DemoStoreError("GitHub 데모 저장소 테스트 접속코드가 일치하지 않습니다.")

    def _url(self, path: str) -> str:
        owner = quote(self.config.owner, safe="")
        repo = quote(self.config.repo, safe="")
        encoded_path = quote(path.strip("/"), safe="/")
        branch = quote(self.config.branch, safe="")
        return f"{self.config.api_url}/repos/{owner}/{repo}/contents/{encoded_path}?ref={branch}"

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> tuple[int, Any, Mapping[str, str]]:
        self._require_read()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "KMA-TAP-demo-store/1",
        }
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        raw_body = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            raw_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            response = self.transport.request(
                method,
                self._url(path),
                headers=headers,
                body=raw_body,
            )
        except DemoStoreError:
            raise
        except Exception as exc:
            raise DemoStoreError(f"GitHub 데모 저장소 요청에 실패했습니다: {exc}") from exc
        status, response_headers, raw = _decode_transport_response(response)
        if not raw:
            payload: Any = None
        else:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DemoStoreError("GitHub API가 올바르지 않은 JSON을 반환했습니다.") from exc
        return status, payload, response_headers

    def _load_file(self, path: str) -> tuple[dict[str, Any] | None, str | None]:
        status, envelope, _ = self._request("GET", path)
        if status == 404:
            return None, None
        if status != 200:
            raise DemoStoreError(
                f"GitHub 데모 파일 조회 실패({status}): {_github_message(envelope)}"
            )
        if not isinstance(envelope, Mapping) or envelope.get("encoding") != "base64":
            raise DemoStoreError("GitHub 데모 파일 응답 형식이 올바르지 않습니다.")
        try:
            encoded = "".join(str(envelope.get("content", "")).split())
            raw = base64.b64decode(encoded, validate=True)
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DemoStoreError("GitHub 데모 파일의 base64/JSON 내용이 손상되었습니다.") from exc
        if not isinstance(payload, dict):
            raise DemoStoreError("GitHub 데모 파일 최상위 값은 객체여야 합니다.")
        return payload, _clean(envelope.get("sha")) or None

    def _list_directory(self, path: str) -> list[Mapping[str, Any]]:
        status, payload, _ = self._request("GET", path)
        if status == 404:
            return []
        if status != 200:
            raise DemoStoreError(
                f"GitHub 데모 디렉터리 조회 실패({status}): {_github_message(payload)}"
            )
        if not isinstance(payload, list):
            raise DemoStoreError("GitHub 데모 디렉터리 응답 형식이 올바르지 않습니다.")
        return [item for item in payload if isinstance(item, Mapping)]

    def _upsert(
        self,
        path: str,
        incoming: Mapping[str, Any],
        merger: Any,
        message: str,
    ) -> dict[str, Any]:
        self._require_write()
        for retry in range(MAX_CONFLICT_RETRIES + 1):
            current, sha = self._load_file(path)
            merged = merger(current, incoming)
            raw = json.dumps(
                merged,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ).encode("utf-8")
            body: dict[str, Any] = {
                "message": message,
                "content": base64.b64encode(raw).decode("ascii"),
                "branch": self.config.branch,
            }
            if sha:
                body["sha"] = sha
            status, response, _ = self._request("PUT", path, body)
            if status in {200, 201}:
                return merged
            if status == 409 and retry < MAX_CONFLICT_RETRIES:
                continue
            if status == 409:
                raise DemoStoreError(
                    f"GitHub 데모 파일 충돌을 {MAX_CONFLICT_RETRIES}회 재시도했지만 저장하지 못했습니다."
                )
            raise DemoStoreError(
                f"GitHub 데모 파일 저장 실패({status}): {_github_message(response)}"
            )
        raise DemoStoreError("GitHub 데모 파일을 저장하지 못했습니다.")

    def load_project(self, project_id: str) -> dict[str, Any] | None:
        project = _project_id(project_id)
        payload, _ = self._load_file(f"{ROOT_PATH}/projects/{project}.json")
        if payload is not None:
            _validate_project_payload(payload)
        return payload

    def load_submission(
        self,
        project_id: str,
        participant_key_value: str,
    ) -> dict[str, Any] | None:
        project = _project_id(project_id)
        pseudonym = _clean(participant_key_value)
        if not _PARTICIPANT_KEY_RE.fullmatch(pseudonym):
            raise DemoStoreError("participant_key 형식이 올바르지 않습니다.")
        payload, _ = self._load_file(
            f"{ROOT_PATH}/submissions/{project}/{pseudonym}.json"
        )
        if payload is not None:
            _validate_submission_payload(payload)
        return payload

    def list_projects(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for item in sorted(
            self._list_directory(f"{ROOT_PATH}/projects"),
            key=lambda row: _clean(row.get("path") or row.get("name")),
        ):
            if item.get("type") != "file" or not _clean(item.get("name")).endswith(".json"):
                continue
            path = _clean(item.get("path"))
            if not path:
                continue
            payload, _ = self._load_file(path)
            if payload is not None:
                _validate_project_payload(payload)
                records.append(payload)
        return records

    def list_submissions(self, project_id: str | None = None) -> list[dict[str, Any]]:
        project_paths: list[str]
        if project_id is not None:
            project = _project_id(project_id)
            project_paths = [f"{ROOT_PATH}/submissions/{project}"]
        else:
            project_paths = [
                _clean(item.get("path"))
                for item in self._list_directory(f"{ROOT_PATH}/submissions")
                if item.get("type") == "dir" and _clean(item.get("path"))
            ]

        records: list[dict[str, Any]] = []
        for directory in sorted(project_paths):
            for item in sorted(
                self._list_directory(directory),
                key=lambda row: _clean(row.get("path") or row.get("name")),
            ):
                if item.get("type") != "file" or not _clean(item.get("name")).endswith(".json"):
                    continue
                path = _clean(item.get("path"))
                if not path:
                    continue
                payload, _ = self._load_file(path)
                if payload is not None:
                    _validate_submission_payload(payload)
                    records.append(payload)
        return records

    def save_project(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        incoming = dict(_json_safe(payload))
        _validate_project_payload(incoming)
        project = _project_id(incoming["project_id"])

        def merge(current: Mapping[str, Any] | None, new: Mapping[str, Any]) -> dict[str, Any]:
            merged = dict(current or {})
            merged.update(new)
            merged["schema_version"] = SCHEMA_VERSION
            merged["demo_only"] = True
            merged["record_type"] = "project"
            merged["created_at"] = _clean((current or {}).get("created_at")) or _clean(
                new.get("created_at")
            ) or _now_iso()
            merged["updated_at"] = _now_iso()
            _validate_project_payload(merged)
            return merged

        return self._upsert(
            f"{ROOT_PATH}/projects/{project}.json",
            incoming,
            merge,
            f"TAP demo project snapshot: {project}",
        )

    def save_submission(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        incoming = dict(_json_safe(payload))
        _validate_submission_payload(incoming)
        phases = incoming["phases"]
        if not any(bool(phases[phase].get("completed")) for phase in ("pre", "post")):
            raise DemoStoreError("문항별 저장은 지원하지 않습니다. 검사 완료 시점에만 저장해 주세요.")
        project = _project_id(incoming["project_id"])
        pseudonym = _clean(incoming["participant_key"])

        def merge(current: Mapping[str, Any] | None, new: Mapping[str, Any]) -> dict[str, Any]:
            if current is not None:
                _validate_submission_payload(current)
                if current.get("project_id") != new.get("project_id") or current.get(
                    "participant_key"
                ) != new.get("participant_key"):
                    raise DemoStoreError("기존 submission의 프로젝트/참여자 키가 일치하지 않습니다.")
                if current.get("instrument") != new.get("instrument"):
                    raise DemoStoreError(
                        "기존 교육 전·후 결과와 검사 버전·문항 스냅샷이 달라 병합할 수 없습니다."
                    )
            merged = dict(current or {})
            merged.update(new)
            old_phases = (current or {}).get("phases", {})
            new_phases = new.get("phases", {})
            combined_phases: dict[str, Any] = {}
            for phase in ("pre", "post"):
                old_phase = dict(old_phases.get(phase) or {}) if isinstance(old_phases, Mapping) else {}
                new_phase = dict(new_phases.get(phase) or {}) if isinstance(new_phases, Mapping) else {}
                # A completed snapshot is immutable. Legitimate retries may
                # recreate timing metadata, but cannot replace scores (or, for
                # post, transition responses) for the same pseudonymous key.
                if old_phase.get("completed") and new_phase.get("completed"):
                    if _completed_phase_identity(current or {}, phase) != _completed_phase_identity(
                        new, phase
                    ):
                        raise DemoStoreError(
                            f"{phase} 완료 결과가 이미 저장되어 있어 변경할 수 없습니다. "
                            "participant-ID collision/data conflict를 확인해 주세요."
                        )
                    combined_phases[phase] = old_phase
                elif old_phase.get("completed"):
                    combined_phases[phase] = old_phase
                else:
                    combined = old_phase
                    combined.update(new_phase)
                    combined_phases[phase] = combined
            merged["phases"] = combined_phases
            old_transition = (current or {}).get("transition_responses", {})
            new_transition = new.get("transition_responses", {})
            old_post_completed = bool(
                isinstance(old_phases, Mapping)
                and isinstance(old_phases.get("post"), Mapping)
                and old_phases["post"].get("completed")
            )
            new_post_completed = bool(
                isinstance(new_phases, Mapping)
                and isinstance(new_phases.get("post"), Mapping)
                and new_phases["post"].get("completed")
            )
            if old_post_completed:
                transition = dict(old_transition) if isinstance(old_transition, Mapping) else {}
            elif new_post_completed:
                transition = dict(new_transition) if isinstance(new_transition, Mapping) else {}
            else:
                transition = dict(old_transition) if isinstance(old_transition, Mapping) else {}
                if isinstance(new_transition, Mapping):
                    transition.update(new_transition)
            merged["transition_responses"] = transition
            merged["schema_version"] = SCHEMA_VERSION
            merged["demo_only"] = True
            merged["record_type"] = "submission"
            merged["updated_at"] = _now_iso()
            _validate_submission_payload(merged)
            return merged

        return self._upsert(
            f"{ROOT_PATH}/submissions/{project}/{pseudonym}.json",
            incoming,
            merge,
            f"TAP demo submission snapshot: {project}/{pseudonym}",
        )

    # Page-level names that make the completion-triggered operation explicit.
    publish_project = save_project
    publish_submission = save_submission


__all__ = [
    "DemoStoreConfig",
    "DemoStoreError",
    "GitHubDemoStore",
    "participant_key",
    "project_payload_from_state",
    "submission_payload_from_state",
]
