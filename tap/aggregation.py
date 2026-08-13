from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean
from typing import Any, Iterable, Mapping

from tap.config import MIN_GROUP_N


def _valid_score(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score) or not 1.0 <= score <= 5.0:
        return None
    return score


def aggregate_factor_results(
    rows: Iterable[Mapping[str, Any]], min_group_n: int = MIN_GROUP_N
) -> list[dict[str, Any]]:
    participant_scores: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    names: dict[str, str] = {}
    for row in rows:
        score = _valid_score(row.get("score_1_to_5"))
        participant_id = str(row.get("participant_id", "")).strip()
        if score is None or not participant_id:
            continue
        code = str(row["factor_code"])
        participant_scores[code][participant_id].append(score)
        names[code] = str(row.get("factor_name_ko", code))
    out: list[dict[str, Any]] = []
    for code, by_participant in participant_scores.items():
        # 동일 참여자의 중복 행은 먼저 개인 평균으로 축약해 N을 부풀리지 않는다.
        values = [mean(person_values) for person_values in by_participant.values()]
        if len(values) < min_group_n:
            out.append(
                {
                    "factor_code": code,
                    "factor_name_ko": names[code],
                    "n": len(values),
                    "group_mean": None,
                    "status": f"비공개(N<{min_group_n})",
                }
            )
        else:
            out.append(
                {
                    "factor_code": code,
                    "factor_name_ko": names[code],
                    "n": len(values),
                    "group_mean": round(mean(values), 2),
                    "status": "공개",
                }
            )
    return sorted(out, key=lambda x: x["factor_code"])


def _normalise_phase(value: Any) -> str | None:
    phase = str(value or "").strip().lower()
    aliases = {"pre": "pre", "post": "post", "사전": "pre", "사후": "post"}
    return aliases.get(phase)


def aggregate_paired_factor_results(
    rows: Iterable[Mapping[str, Any]], min_group_n: int = MIN_GROUP_N
) -> list[dict[str, Any]]:
    """Aggregate pre/post change from the same participants only.

    Both long rows (``assessment_phase`` + ``score_1_to_5``) and already-paired
    rows (``pre_score`` + ``post_score``) are accepted. Missing, NA, non-finite,
    and out-of-range scores are excluded independently at each phase. Duplicate
    rows are collapsed to a participant-phase mean before N or change is counted.
    """
    if min_group_n < 1:
        raise ValueError("min_group_n must be at least 1")

    participant_scores: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: {"pre": [], "post": []})
    )
    names: dict[str, str] = {}
    seen_codes: set[str] = set()
    for row in rows:
        if "factor_code" not in row:
            continue
        code = str(row["factor_code"])
        seen_codes.add(code)
        names[code] = str(row.get("factor_name_ko", names.get(code, code)))
        participant_id = str(row.get("participant_id", "")).strip()
        if not participant_id:
            continue

        if "pre_score" in row or "post_score" in row:
            for phase, key in (("pre", "pre_score"), ("post", "post_score")):
                score = _valid_score(row.get(key))
                if score is not None:
                    participant_scores[code][participant_id][phase].append(score)
            continue

        phase = _normalise_phase(row.get("assessment_phase", row.get("phase")))
        score = _valid_score(row.get("score_1_to_5"))
        if phase is not None and score is not None:
            participant_scores[code][participant_id][phase].append(score)

    output: list[dict[str, Any]] = []
    for code in seen_codes:
        by_participant = participant_scores.get(code, {})
        pre_by_person = {
            participant_id: mean(values["pre"])
            for participant_id, values in by_participant.items()
            if values["pre"]
        }
        post_by_person = {
            participant_id: mean(values["post"])
            for participant_id, values in by_participant.items()
            if values["post"]
        }
        paired_ids = sorted(set(pre_by_person) & set(post_by_person))
        paired_n = len(paired_ids)
        pre_n = len(pre_by_person)
        post_n = len(post_by_person)
        attrition_ids = set(pre_by_person) - set(post_by_person)
        post_only_ids = set(post_by_person) - set(pre_by_person)
        disclosed = paired_n >= min_group_n
        paired_pre = [pre_by_person[participant_id] for participant_id in paired_ids]
        paired_post = [post_by_person[participant_id] for participant_id in paired_ids]
        changes = [post - pre for pre, post in zip(paired_pre, paired_post)]
        pre_mean = round(mean(paired_pre), 2) if disclosed else None
        post_mean = round(mean(paired_post), 2) if disclosed else None
        observed_change = round(mean(changes), 2) if disclosed else None
        output.append(
            {
                "factor_code": code,
                "factor_name_ko": names.get(code, code),
                "pre_n": pre_n,
                "post_n": post_n,
                "paired_n": paired_n,
                "n": paired_n,
                "attrition_n": len(attrition_ids),
                "attrition_rate": round(len(attrition_ids) / pre_n * 100, 1) if pre_n else None,
                "post_only_n": len(post_only_ids),
                "pre_mean": pre_mean,
                "post_mean": post_mean,
                "observed_change": observed_change,
                "self_reported_change": observed_change,
                # Compatibility for consumers that previously displayed one
                # group mean; for a pre/post row it represents the paired post.
                "group_mean": post_mean,
                "status": "공개" if disclosed else f"비공개(짝지어진 N<{min_group_n})",
                "comparison_basis": "동일 참여자 짝지어진 결과",
                "interpretation": "교육 전후 관찰된 자기보고 변화",
            }
        )
    return sorted(output, key=lambda row: row["factor_code"])


def aggregate_pre_post_results(
    rows: Iterable[Mapping[str, Any]], min_group_n: int = MIN_GROUP_N
) -> list[dict[str, Any]]:
    """Backward-friendly descriptive alias for paired factor aggregation."""
    return aggregate_paired_factor_results(rows, min_group_n=min_group_n)
