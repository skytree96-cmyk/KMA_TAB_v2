"""Report insights beyond pre/post scores: transfer climate, course follow-up and detail export.

Pure functions only, so the Streamlit screens and the PDF share one calculation.
"""
from __future__ import annotations

from statistics import mean
from typing import Any, Iterable, Mapping

from tap.config import MIN_GROUP_N
from tap.data import load_course_map, load_courses
from tap.recommendation import TRAINING_GATE, normalize_course_title


TRANSFER_FACTORS = (
    ("application_opportunity", "적용 기회"),
    ("supervisor_support", "상사·리더 지원"),
    ("resources_authority", "도구·정보·권한"),
    ("time_process_support", "시간·프로세스"),
)
BARRIERS = ("적용 기회 부족", "상사·동료 지원 부족", "도구·정보·권한 부족", "시간·프로세스 제약", "특별한 방해요인 없음")
DELIVERY_LABELS = {"online": "온라인", "offline": "집합", "online_live": "온라인 라이브", "inhouse": "사내교육",
                   "online_short": "온라인"}
# Per competency, one public course then one e-learning course; organizations also see the in-house
# inquiry course. The source order flips when the project prefers online delivery.
SOURCE_SLOTS = {"individual": (("public_edu_center", 1), ("studio_elearning", 1)),
                "organization": (("public_edu_center", 1), ("studio_elearning", 1), ("b2b_inquiry", 1))}
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


def recommend_courses(config: Mapping[str, Any], factor_rows: Iterable[Mapping[str, Any]], limit: int = 4, *,
                      audience: str = "individual", score_key: str = "post_score",
                      max_competencies: int = 3) -> list[dict[str, Any]]:
    """Pick courses for competencies at least 0.2 below the project target.

    factor_rows need factor_code, factor_name_ko and the score under ``score_key`` (post_score after
    training, score_1_to_5 for the pre-training report) and may carry pre_score; rows without a score
    are skipped. Larger gaps come first (gaps in the same 0.1 band tie, and the organization's priority
    competencies break the tie). Courses are filled source by source: every competency gets its best
    public course (only courses with an upcoming session), then its best e-learning course, and
    organizations also get an in-house inquiry course. The same course — a second location or next
    year's run of the same title — is never shown twice.
    """
    if TRAINING_GATE.get(str(config.get("training_cause") or "mixed_or_unknown"), 0.0) == 0.0:
        return []
    targets = config.get("target_means") or {}
    priorities = {str(code) for code in config.get("organization_priorities") or []}
    needs = []
    for row in factor_rows:
        if row.get(score_key) is None:
            continue
        code, score = str(row["factor_code"]), float(row[score_key])
        target = float(targets.get(code, 3.5))
        gap = round(target - score, 2)
        if gap < MEANINGFUL_DIFFERENCE:
            continue
        pre = row.get("pre_score") if score_key == "post_score" else None
        needs.append({"factor_code": code, "factor_name_ko": row["factor_name_ko"], "score": score, "target": target,
                      "gap": gap, "change": None if pre is None else round(score - float(pre), 2),
                      "phase": "post" if score_key == "post_score" else "pre"})
    needs.sort(key=lambda need: (-round(need["gap"], 1), need["factor_code"] not in priorities, need["factor_code"]))
    # Only the few competencies furthest from target: a report that lists courses for every competency
    # stops being a recommendation.
    needs = needs[:max_competencies]

    level = str(config.get("target_level") or "all")
    preference = str(config.get("delivery_preference") or "all")
    # A course written for one level (e.g. team leaders) is never offered to another level, and a public
    # course without an upcoming session is not offered at all (active == has_upcoming in the catalog).
    catalog = {str(row["course_id"]): row for row in load_courses()
               if row.get("active", True) and row.get("target_level", "all") in {"all", level}}
    queues: dict[str, list[dict[str, Any]]] = {}
    for need in needs:
        mappings = [mapping for mapping in load_course_map()
                    if mapping["factor_code"] == need["factor_code"] and str(mapping["course_id"]) in catalog]
        mappings.sort(key=lambda mapping: (-float(mapping["content_fit"]),
                                           str(catalog[str(mapping["course_id"])].get("next_start") or "99999999"),
                                           str(mapping["course_id"])))
        queues[need["factor_code"]] = [catalog[str(mapping["course_id"])] for mapping in mappings]

    slots = list(SOURCE_SLOTS.get(audience, SOURCE_SLOTS["individual"]))
    if preference == "online":
        slots.sort(key=lambda slot: slot[0] != "studio_elearning")
    elif preference == "offline":
        slots.sort(key=lambda slot: slot[0] != "public_edu_center")
    allowed = {source for source, _ in slots}

    picked: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()

    def take(need: Mapping[str, Any], source: str | None) -> bool:
        for course in queues[need["factor_code"]]:
            course_id = str(course["course_id"])
            course_source = str(course.get("source", ""))
            if course_id in seen_ids or course_source not in allowed:
                continue
            if source is not None and course_source != source:
                continue
            title_key = normalize_course_title(course.get("title", ""))
            if title_key in seen_titles:
                continue
            seen_ids.add(course_id)
            seen_titles.add(title_key)
            reason = _course_reason(need)
            if any(row["factor_code"] == need["factor_code"] for row in picked):
                reason["advice"] = ""  # say what the change suggests once per competency, not under every course
            picked.append({**course, "factor_code": need["factor_code"], "factor_name_ko": need["factor_name_ko"],
                           "delivery_label": DELIVERY_LABELS.get(str(course.get("delivery")), "온라인·집합"),
                           "schedule": course_schedule_text(course), **reason})
            return True
        return False

    # Source by source so every competency gets its public course before any gets an e-learning one.
    for source, count in slots:
        for need in needs:
            for _ in range(count):
                if len(picked) >= limit or not take(need, source):
                    break
    # Fill any remaining room round-robin from whatever is left, as the earlier version did.
    progressed = True
    while len(picked) < limit and progressed:
        progressed = False
        for need in needs:
            if len(picked) < limit and take(need, None):
                progressed = True
    return picked


def course_schedule_text(course: Mapping[str, Any]) -> str:
    """One line a reader can act on: next session date and place, or 'available any time'."""
    source = str(course.get("source", ""))
    if source == "public_edu_center":
        start = str(course.get("next_start") or "")
        bits = [f"다음 개강 {start[:4]}-{start[4:6]}-{start[6:]}" if len(start) == 8 else "일정은 과정 페이지에서 확인"]
        bits.extend(str(course[key]) + suffix for key, suffix in (("place", ""), ("edu_day", "일"), ("edu_time", "시간"))
                    if course.get(key))
        return " · ".join(bits)
    if source == "studio_elearning":
        return "온라인 · 상시 수강"
    if source == "b2b_inquiry":
        return "사내교육 · 인원을 모아 KMA에 문의"
    return DELIVERY_LABELS.get(str(course.get("delivery")), "")


def _course_reason(need: Mapping[str, Any]) -> dict[str, Any]:
    """The numbers behind a pick, and what the pre/post change suggests doing with it."""
    phase_label = "교육 후" if need.get("phase") == "post" else "교육 전"
    reason = f"{phase_label} {need['score']:.2f}점, 목표 {need['target']:.2f}점보다 {need['gap']:.2f}점 낮음"
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
