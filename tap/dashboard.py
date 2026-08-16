from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Iterable, Mapping

from tap.config import DATA_DIR


@lru_cache(maxsize=1)
def load_dashboard_demo() -> dict[str, Any]:
    with (DATA_DIR / "dashboard_demo.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)


def completion_rate(projects: Iterable[Mapping[str, Any]]) -> float:
    invited = sum(int(row["invited"]) for row in projects)
    completed = sum(int(row["completed"]) for row in projects)
    return round(completed / invited * 100, 1) if invited else 0.0


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
