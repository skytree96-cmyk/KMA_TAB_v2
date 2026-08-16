from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Iterable, Mapping, Protocol

from tap.config import DATA_DIR
from tap.runtime_guard import source_fingerprint


__tap_source_sha256__ = source_fingerprint(__file__)


@lru_cache(maxsize=1)
def load_dashboard_demo() -> dict[str, Any]:
    with (DATA_DIR / "dashboard_demo.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)


def completion_rate(projects: Iterable[Mapping[str, Any]]) -> float:
    invited = sum(int(row["invited"]) for row in projects)
    completed = sum(int(row["completed"]) for row in projects)
    return round(completed / invited * 100, 1) if invited else 0.0


class DemoStoreReader(Protocol):
    """Small read-only surface used by dashboard/report pages and test fakes."""

    def list_projects(self) -> list[dict[str, Any]]: ...

    def list_submissions(self, project_id: str | None = None) -> list[dict[str, Any]]: ...


def fetch_store_snapshot(
    store: DemoStoreReader,
    *,
    project_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Read one internally consistent snapshot from the configured demo store."""

    return {
        "projects": list(store.list_projects()),
        "submissions": list(store.list_submissions(project_id=project_id)),
    }


def build_persistent_dashboard(
    submissions: Iterable[Mapping[str, Any]],
    projects: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Aggregate completed pseudonymous submissions without exposing identities.

    A participant is counted per project.  Incomplete item responses are ignored,
    and duplicate records for the same project/participant are resolved using the
    newest ``updated_at`` value.  This matches the demo store's overwrite model.
    """

    records = _latest_completed_submissions(submissions)
    project_snapshots = _project_snapshots(projects)
    stats: dict[str, dict[str, Any]] = {
        project_id: {
            "participants": set(),
            "pre": set(),
            "post": set(),
            "paired": set(),
            "updated_at": str(project.get("updated_at") or ""),
            "instrument": {},
        }
        for project_id, project in project_snapshots.items()
    }
    for record in records:
        project_id = str(record["project_id"])
        participant_key = str(record["participant_key"])
        phases = record["phases"]
        stored_question_codes = _stored_question_codes(record.get("instrument"))
        pre_complete = _stored_phase_complete(phases.get("pre"), stored_question_codes)
        post_complete = _stored_phase_complete(phases.get("post"), stored_question_codes)
        row = stats.setdefault(
            project_id,
            {
                "participants": set(),
                "pre": set(),
                "post": set(),
                "paired": set(),
                "updated_at": "",
                "instrument": record.get("instrument", {}),
            },
        )
        row["participants"].add(participant_key)
        if pre_complete:
            row["pre"].add(participant_key)
        if post_complete:
            row["post"].add(participant_key)
        if pre_complete and post_complete:
            row["paired"].add(participant_key)
        updated_at = str(record.get("updated_at") or "")
        if updated_at >= row["updated_at"]:
            row["updated_at"] = updated_at
            row["instrument"] = record.get("instrument", {})

    project_rows: list[dict[str, Any]] = []
    for project_id, row in sorted(
        stats.items(), key=lambda item: str(item[1]["updated_at"]), reverse=True
    ):
        participants = len(row["participants"])
        paired = len(row["paired"])
        instrument = row["instrument"] if isinstance(row["instrument"], Mapping) else {}
        name = (
            str(project_snapshots.get(project_id, {}).get("project_name") or "").strip()
            or str(instrument.get("project_name") or "").strip()
            or project_id
        )
        if not participants:
            status = "검사 대기"
        elif paired == participants:
            status = "전·후 완료"
        elif row["post"]:
            status = "교육 후 진행"
        else:
            status = "교육 전 완료"
        project_rows.append(
            {
                "project_id": project_id,
                "name": name,
                "scope": (
                    f"코드 {project_id} · GitHub 기획검증 누적 · 교육 전 {len(row['pre'])}명 · "
                    f"교육 후 {len(row['post'])}명"
                ),
                "invited": participants,
                "completed": paired,
                "completion_pct": round(paired / participants * 100) if participants else 0,
                "status": status,
                "updated_at": str(row["updated_at"]),
                "pre_completed": len(row["pre"]),
                "post_completed": len(row["post"]),
            }
        )

    project_count = len(project_rows)
    participant_count = sum(int(row["invited"]) for row in project_rows)
    pre_completed_count = sum(int(row["pre_completed"]) for row in project_rows)
    post_completed_count = sum(int(row["post_completed"]) for row in project_rows)
    paired_count = sum(int(row["completed"]) for row in project_rows)
    metrics = [
        {
            "value": f"{project_count}개",
            "label": "누적 프로젝트",
            "note": "GitHub 기획검증 저장소",
        },
        {
            "value": f"{participant_count}명",
            "label": "완료 검사 참여자",
            "note": "완료 snapshot · 프로젝트별 가명키",
        },
        {
            "value": f"{pre_completed_count}건",
            "label": "교육 전 완료",
            "note": "완료 제출만 집계",
        },
        {
            "value": f"{post_completed_count}건",
            "label": "교육 후 완료",
            "note": f"전·후 짝지음 {paired_count}명",
        },
    ]
    return {
        "metrics": metrics,
        "projects": project_rows,
        "has_project": bool(project_rows),
        # A published project is real stored data even before its first completed
        # submission.  Pages use this flag to decide whether to show the store or
        # fall back to the static sample dashboard.
        "has_data": bool(project_rows),
        "has_submissions": bool(records),
        "participant_count": participant_count,
        "paired_count": paired_count,
        "pre_completed_count": pre_completed_count,
        "post_completed_count": post_completed_count,
        "phase_completion_pct": (
            round((pre_completed_count + post_completed_count) / (participant_count * 2) * 100)
            if participant_count
            else 0
        ),
    }


def build_kma_persistent_dashboard(
    submissions: Iterable[Mapping[str, Any]],
    projects: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the privacy-minimal KMA overview from accumulated demo records."""

    accumulated = build_persistent_dashboard(submissions, projects)
    metrics = [
        {
            "value": f"{len(accumulated['projects'])}개",
            "label": "누적 프로젝트",
            "note": "실제 기획검증 저장자료",
        },
        {
            "value": f"{accumulated['participant_count']}명",
            "label": "완료 검사 참여자",
            "note": "완료 snapshot · 가명키 중복 제거",
        },
        {
            "value": f"{accumulated['pre_completed_count']}건",
            "label": "교육 전 완료",
            "note": "완료 제출 기준",
        },
        {
            "value": f"{accumulated['paired_count']}명",
            "label": "전·후 짝지음",
            "note": f"교육 후 완료 {accumulated['post_completed_count']}건",
        },
    ]
    organizations = [
        {
            "name": row["name"],
            "projects": 1,
            "invited": row["invited"],
            "completion_pct": row["completion_pct"],
            "activity": _display_timestamp(row["updated_at"]),
        }
        for row in accumulated["projects"]
    ]
    snapshot_rows = [
        {
            "updated_at": _display_timestamp(row["updated_at"]),
            "snapshot": "현재 완료 집계",
            "project": row["name"],
            "counts": f"전 {row['pre_completed']} · 후 {row['post_completed']}",
        }
        for row in accumulated["projects"][:10]
    ]
    return {
        "metrics": metrics,
        "organizations": organizations,
        # These rows are current aggregate snapshots, not persisted audit events.
        "snapshot_rows": snapshot_rows,
        "has_data": accumulated["has_data"],
        "has_submissions": accumulated["has_submissions"],
    }


def completed_store_submission_factor_rows(
    submissions: Iterable[Mapping[str, Any]],
    question_rows: Iterable[Mapping[str, Any]],
    *,
    project_id: str,
    assessment_version: str = "TAP-1.0",
    target_level: str = "staff",
    target_means: Mapping[str, float] | None = None,
    question_snapshot_hash: str = "",
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Convert stored item responses into canonical group-report factor rows."""

    from tap.reporting import completed_session_factor_rows

    questions = list(question_rows)
    expected_codes = [str(row.get("question_code") or "").strip() for row in questions]
    expected_code_set = set(expected_codes)
    expected_hash = str(question_snapshot_hash or "").strip()
    excluded_code_set = 0
    excluded_snapshot_hash = 0
    output: list[dict[str, Any]] = []
    for record in _latest_completed_submissions(submissions):
        if str(record["project_id"]) != str(project_id):
            continue
        phases = record["phases"]
        instrument = record.get("instrument")
        if not isinstance(instrument, Mapping):
            instrument = {}
        stored_codes = instrument.get("question_snapshot_codes")
        normalized_stored_codes = (
            [str(code).strip() for code in stored_codes]
            if isinstance(stored_codes, list)
            else []
        )
        if (
            len(normalized_stored_codes) != len(expected_codes)
            or set(normalized_stored_codes) != expected_code_set
        ):
            excluded_code_set += 1
            continue
        if expected_hash and str(instrument.get("question_snapshot_hash") or "").strip() != expected_hash:
            excluded_snapshot_hash += 1
            continue
        responses_by_phase = {
            phase: dict(value.get("responses") or {})
            for phase, value in phases.items()
            if phase in {"pre", "post"} and isinstance(value, Mapping)
        }
        completed_by_phase = {
            phase: _stored_phase_complete(phases.get(phase), normalized_stored_codes)
            for phase in ("pre", "post")
        }
        assessment_dates = {
            phase: str(dict(phases.get(phase) or {}).get("completed_at") or "")
            for phase in ("pre", "post")
        }
        stored_targets = instrument.get("target_means")
        if not isinstance(stored_targets, Mapping):
            stored_targets = target_means or {}
        output.extend(
            completed_session_factor_rows(
                questions,
                responses_by_phase,
                completed_by_phase,
                participant_id=str(record["participant_key"]),
                project_id=str(record["project_id"]),
                assessment_version=str(
                    instrument.get("assessment_version") or assessment_version
                ),
                target_level=str(instrument.get("target_level") or target_level),
                assessment_dates=assessment_dates,
                target_means=stored_targets,
                post_transfer_responses=(
                    record.get("transition_responses")
                    if isinstance(record.get("transition_responses"), Mapping)
                    else {}
                ),
            )
        )
    if warnings is not None and excluded_code_set:
        warnings.append(
            f"현재 프로젝트와 문항 코드 구성이 다른 누적 제출 {excluded_code_set}건을 집계에서 제외했습니다."
        )
    if warnings is not None and excluded_snapshot_hash:
        warnings.append(
            f"현재 프로젝트와 문항 스냅샷 버전이 다른 누적 제출 {excluded_snapshot_hash}건을 집계에서 제외했습니다."
        )
    return output


def build_session_dashboard(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build the company dashboard from this browser session only.

    The public MVP has no project/participant database.  Consequently this
    summary deliberately represents at most one project and one pseudonymous
    participant: the project and responses currently held in Streamlit's
    ``session_state``.  It must never imply organization-wide totals.
    """

    selected_factors = _string_list(state.get("selected_factors"))
    project_id = str(state.get("project_id") or "").strip()
    has_project = bool(project_id and selected_factors)

    responses_by_phase = state.get("responses_by_phase")
    if not isinstance(responses_by_phase, Mapping):
        responses_by_phase = {}
    pre_responses = _response_map(responses_by_phase.get("pre"))
    post_responses = _response_map(responses_by_phase.get("post"))

    completed_by_phase = state.get("assessment_completed_by_phase")
    if not isinstance(completed_by_phase, Mapping):
        completed_by_phase = {}
    pre_complete = has_project and bool(completed_by_phase.get("pre"))
    post_complete = has_project and bool(completed_by_phase.get("post"))

    participant_id = str(state.get("participant_id") or "").strip()
    has_participant = bool(
        participant_id or pre_responses or post_responses or pre_complete or post_complete
    )
    participant_count = int(has_participant)
    paired_count = int(has_participant and pre_complete and post_complete)

    completed_phases = int(pre_complete) + int(post_complete)
    phase_completion_pct = round(completed_phases / 2 * 100) if has_project else 0
    paired_completion_pct = (
        round(paired_count / participant_count * 100) if participant_count else 0
    )

    project_name = str(state.get("project_name") or "").strip() or "이름 없는 교육평가 프로젝트"
    metrics = [
        {
            "value": f"{int(has_project)}개",
            "label": "현재 세션 프로젝트",
            "note": project_name if has_project else "저장된 프로젝트 없음",
        },
        {
            "value": f"{participant_count}명",
            "label": "현재 세션 참여자",
            "note": "가명 ID 연결됨" if participant_id else "교육 참여자 ID 미입력",
        },
        {
            "value": _phase_label(has_project, pre_complete),
            "label": "교육 전 검사",
            "note": f"현재 세션 응답 {len(pre_responses)}개",
        },
        {
            "value": _phase_label(has_project, post_complete),
            "label": "교육 후 검사",
            "note": f"현재 세션 응답 {len(post_responses)}개",
        },
    ]

    projects: list[dict[str, Any]] = []
    if has_project:
        if pre_complete and post_complete:
            stage = "교육 전·후 검사 완료"
            status = "완료"
        elif pre_complete:
            stage = "교육 전 완료 · 교육 후 대기/진행"
            status = "진행 중"
        elif pre_responses:
            stage = "교육 전 검사 진행"
            status = "진행 중"
        else:
            stage = "교육 전 검사 준비"
            status = "준비"
        projects.append(
            {
                "name": project_name,
                "scope": (
                    f"현재 브라우저 세션 · 측정역량 {len(selected_factors)}개 · {stage}"
                ),
                # The row numerator, denominator and progress bar all describe
                # complete pre/post participant pairs. Phase progress is kept
                # separately for the explanatory caption on the home page.
                "invited": participant_count,
                "completed": paired_count,
                "completion_pct": paired_completion_pct,
                "status": status,
            }
        )

    return {
        "metrics": metrics,
        "projects": projects,
        "has_project": has_project,
        "participant_count": participant_count,
        "paired_count": paired_count,
        "phase_completion_pct": phase_completion_pct,
        "pre_response_count": len(pre_responses),
        "post_response_count": len(post_responses),
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [text for item in value if (text := str(item).strip())]


def _response_map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _phase_label(has_project: bool, complete: bool) -> str:
    if not has_project:
        return "대기"
    return "완료" if complete else "미완료"


def _latest_completed_submissions(
    submissions: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for source in submissions:
        if not isinstance(source, Mapping):
            continue
        project_id = str(source.get("project_id") or "").strip()
        participant_key = str(source.get("participant_key") or "").strip()
        phases = source.get("phases")
        if not project_id or not participant_key or not isinstance(phases, Mapping):
            continue
        stored_question_codes = _stored_question_codes(source.get("instrument"))
        if not stored_question_codes:
            continue
        if not any(
            _stored_phase_complete(phases.get(phase), stored_question_codes)
            for phase in ("pre", "post")
        ):
            continue
        record = dict(source)
        record["project_id"] = project_id
        record["participant_key"] = participant_key
        record["phases"] = dict(phases)
        key = (project_id, participant_key)
        previous = latest.get(key)
        if previous is None or str(record.get("updated_at") or "") >= str(
            previous.get("updated_at") or ""
        ):
            latest[key] = record
    return list(latest.values())


def _stored_phase_complete(
    value: Any,
    question_codes: Iterable[str] | None = None,
) -> bool:
    if not isinstance(value, Mapping) or not bool(value.get("completed")):
        return False
    responses = value.get("responses")
    if not isinstance(responses, Mapping) or not responses:
        return False
    if question_codes is None:
        return True
    expected = [str(code).strip() for code in question_codes]
    actual = [str(code).strip() for code in responses]
    return bool(expected) and len(actual) == len(expected) and set(actual) == set(expected)


def _stored_question_codes(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    raw_codes = value.get("question_snapshot_codes")
    if not isinstance(raw_codes, list):
        return []
    codes = [str(code).strip() for code in raw_codes]
    if not codes or any(not code for code in codes) or len(set(codes)) != len(codes):
        return []
    return codes


def _project_snapshots(
    projects: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    """Return the newest valid stored snapshot for every published project."""

    output: dict[str, dict[str, str]] = {}
    for project in projects:
        if not isinstance(project, Mapping):
            continue
        project_id = str(project.get("project_id") or "").strip()
        project_name = str(project.get("project_name") or "").strip()
        updated_at = str(
            project.get("updated_at") or project.get("created_at") or ""
        ).strip()
        if not project_id:
            continue
        previous = output.get(project_id)
        if previous is None or updated_at >= previous["updated_at"]:
            output[project_id] = {
                "project_name": project_name,
                "updated_at": updated_at,
            }
    return output


def _display_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "기록 없음"
    return text.replace("T", " ")[:16]


def validate_dashboard_demo(data: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(data) != {"company", "kma"}:
        errors.append("dashboard roles must be company and kma")

    company = data.get("company", {})
    projects = company.get("projects", [])
    if len(company.get("metrics", [])) != 4:
        errors.append("company dashboard must have four metrics")
    for project in projects:
        invited = int(project.get("invited", 0))
        completed = int(project.get("completed", 0))
        pct = int(project.get("completion_pct", -1))
        if invited < completed:
            errors.append(f"completed exceeds invited: {project.get('name')}")
        expected = round(completed / invited * 100) if invited else 0
        if pct != expected:
            errors.append(f"completion rate mismatch: {project.get('name')}")

    kma = data.get("kma", {})
    if len(kma.get("metrics", [])) != 4:
        errors.append("KMA dashboard must have four metrics")
    forbidden_fragments = ("score", "점수", "gap", "격차", "individual", "개인결과")
    for row in kma.get("organizations", []):
        for key in row:
            if any(fragment in str(key).lower() for fragment in forbidden_fragments):
                errors.append(f"KMA organization row exposes forbidden field: {key}")
    return errors
