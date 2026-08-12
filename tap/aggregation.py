from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any, Iterable, Mapping

from tap.config import MIN_GROUP_N


def aggregate_factor_results(
    rows: Iterable[Mapping[str, Any]], min_group_n: int = MIN_GROUP_N
) -> list[dict[str, Any]]:
    participant_scores: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    names: dict[str, str] = {}
    for row in rows:
        if row.get("score_1_to_5") in (None, ""):
            continue
        code = str(row["factor_code"])
        participant_id = str(row["participant_id"])
        participant_scores[code][participant_id].append(float(row["score_1_to_5"]))
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
