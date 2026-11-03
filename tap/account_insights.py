"""Report insights beyond pre/post scores: transfer climate, course follow-up and detail export.

Pure functions only, so the Streamlit screens and the PDF share one calculation.
"""
from __future__ import annotations

from statistics import mean
from typing import Any, Iterable, Mapping

from tap.config import MIN_GROUP_N
from tap.data import load_course_map, load_courses
from tap.recommendation import rank_courses


TRANSFER_FACTORS = (
    ("application_opportunity", "적용 기회"),
    ("supervisor_support", "상사·리더 지원"),
    ("resources_authority", "도구·정보·권한"),
    ("time_process_support", "시간·프로세스"),
)
BARRIERS = ("적용 기회 부족", "상사·동료 지원 부족", "도구·정보·권한 부족", "시간·프로세스 제약", "특별한 방해요인 없음")
DELIVERY_LABELS = {"online": "온라인", "offline": "집합"}
# Below this mean the transfer factor is called out as a follow-up item.
TRANSFER_ATTENTION_MEAN = 3.0


def _complete_transfer(transfer: Any) -> bool:
    return isinstance(transfer, Mapping) and all(
        type(transfer.get(code)) is int and 1 <= transfer[code] <= 5 for code, _ in TRANSFER_FACTORS)


def summarize_transfer(results: Iterable[Mapping[str, Any]], min_n: int = MIN_GROUP_N) -> dict[str, Any]:
    """Average the post-assessment transfer climate; nothing is disclosed below min_n respondents.

    Free-text applied content is never aggregated, so individual answers cannot surface here.
    """
    responses = [transfer for result in results if result.get("post_completed")
                 for transfer in [(result.get("post_payload") or {}).get("post_transfer_responses")]
                 if _complete_transfer(transfer)]
    n = len(responses)
    disclosed = n >= min_n
    factors = [{"code": code, "label": label,
                "mean": round(mean(transfer[code] for transfer in responses), 2) if disclosed else None}
               for code, label in TRANSFER_FACTORS]
    barriers = []
    if disclosed:
        for barrier in BARRIERS:
            count = sum(barrier in (transfer.get("barriers") or []) for transfer in responses)
            barriers.append({"label": barrier, "count": count, "rate": round(count / n * 100)})
    return {"n": n, "disclosed": disclosed, "factors": factors, "barriers": barriers}


def transfer_notes(summary: Mapping[str, Any]) -> list[str]:
    """Plain follow-up sentences for the weakest transfer conditions and the most common barrier."""
    if not summary.get("disclosed"):
        return []
    notes = [f"{row['label']} 평균이 {row['mean']:.2f}점으로 낮아, 교육 내용이 현업에서 쓰이도록 이 조건을 먼저 보완해 보세요."
             for row in sorted(summary["factors"], key=lambda row: row["mean"])
             if row["mean"] < TRANSFER_ATTENTION_MEAN]
    top = max((row for row in summary["barriers"] if row["label"] != "특별한 방해요인 없음" and row["count"]),
              key=lambda row: row["count"], default=None)
    if top:
        notes.append(f"가장 많이 꼽힌 적용 장애요인은 '{top['label']}'({top['rate']}%)입니다.")
    if not notes:
        notes.append("네 가지 현업 적용 조건이 모두 보통 이상으로 응답되었습니다. 적용 사례를 공유해 확산해 보세요.")
    return notes


def recommend_courses(config: Mapping[str, Any], factor_rows: Iterable[Mapping[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    """Rank follow-up courses for competencies whose post score is still below the project target.

    factor_rows need factor_code, factor_name_ko and post_score; rows without a post score are skipped.
    Each course appears once, under the competency that ranked it highest.
    """
    targets = config.get("target_means") or {}
    factor_results = [{"factor_code": str(row["factor_code"]), "factor_name_ko": row["factor_name_ko"], "status": "산출",
                       "post_score": row["post_score"],
                       "gap_to_target": round(float(targets.get(str(row["factor_code"]), 3.5)) - float(row["post_score"]), 2)}
                      for row in factor_rows if row.get("post_score") is not None]
    ranked = rank_courses(
        factor_results, load_courses(), load_course_map(),
        organization_priorities=set(config.get("organization_priorities") or []),
        learner_interests=set(config.get("learner_interests") or []),
        target_level=str(config.get("target_level") or "all"),
        delivery_preference=str(config.get("delivery_preference") or "all"),
        training_cause=str(config.get("training_cause") or "mixed_or_unknown"),
        limit=len(factor_results) * 10,
    )
    picked: dict[str, dict[str, Any]] = {}
    for row in ranked:
        picked.setdefault(str(row["course_id"]), row)
    courses = list(picked.values())[:limit]
    for row in courses:
        row["delivery_label"] = DELIVERY_LABELS.get(str(row.get("delivery")), "온라인·집합")
    return courses


def organization_detail_rows(summaries: Iterable[Mapping[str, Any]], config: Mapping[str, Any],
                             transfer: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One flat table for the detail CSV: competencies, transfer climate and barriers.

    Scores of undisclosed competencies are already None in the summaries; only counts remain.
    """
    targets = config.get("target_means") or {}
    rows = [{"구분": "역량", "항목": row["factor_name_ko"], "사전 응답": row["pre_n"], "사후 응답": row["post_n"],
             "전·후 유효 인원": row["paired_n"], "사후 미응답": row["attrition_n"],
             "교육 전": row["pre_mean"], "교육 후": row["post_mean"], "변화": row["observed_change"],
             "목표 수준": targets.get(row["factor_code"]),
             "목표 대비": round(row["post_mean"] - float(targets[row["factor_code"]]), 2)
             if row["post_mean"] is not None and row["factor_code"] in targets else None,
             "상태": row["status"]} for row in summaries]
    status = "공개" if transfer["disclosed"] else f"비공개(응답 N<{MIN_GROUP_N})"
    rows.extend({"구분": "현업전이 환경(1~5)", "항목": row["label"], "응답 수": transfer["n"], "평균": row["mean"], "상태": status}
                for row in transfer["factors"])
    rows.extend({"구분": "적용 장애요인", "항목": row["label"], "응답 수": row["count"], "비율(%)": row["rate"], "상태": status}
                for row in transfer["barriers"])
    return rows
