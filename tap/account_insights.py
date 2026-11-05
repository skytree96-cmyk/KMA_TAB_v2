"""Report insights beyond pre/post scores: transfer climate, course follow-up and detail export.

Pure functions only, so the Streamlit screens and the PDF share one calculation.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from statistics import mean
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from tap.config import MIN_GROUP_N
from tap.course_schedule import live_session_starts
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
# A session that starts sooner than this cannot be acted on from a report: approval and registration take
# time. A public course is offered with its first session on or after the cutoff, or not at all.
MIN_DAYS_BEFORE_START = 7
# Words that say nothing about a course's subject. Two titles that share only these are different topics.
_GENERIC_TITLE_WORDS = frozenset("""
활용 활용법 활용한 활용의 실무 과정 스킬 위한 위해 기본 기초 입문 심화 완벽 하루 하루만에 끝내는 통하는 통한 직장인 직장인을
일잘러 일잘러의 일잘러라면 비즈니스 업무 방법 기법 노하우 실전 강의 마스터 클래스 아카이브 교육 이해 핵심 성공 성장 함께 함께하는
하는 만드는 기반 바로 써먹는 알아야 필요한 모든 여의도 비대면 상시개강 테크닉 역량 개발 향상 전문가 양성 워크숍 실습 사례 트레이닝
hd part biz with the and for of ok tool
""".split())
_TITLE_TOKEN = re.compile(r"[a-z0-9]+|[가-힣]+")
_TRAILING_PARTICLE = re.compile(r"(으로|에서|부터|까지|을|를|의|과|와|로|에|은|는|이|가|도|만)$")


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
    weak = [row for row in sorted(summary["factors"], key=lambda row: row["mean"])
            if row["mean"] < TRANSFER_ATTENTION_MEAN]
    # One sentence for all weak conditions, so the advice is not repeated under each one. The particle
    # follows the fixed word "조건은", never a label.
    notes = [f"평균이 {TRANSFER_ATTENTION_MEAN:.1f}점 미만이라 먼저 보완할 현업 적용 조건은 "
             + ", ".join(f"{row['label']}({row['mean']:.2f}점)" for row in weak) + "입니다."] if weak else []
    top = max((row for row in summary["barriers"] if row["label"] != "특별한 방해요인 없음" and row["count"]),
              key=lambda row: row["count"], default=None)
    if top:
        notes.append(f"가장 많이 꼽힌 적용 장애요인은 '{top['label']}'({top['rate']}%)입니다.")
    if not notes:
        notes.append(f"현업 적용 조건 {len(summary['factors'])}가지의 평균이 모두 {TRANSFER_ATTENTION_MEAN:.1f}점 이상입니다. "
                     "잘된 적용 사례를 모아 조직 안에 공유하세요.")
    return notes


def course_topic_words(title: Any) -> set[str]:
    """Subject words of a title: "노션 활용법" and "Notion(노션) 활용 Part.1" share 노션, so they are one topic."""
    words = set()
    for token in _TITLE_TOKEN.findall(str(title or "").lower()):
        if len(token) >= 3 and "가" <= token[0] <= "힣":
            token = _TRAILING_PARTICLE.sub("", token)
        if len(token) >= 2 and token not in _GENERIC_TITLE_WORDS:
            words.add(token)
    return words


def _session_starts(course: Mapping[str, Any], live: Mapping[str, list[str]] | None = None) -> list[str]:
    """Known session start dates (YYYYMMDD) of a public course.

    With a live answer from the KMA site, that answer is the truth: a course it does not list has no
    sessions. Without one, the catalog's list is used, or its next_start when no list is given.
    """
    if live is not None:
        return sorted(set(live.get(str(course.get("crscd") or ""), ())))
    starts = [start for start in str(course.get("upcoming_starts") or "").split("|") if len(start) == 8]
    if not starts and len(str(course.get("next_start") or "")) == 8:
        starts = [str(course["next_start"])]
    return sorted(set(starts))


def next_feasible_start(course: Mapping[str, Any], today: date, live: Mapping[str, list[str]] | None = None) -> str | None:
    """First session a reader can still register for, or None when every known session starts too soon."""
    cutoff = (today + timedelta(days=MIN_DAYS_BEFORE_START)).strftime("%Y%m%d")
    return next((start for start in _session_starts(course, live) if start >= cutoff), None)


def course_gap_counts(config: Mapping[str, Any], factor_rows: Iterable[Mapping[str, Any]],
                      score_key: str = "post_score") -> tuple[int, int]:
    """(competencies with a score, those far enough below target to call for a course).

    Uses the same target and threshold as recommend_courses, so an empty course list can say why it is
    empty: no scores, no gap, or a gap with no course to offer.
    """
    targets = config.get("target_means") or {}
    scored = [row for row in factor_rows if row.get(score_key) is not None]
    below = [row for row in scored
             if round(float(targets.get(str(row["factor_code"]), 3.5)) - float(row[score_key]), 2) >= MEANINGFUL_DIFFERENCE]
    return len(scored), len(below)


def recommend_courses(config: Mapping[str, Any], factor_rows: Iterable[Mapping[str, Any]], limit: int = 4, *,
                      audience: str = "individual", score_key: str = "post_score",
                      max_competencies: int = 3, today: date | None = None,
                      session_starts: Mapping[str, list[str]] | None = None) -> list[dict[str, Any]]:
    """Pick courses for competencies at least 0.2 below the project target.

    factor_rows need factor_code, factor_name_ko and the score under ``score_key`` (post_score after
    training, score_1_to_5 for the pre-training report) and may carry pre_score; rows without a score
    are skipped. Larger gaps come first (gaps in the same 0.1 band tie, and the organization's priority
    competencies break the tie). Courses are filled source by source: every competency gets its best
    public course (only sessions starting at least MIN_DAYS_BEFORE_START days from today), then its best
    e-learning course, and organizations also get an in-house inquiry course. A competency without a
    course from the preferred source takes one from the next source in the first round, so the largest
    gap never drops below smaller ones. Within one competency, equally fitting courses are ordered by
    the next session, and a course on a subject the competency already has yields to a new subject.
    The same course — a second location, next year's run or another part of the same series — is never
    shown twice. Session dates come from ``session_starts`` (course code -> start dates) when given, else
    from the daily live answer of the KMA site when one is available, else from the catalog.
    """
    if TRAINING_GATE.get(str(config.get("training_cause") or "mixed_or_unknown"), 0.0) == 0.0:
        return []
    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
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
    # A course written for one level (e.g. team leaders) is never offered to another level. A public course
    # is offered with its first session the reader can still join; one whose sessions all start within the
    # next week (or are over, when the monthly catalog has aged) is not offered at all.
    live = session_starts if session_starts is not None else live_session_starts()
    catalog: dict[str, dict[str, Any]] = {}
    for row in load_courses():
        if not row.get("active", True) or row.get("target_level", "all") not in {"all", level}:
            continue
        course = dict(row)
        if str(course.get("source", "")) == "public_edu_center" and (live is not None or _session_starts(course)):
            start = next_feasible_start(course, today, live)
            if start is None:
                continue
            course["next_start"] = start
        catalog[str(course["course_id"])] = course
    queues: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    for need in needs:
        mappings = [mapping for mapping in load_course_map()
                    if mapping["factor_code"] == need["factor_code"] and str(mapping["course_id"]) in catalog]
        mappings.sort(key=lambda mapping: (-float(mapping["content_fit"]),
                                           str(catalog[str(mapping["course_id"])].get("next_start") or "99999999"),
                                           str(mapping["course_id"])))
        queues[need["factor_code"]] = [(float(mapping["content_fit"]), catalog[str(mapping["course_id"])])
                                       for mapping in mappings]

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
        candidates = []
        for fit, course in queues[need["factor_code"]]:
            course_source = str(course.get("source", ""))
            if str(course["course_id"]) in seen_ids or course_source not in allowed:
                continue
            if source is not None and course_source != source:
                continue
            if normalize_course_title(course.get("title", "")) in seen_titles:
                continue
            candidates.append((fit, course))
        if not candidates:
            return False
        # Among the best-fitting courses, a new subject beats a repeat of one this competency already has:
        # three Notion courses say less than one Notion course and one automation course.
        covered = [course_topic_words(row["title"]) for row in picked if row["factor_code"] == need["factor_code"]]
        best_fit = candidates[0][0]
        course = next((course for fit, course in candidates
                       if fit == best_fit and not any(course_topic_words(course.get("title", "")) & words for words in covered)),
                      candidates[0][1])
        seen_ids.add(str(course["course_id"]))
        seen_titles.add(normalize_course_title(course.get("title", "")))
        reason = _course_reason(need)
        if covered:
            reason["advice"] = ""  # say what the change suggests once per competency, not under every course
        picked.append({**course, "factor_code": need["factor_code"], "factor_name_ko": need["factor_name_ko"],
                       "delivery_label": DELIVERY_LABELS.get(str(course.get("delivery")), "온라인·집합"),
                       "schedule": course_schedule_text(course),
                       # The numbers behind `reason`, for the gap bar on the cards.
                       "score": need["score"], "target": need["target"], "gap": need["gap"], "change": need["change"],
                       **reason})
        return True

    # Source by source so every competency gets its public course before any gets an e-learning one. In the
    # first round a competency without a course from that source (sales has no e-learning) takes one from
    # another source, so it keeps its place in the gap order.
    for round_index, (source, count) in enumerate(slots):
        for need in needs:
            for _ in range(count):
                if len(picked) >= limit or not (take(need, source) or (round_index == 0 and take(need, None))):
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
        return "사내교육 · KMA에 단체교육 문의"
    return DELIVERY_LABELS.get(str(course.get("delivery")), "")


def _course_reason(need: Mapping[str, Any]) -> dict[str, Any]:
    """The numbers behind a pick, and what the pre/post change suggests doing with it."""
    phase_label = "교육 후" if need.get("phase") == "post" else "교육 전"
    reason = f"{phase_label} {need['score']:.2f}점, 목표 {need['target']:.2f}점보다 {need['gap']:.2f}점 낮음"
    change = need["change"]
    if change is None:
        return {"reason": reason, "advice": ""}
    # Words instead of a signed number, so a zero change never reads "교육 전보다 +0.00점".
    reason += (" · 교육 전과 같음" if change == 0
               else f" · 교육 전보다 {abs(change):.2f}점 {'높음' if change > 0 else '낮음'}")
    if change >= MEANINGFUL_DIFFERENCE:
        advice = "교육 전보다 점수가 올랐습니다. 같은 주제의 심화 과정이나 현업 적용 과제로 이어가세요."
    elif change <= -MEANINGFUL_DIFFERENCE:
        advice = "교육 전보다 점수가 낮아졌습니다. 새 과정을 듣기 전에 업무가 바뀌었거나 적용 기회가 줄었는지 살펴보세요."
    else:
        advice = "교육 전과 큰 차이가 없습니다. 지난 교육 내용이 업무에 맞았는지, 적용할 여건이 있었는지 함께 점검하세요."
    return {"reason": reason, "advice": advice}


def course_context_note(transfer: Mapping[str, Any] | None) -> str | None:
    """Put weak transfer conditions ahead of the course list: more training rarely fixes the work environment."""
    if not transfer or not transfer.get("disclosed"):
        return None
    weak = [row["label"] for row in transfer["factors"] if row["mean"] < TRANSFER_ATTENTION_MEAN]
    if not weak:
        return None
    # The transfer section above already gives the means; this line only ties them to the course list.
    return f"현업 적용 조건 중 평균이 낮은 {', '.join(weak)}부터 보완해야 과정에서 배운 내용이 현업에서 쓰입니다."


def organization_detail_rows(summaries: Iterable[Mapping[str, Any]], config: Mapping[str, Any],
                             transfer: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One flat table for the detail CSV: competencies, transfer climate and barriers.

    Scores of undisclosed competencies are already None in the summaries; only counts remain.
    """
    targets = config.get("target_means") or {}
    rows = [{"구분": "역량", "항목": row["factor_name_ko"], "교육 전 응답": row["pre_n"], "교육 후 응답": row["post_n"],
             "교육 전후 유효 인원": row["paired_n"], "교육 후 미응답": row["attrition_n"],
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
