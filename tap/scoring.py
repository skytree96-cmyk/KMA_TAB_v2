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
    assessment_phase: str | None = None,
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
        row: dict[str, Any] = {
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
        if assessment_phase is not None:
            if assessment_phase not in {"pre", "post"}:
                raise ValueError("assessment_phase must be 'pre' or 'post'")
            row["assessment_phase"] = assessment_phase
        results.append(row)
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


def _paired_response_value(
    responses: Mapping[str, Any], question_code: str
) -> tuple[str, int | None]:
    if question_code not in responses or responses[question_code] in (None, ""):
        return "missing", None
    value = responses[question_code]
    if isinstance(value, bool) or value not in {0, 1, 2, 3, 4, 5}:
        raise ValueError(f"invalid response for {question_code}: {value}")
    if value == NA_VALUE:
        return "na", None
    return "valid", int(value)


def score_pre_post_responses(
    questions: Iterable[Mapping[str, Any]],
    pre_responses: Mapping[str, Any],
    post_responses: Mapping[str, Any],
    target_means: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Score change using only items answered validly at both time points.

    Missing and ``수행 기회 없음`` (0) responses stay distinct in the audit
    counts. A factor is reported only when the paired intersection satisfies the
    same completeness rule as a single assessment. The result describes an
    observed self-reported change; it does not claim causal training impact.
    """
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    seen_question_codes: set[str] = set()
    for question in questions:
        question_code = str(question["question_code"])
        if question_code in seen_question_codes:
            raise ValueError(f"duplicate question_code: {question_code}")
        seen_question_codes.add(question_code)
        grouped[str(question["factor_code"])].append(question)

    targets = target_means or {}
    rows: list[dict[str, Any]] = []
    for factor_code, items in grouped.items():
        paired_pre: list[int] = []
        paired_post: list[int] = []
        pre_na = post_na = pre_missing = post_missing = 0
        for item in items:
            code = str(item["question_code"])
            pre_status, pre_value = _paired_response_value(pre_responses, code)
            post_status, post_value = _paired_response_value(post_responses, code)
            pre_na += int(pre_status == "na")
            post_na += int(post_status == "na")
            pre_missing += int(pre_status == "missing")
            post_missing += int(post_status == "missing")
            if pre_status == "valid" and post_status == "valid":
                paired_pre.append(int(pre_value))
                paired_post.append(int(post_value))

        total_items = len(items)
        minimum = required_valid_items(total_items)
        valid = len(paired_pre) >= minimum
        pre_score = round(mean(paired_pre), 2) if valid else None
        post_score = round(mean(paired_post), 2) if valid else None
        change = round(post_score - pre_score, 2) if valid else None
        target = float(targets.get(factor_code, 3.5))
        rows.append(
            {
                "factor_code": factor_code,
                "factor_name_ko": items[0]["factor_name_ko"],
                "module_group": items[0]["module_group"],
                "pre_score": pre_score,
                "post_score": post_score,
                "self_reported_change": change,
                "pre_index_100": round((pre_score - 1) * 25, 1) if pre_score is not None else None,
                "post_index_100": round((post_score - 1) * 25, 1) if post_score is not None else None,
                "change_index_100": round(change * 25, 1) if change is not None else None,
                "paired_valid_items": len(paired_pre),
                "required_paired_items": minimum,
                "total_items": total_items,
                "dropped_unpaired_items": total_items - len(paired_pre),
                "pre_na_items": pre_na,
                "post_na_items": post_na,
                "pre_missing_items": pre_missing,
                "post_missing_items": post_missing,
                "target_mean": target,
                "pre_gap_to_target": (
                    round(max(0.0, target - pre_score), 2) if pre_score is not None else None
                ),
                "post_gap_to_target": (
                    round(max(0.0, target - post_score), 2) if post_score is not None else None
                ),
                "status": "산출" if valid else "미산출",
                "comparison_basis": "동일 문항 교집합",
                "interpretation": "교육 전후 관찰된 자기보고 변화",
            }
        )
    return sorted(rows, key=lambda row: (row["module_group"], row["factor_code"]))
