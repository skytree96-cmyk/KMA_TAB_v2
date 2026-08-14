from __future__ import annotations

from typing import Any, Iterable, Mapping


TRAINING_GATE = {
    "knowledge_skill": 1.0,
    # 원인 미확인은 정보의 부재이지 교육효과가 절반이라는 근거가 아니다.
    # 프로젝트 생성 단계의 중립 기본값이 점수를 왜곡하지 않도록 1.0을 적용한다.
    "mixed_or_unknown": 1.0,
    "system_only": 0.0,
}


def recommendation_score(
    *,
    gap_to_target: float,
    content_fit: float,
    organization_priority: bool,
    learner_interest: bool,
    level_fit: bool,
    delivery_fit: bool,
    training_cause: str,
) -> dict[str, float]:
    if training_cause not in TRAINING_GATE:
        raise ValueError(f"unknown training_cause: {training_cause}")
    gap_points = min(40.0, max(0.0, gap_to_target) / 4.0 * 40.0)
    content_points = min(30.0, max(0.0, content_fit) * 30.0)
    priority_points = 15.0 if organization_priority else 0.0
    interest_points = 10.0 if learner_interest else 0.0
    context_points = (3.0 if level_fit else 0.0) + (2.0 if delivery_fit else 0.0)
    base = gap_points + content_points + priority_points + interest_points + context_points
    gate = TRAINING_GATE[training_cause]
    return {
        "gap_points": round(gap_points, 1),
        "content_points": round(content_points, 1),
        "priority_points": priority_points,
        "interest_points": interest_points,
        "context_points": context_points,
        "training_gate": gate,
        "recommendation_score": round(base * gate, 1),
    }


def rank_courses(
    factor_results: Iterable[Mapping[str, Any]],
    course_rows: Iterable[Mapping[str, Any]],
    mapping_rows: Iterable[Mapping[str, Any]],
    *,
    organization_priorities: set[str] | None = None,
    learner_interests: set[str] | None = None,
    target_level: str = "all",
    delivery_preference: str = "all",
    training_cause: str = "mixed_or_unknown",
    limit: int = 6,
) -> list[dict[str, Any]]:
    if TRAINING_GATE.get(training_cause, 0.0) == 0.0:
        return []
    priorities = organization_priorities or set()
    interests = learner_interests or set()
    result_by_factor = {
        str(row["factor_code"]): row
        for row in factor_results
        if row.get("status") == "산출" and (row.get("gap_to_target") or 0) > 0
    }
    courses = {str(row["course_id"]): row for row in course_rows if row.get("active", True)}
    ranked: list[dict[str, Any]] = []
    for mapping in mapping_rows:
        factor_code = str(mapping["factor_code"])
        result = result_by_factor.get(factor_code)
        course = courses.get(str(mapping["course_id"]))
        if not result or not course:
            continue
        level_fit = course.get("target_level", "all") in {"all", target_level}
        delivery_fit = delivery_preference == "all" or course.get("delivery") == delivery_preference
        parts = recommendation_score(
            gap_to_target=float(result["gap_to_target"]),
            content_fit=float(mapping["content_fit"]),
            organization_priority=factor_code in priorities,
            learner_interest=factor_code in interests,
            level_fit=level_fit,
            delivery_fit=delivery_fit,
            training_cause=training_cause,
        )
        ranked.append(
            {
                **course,
                "factor_code": factor_code,
                "factor_name_ko": result["factor_name_ko"],
                "mapping_rationale": mapping["rationale"],
                **parts,
            }
        )
    ranked.sort(key=lambda row: (-float(row["recommendation_score"]), str(row["course_id"])))
    return ranked[:limit]
