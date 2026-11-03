"""Report insights beyond pre/post scores: transfer climate, course follow-up and detail export.

Pure functions only, so the Streamlit screens and the PDF share one calculation.
"""
from __future__ import annotations

from statistics import mean
from typing import Any, Iterable, Mapping

from tap.config import MIN_GROUP_N
from tap.data import load_course_map, load_courses
from tap.recommendation import TRAINING_GATE


TRANSFER_FACTORS = (
    ("application_opportunity", "적용 기회"),
    ("supervisor_support", "상사·리더 지원"),
    ("resources_authority", "도구·정보·권한"),
    ("time_process_support", "시간·프로세스"),
)
BARRIERS = ("적용 기회 부족", "상사·동료 지원 부족", "도구·정보·권한 부족", "시간·프로세스 제약", "특별한 방해요인 없음")
DELIVERY_LABELS = {"online": "온라인", "offline": "집합"}
# KMA's inquiry page, where HR teams request training tailored to their company.
COURSE_INQUIRY_URL = "https://www.kma.or.kr/kr/usrs/eduRegMgnt/eduRegMgntForm.do?cateNm=customerInquiry"
# Below this mean the transfer factor is called out as a follow-up item.
TRANSFER_ATTENTION_MEAN = 3.0
# The report calls a pre/post difference under 0.2 "유지". A gap to target that small is within
# self-report noise, so it does not call for a course; a rise of 0.2 or more means change is under way.
MEANINGFUL_DIFFERENCE = 0.2


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
    """Pick follow-up courses for competencies still at least 0.2 below the project target after training.

    factor_rows need factor_code, factor_name_ko and post_score, and may carry pre_score; rows without a
    post score are skipped. Larger gaps come first (gaps in the same 0.1 band tie, and the organization's
    priority competencies break the tie). Every competency gets its best course before any gets a second,
    and each course appears once.
    """
    if TRAINING_GATE.get(str(config.get("training_cause") or "mixed_or_unknown"), 0.0) == 0.0:
        return []
    targets = config.get("target_means") or {}
    priorities = {str(code) for code in config.get("organization_priorities") or []}
    needs = []
    for row in factor_rows:
        if row.get("post_score") is None:
            continue
        code, post = str(row["factor_code"]), float(row["post_score"])
        target = float(targets.get(code, 3.5))
        gap = round(target - post, 2)
        if gap < MEANINGFUL_DIFFERENCE:
            continue
        pre = row.get("pre_score")
        needs.append({"factor_code": code, "factor_name_ko": row["factor_name_ko"], "post": post, "target": target,
                      "gap": gap, "change": None if pre is None else round(post - float(pre), 2)})
    needs.sort(key=lambda need: (-round(need["gap"], 1), need["factor_code"] not in priorities, need["factor_code"]))

    level = str(config.get("target_level") or "all")
    preference = str(config.get("delivery_preference") or "all")
    # A course written for one level (e.g. team leaders) is never offered to another level.
    catalog = {str(row["course_id"]): row for row in load_courses()
               if row.get("active", True) and row.get("target_level", "all") in {"all", level}}
    queues = {need["factor_code"]: [str(mapping["course_id"]) for mapping in sorted(
        (mapping for mapping in load_course_map()
         if mapping["factor_code"] == need["factor_code"] and str(mapping["course_id"]) in catalog),
        key=lambda mapping: (preference != "all" and catalog[str(mapping["course_id"])].get("delivery") != preference,
                             -float(mapping["content_fit"]), str(mapping["course_id"])))] for need in needs}
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    while len(picked) < limit and any(queues.values()):
        for need in needs:
            queue = queues[need["factor_code"]]
            while queue and queue[0] in seen:
                queue.pop(0)
            if queue and len(picked) < limit:
                course = catalog[queue.pop(0)]
                seen.add(str(course["course_id"]))
                reason = _course_reason(need)
                if any(row["factor_code"] == need["factor_code"] for row in picked):
                    reason["advice"] = ""  # say what the change suggests once per competency, not under every course
                picked.append({**course, "factor_code": need["factor_code"], "factor_name_ko": need["factor_name_ko"],
                               "delivery_label": DELIVERY_LABELS.get(str(course.get("delivery")), "온라인·집합"), **reason})
    return picked


def _course_reason(need: Mapping[str, Any]) -> dict[str, Any]:
    """The numbers behind a pick, and what the pre/post change suggests doing with it."""
    reason = f"교육 후 {need['post']:.2f}점, 목표 {need['target']:.2f}점보다 {need['gap']:.2f}점 낮음"
    change = need["change"]
    if change is None:
        return {"reason": reason, "advice": ""}
    reason += f" · 교육 전보다 {change:+.2f}점"
    if change >= MEANINGFUL_DIFFERENCE:
        advice = "교육 후 점수가 오르고 있습니다. 같은 주제의 심화 학습이나 현업 적용 과제로 이어가 보세요."
    elif change <= -MEANINGFUL_DIFFERENCE:
        advice = "교육 전보다 낮아졌습니다. 업무 변화나 적용 기회 감소가 있었는지 먼저 확인해 보세요."
    else:
        advice = "교육 전과 큰 차이가 없습니다. 과정 내용이 맞았는지와 현업 적용 여건을 함께 점검해 보세요."
    return {"reason": reason, "advice": advice}


def course_context_note(transfer: Mapping[str, Any] | None) -> str | None:
    """Put weak transfer conditions ahead of the course list: more training rarely fixes the work environment."""
    if not transfer or not transfer.get("disclosed"):
        return None
    weak = [row["label"] for row in transfer["factors"] if row["mean"] < TRANSFER_ATTENTION_MEAN]
    if not weak:
        return None
    return (f"현업 적용 조건({', '.join(weak)}) 평균이 {TRANSFER_ATTENTION_MEAN:.1f}점 미만입니다. "
            "과정을 더 듣기 전에 이 조건부터 보완해야 배운 내용이 현업에서 쓰일 수 있습니다.")


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
