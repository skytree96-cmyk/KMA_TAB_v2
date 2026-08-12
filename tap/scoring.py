from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import mean
from typing import Any, Iterable, Mapping

from tap.config import FREQUENCY_LEVELS, MIN_VALID_ITEMS, NA_VALUE


def response_to_index(value: int) -> float | None:
    """Convert a 1-5 behavior-frequency response to 0-100; 0 is NA."""
    if value == NA_VALUE:
        return None
    if value not in {1, 2, 3, 4, 5}:
        raise ValueError(f"response must be 0..5, got {value}")
    return float((value - 1) * 25)


def frequency_level(score_1_to_5: float) -> str:
    for threshold, label in FREQUENCY_LEVELS:
        if score_1_to_5 >= threshold:
            return label
    raise ValueError("score must be between 1 and 5")


def required_valid_items(total_items: int) -> int:
    """Operational completeness rule; empirical validation may revise it."""
    if total_items <= 0:
        return 0
    return min(total_items, max(MIN_VALID_ITEMS, math.ceil(total_items * 0.75)))


def score_responses(
    questions: Iterable[Mapping[str, Any]],
    responses: Mapping[str, int],
    target_means: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for question in questions:
        grouped[str(question["factor_code"])].append(question)

    targets = target_means or {}
    results: list[dict[str, Any]] = []
    for factor_code, items in grouped.items():
        valid_values: list[int] = []
        na_count = 0
        missing_count = 0
        for item in items:
            question_code = str(item["question_code"])
            if question_code not in responses:
                missing_count += 1
                continue
            value = responses[question_code]
            if value == NA_VALUE:
                na_count += 1
            elif value in {1, 2, 3, 4, 5}:
                valid_values.append(value)
            else:
                raise ValueError(f"invalid response for {item['question_code']}: {value}")

        minimum = required_valid_items(len(items))
        valid = len(valid_values) >= minimum
        target = float(targets.get(factor_code, 3.5))
        raw_mean = round(mean(valid_values), 2) if valid else None
        index_100 = round((raw_mean - 1) * 25, 1) if raw_mean is not None else None
        gap = round(max(0.0, target - raw_mean), 2) if raw_mean is not None else None
        results.append(
            {
                "factor_code": factor_code,
                "factor_name_ko": items[0]["factor_name_ko"],
                "module_group": items[0]["module_group"],
                "valid_items": len(valid_values),
                "total_items": len(items),
                "na_items": na_count,
                "missing_items": missing_count,
                "status": "산출" if valid else "미산출",
                "score_1_to_5": raw_mean,
                "index_100": index_100,
                "frequency_level": frequency_level(raw_mean) if raw_mean is not None else "유효응답 부족",
                "target_mean": target,
                "gap_to_target": gap,
            }
        )
    return sorted(results, key=lambda x: (x["module_group"], x["factor_code"]))


def response_quality_flags(
    responses: Mapping[str, int],
    duration_seconds: float | None = None,
) -> list[str]:
    """Flags are cautions, never automatic invalidation decisions."""
    flags: list[str] = []
    values = [v for v in responses.values() if v in {1, 2, 3, 4, 5}]
    total = len(responses)
    if values and duration_seconds is not None and duration_seconds / len(values) < 2.5:
        flags.append("응답 속도 확인 필요")
    if len(values) >= 12:
        dominant_share = Counter(values).most_common(1)[0][1] / len(values)
        if dominant_share >= 0.90:
            flags.append("동일응답 반복 확인 필요")
    if total and sum(v == NA_VALUE for v in responses.values()) / total > 0.40:
        flags.append("수행 기회 없음 응답 비율 높음")
    return flags


def compare_pre_post(
    pre_results: Iterable[Mapping[str, Any]],
    post_results: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return self-reported behavior-frequency change, not training ROI/effect."""
    pre = {str(r["factor_code"]): r for r in pre_results}
    rows: list[dict[str, Any]] = []
    for post in post_results:
        factor_code = str(post["factor_code"])
        before = pre.get(factor_code)
        pre_score = before.get("score_1_to_5") if before else None
        post_score = post.get("score_1_to_5")
        change = round(post_score - pre_score, 2) if pre_score is not None and post_score is not None else None
        rows.append(
            {
                "factor_code": factor_code,
                "pre_score": pre_score,
                "post_score": post_score,
                "self_reported_change": change,
            }
        )
    return rows
