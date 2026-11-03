from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

# 개인 리포트에 노출하는 소스와 역량당 슬롯 수. 교육문의형(b2b_inquiry)은 조직 리포트 전용이다.
INDIVIDUAL_SLOTS: tuple[tuple[str, int], ...] = (("public_edu_center", 1), ("studio_elearning", 1))
ORGANIZATION_SLOTS: tuple[tuple[str, int], ...] = (
    ("public_edu_center", 1),
    ("studio_elearning", 1),
    ("b2b_inquiry", 1),
)
SUPPLEMENT_SOURCE = "studio_original"


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


_TITLE_PREFIX = re.compile(r"^(\[[^\]]+\]\s*)+")
_YEAR_TAIL = re.compile(r"\(\s*20\d\d\s*\)")
_NON_WORD = re.compile(r"[^0-9a-z가-힣]")


def normalize_course_title(title: str) -> str:
    """지점([여의도]/[강남]/[비대면])·연도 꼬리가 다른 같은 과정을 하나로 묶기 위한 키."""
    text = _TITLE_PREFIX.sub("", str(title or ""))
    text = _YEAR_TAIL.sub("", text).lower()
    return _NON_WORD.sub("", text)


def select_gap_factors(
    factor_results: Iterable[Mapping[str, Any]],
    *,
    organization_priorities: set[str] | None = None,
    priority_first: bool = False,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """목표 격차가 있는 산출 역량을 격차 큰 순으로 고른다. 조직 리포트는 조직 우선역량을 먼저 둔다."""
    priorities = organization_priorities or set()
    candidates = [
        dict(row)
        for row in factor_results
        if row.get("status", "산출") == "산출" and float(row.get("gap_to_target") or 0) > 0
    ]
    candidates.sort(
        key=lambda row: (
            (str(row["factor_code"]) not in priorities) if priority_first else False,
            -float(row["gap_to_target"]),
            str(row.get("factor_name_ko", "")),
        )
    )
    return candidates[:limit]


def recommend_for_factors(
    factor_results: Iterable[Mapping[str, Any]],
    course_rows: Iterable[Mapping[str, Any]],
    mapping_rows: Iterable[Mapping[str, Any]],
    *,
    organization_priorities: set[str] | None = None,
    learner_interests: set[str] | None = None,
    target_level: str = "all",
    delivery_preference: str = "all",
    training_cause: str = "mixed_or_unknown",
    top_factors: int = 3,
    slots: tuple[tuple[str, int], ...] = INDIVIDUAL_SLOTS,
    supplement_limit: int = 2,
    priority_first: bool = False,
) -> list[dict[str, Any]]:
    """역량을 먼저 격차순으로 고른 뒤, 역량마다 소스별 슬롯(공개교육 1·이러닝 1 …)을 채운다.

    - 같은 과정(정규화 제목)은 전체 결과에서 한 번만 쓰고 다음 후보로 backfill한다.
    - 공개교육은 다음 기수가 있는 과정(active)만 쓴다.
    - 기존 100점 산식은 한 역량 안에서 과정 순서를 정하는 데만 쓴다.
    """
    if TRAINING_GATE.get(training_cause, 0.0) == 0.0:
        return []
    priorities = organization_priorities or set()
    interests = learner_interests or set()
    courses = {str(row["course_id"]): row for row in course_rows if row.get("active", True)}
    mappings_by_factor: dict[str, list[Mapping[str, Any]]] = {}
    for mapping in mapping_rows:
        mappings_by_factor.setdefault(str(mapping["factor_code"]), []).append(mapping)

    selected = select_gap_factors(
        factor_results,
        organization_priorities=priorities,
        priority_first=priority_first,
        limit=top_factors,
    )
    seen_titles: set[str] = set()
    seen_ids: set[str] = set()
    blocks: list[dict[str, Any]] = []
    for factor in selected:
        code = str(factor["factor_code"])
        scored: list[dict[str, Any]] = []
        for mapping in mappings_by_factor.get(code, []):
            course = courses.get(str(mapping["course_id"]))
            if not course:
                continue
            level_fit = course.get("target_level", "all") in {"all", target_level}
            delivery_fit = delivery_preference == "all" or course.get("delivery") == delivery_preference
            parts = recommendation_score(
                gap_to_target=float(factor["gap_to_target"]),
                content_fit=float(mapping["content_fit"]),
                organization_priority=code in priorities,
                learner_interest=code in interests,
                level_fit=level_fit,
                delivery_fit=delivery_fit,
                training_cause=training_cause,
            )
            scored.append(
                {
                    **course,
                    "factor_code": code,
                    "factor_name_ko": factor.get("factor_name_ko", code),
                    "mapping_rationale": mapping.get("rationale", ""),
                    "title_key": normalize_course_title(course.get("title", "")),
                    **parts,
                }
            )
        # 같은 점수면 다음 개강일이 가까운 순, 그다음 과정코드 순으로 고정한다.
        scored.sort(
            key=lambda row: (
                -float(row["recommendation_score"]),
                str(row.get("next_start") or "99999999"),
                str(row["course_id"]),
            )
        )

        def take(source: str, count: int) -> list[dict[str, Any]]:
            picked: list[dict[str, Any]] = []
            for row in scored:
                if len(picked) >= count:
                    break
                if row.get("source") != source:
                    continue
                if row["title_key"] in seen_titles or row["course_id"] in seen_ids:
                    continue
                seen_titles.add(row["title_key"])
                seen_ids.add(str(row["course_id"]))
                picked.append(row)
            return picked

        block_courses: list[dict[str, Any]] = []
        for source, count in slots:
            block_courses.extend(take(source, count))
        supplements = take(SUPPLEMENT_SOURCE, supplement_limit) if supplement_limit else []
        blocks.append(
            {
                **factor,
                "courses": block_courses,
                "supplements": supplements,
            }
        )
    return blocks
