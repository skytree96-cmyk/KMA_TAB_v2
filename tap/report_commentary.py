"""Organization report commentary written by Claude from disclosed aggregates only.

Only numbers the report already shows go out: competencies, departments and the transfer climate
with 5 or more people, and the recommended course titles. No names, personal scores or free text.
A commentary is made when the manager asks for it, stored, and shown to everyone who opens the
report. Any failure leaves the report as it is today.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from tap.ai_budget import FEATURES, KST, MONTHLY_APP_LIMIT_USD, max_call_micros, to_micros
from tap.ai_client import ai_ready, generate
from tap.config import MIN_GROUP_N

FEATURE = "report_commentary"
# Changing the prompt changes every cache key, so old commentaries are offered for rewriting.
PROMPT_VERSION = "2026-11-23"
PROJECT_MONTHLY_LIMIT = 10
SOURCE_LABELS = {"public_edu_center": "공개교육", "studio_elearning": "이러닝", "b2b_inquiry": "단체교육 문의",
                 "studio_original": "stud.io"}

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "findings": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
            "required": ["title", "body"], "additionalProperties": False}},
        "actions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "findings", "actions"],
    "additionalProperties": False,
}

SYSTEM = """너는 KMA(한국능률협회) TAP 서비스의 조직 리포트 해설을 쓴다. 독자는 회원사 교육담당자다.

입력은 한 프로젝트의 집계 수치뿐이다(5명 이상 묶음만). 개인 정보는 없다.

지킬 것:
- 입력에 있는 숫자와 이름만 쓴다. 없는 숫자를 만들거나 계산하거나 반올림을 바꾸지 않는다. 숫자는 입력에 적힌 그대로 쓴다.
- 자기보고 점수의 교육 전후 변화다. "교육 효과로", "교육 덕분에"처럼 원인을 단정하지 않는다. "올랐다", "변화가 컸다"처럼 관찰로 쓴다.
- 변화 0.2점 미만은 "유지"로 본다. 목표와의 차이 0.2점 미만도 목표 수준으로 본다.
- 부서는 입력에 있는 부서만 말한다. 특정 부서를 탓하거나 순위를 매기지 않는다.
- 추천 과정은 입력에 있는 과정명만 그대로 쓴다.
- 문장은 짧게, "~입니다/~습니다"체로 쓴다. 한 문장에 한 가지 내용만 쓴다. actions만 "~하세요"로 끝낸다.

해설의 역할:
- 역량별 점수와 변화는 리포트 차트에 이미 있다. 숫자를 하나씩 다시 읽어 주지 않는다. 한 문장에 숫자는 두 개까지만 쓴다.
- 차트만 봐서는 알기 어려운 연결을 짚는다. 예: 변화는 컸지만 목표와 아직 거리가 있는 역량, 점수는 올랐지만 현업전이 여건이 낮아 적용이 막힐 수 있는 지점, 부서 사이 변화 차이가 0.2점 이상 나는 역량.
- findings 3개는 서로 다른 관점이어야 한다(예: 변화와 목표, 부서 차이, 현업 적용 여건). 입력에 부서나 현업전이 자료가 없으면 다른 관점으로 바꾼다.
- headline은 담당자가 이것 하나만 읽어도 다음에 할 일을 알 수 있게 쓴다.

문구 규칙(TAP 문구 검수 기준):
- 같은 내용을 두 번 쓰지 않는다. headline에 쓴 말을 findings에서 되풀이하지 않는다.
- 가운뎃점(·)은 명사 조각끼리만 잇고, 명사를 넷 이상 잇지 않는다. 콜론 라벨("모수:")을 쓰지 않는다.
- 번역투를 쓰지 않는다: "~되어 있습니다", "~하고 있습니다", "짝지은", "스냅샷", "휴리스틱", "인사이트", "시사점".
- "A가 아니라 B" 같은 수사 틀, 과장("너머", "한눈에", "지금 바로", "획기적"), 근거 없는 단정("~해야 현업에서 쓰입니다")을 쓰지 않는다.
- "큰 향상"이 아니라 "크게 향상", "확인하세요" 대신 할 일을 구체적으로 쓴다.

분량:
- headline: 40자 안팎 한 문장.
- findings: 3개. 각각 title(15자 안팎 명사구)과 body(2~3문장).
- actions: 2~3개. 담당자가 다음 달에 할 수 있는 일. 각각 한 문장.
"""

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _two(value: Any) -> str:
    return f"{float(value):.2f}"


def _signed(value: Any) -> str:
    return f"{float(value):+.2f}"


def _start_text(start: Any) -> str:
    start = str(start or "")
    if len(start) != 8 or not start.isdigit():
        return ""
    return f" ({int(start[4:6])}월 {int(start[6:])}일 개강)"


def build_payload(project: Mapping[str, Any], summaries: Iterable[Mapping[str, Any]], paired: int,
                  team_grid: Mapping[str, Any] | None, transfer: Mapping[str, Any] | None,
                  courses: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The aggregate input, or None when no competency is disclosed. Numbers are pre-formatted strings
    so the commentary can be checked against them character for character."""
    config = project.get("config") or {}
    targets = config.get("target_means") or {}
    factors = []
    for row in summaries:
        if int(row.get("paired_n") or 0) < MIN_GROUP_N or row.get("pre_mean") is None or row.get("post_mean") is None:
            continue
        target = float(targets.get(str(row["factor_code"]), 3.5))
        post = float(row["post_mean"])
        factors.append({"역량": str(row["factor_name_ko"]), "교육 전": _two(row["pre_mean"]), "교육 후": _two(post),
                        "변화": _signed(round(post - float(row["pre_mean"]), 2)), "목표": _two(target),
                        "목표 대비": _signed(round(post - target, 2)), "전후 유효 인원": int(row["paired_n"])})
    if not factors:
        return None
    payload: dict[str, Any] = {"프로젝트": str(project.get("name") or project.get("project_name") or ""),
                               "교육 전후 모두 완료": int(paired), "역량별 결과": factors}

    if team_grid:
        names = {factor["factor_code"]: factor["factor_name_ko"] for factor in team_grid.get("factors", [])}
        teams = []
        for row in team_grid.get("rows", []):
            changes = {names[cell["factor_code"]]: _signed(cell["change"]) for cell in row["cells"]
                       if cell.get("shown") and cell.get("change") is not None}
            if changes:
                teams.append({"부서": row["team"], "인원": int(row["paired_n"]), "변화": changes})
        if len(teams) >= 2:
            payload["부서별 교육 전후 변화(5명 이상만)"] = teams

    if transfer and transfer.get("disclosed"):
        payload["현업전이 환경(1~5)"] = {
            "응답": int(transfer["n"]),
            "평균": {row["label"]: _two(row["mean"]) for row in transfer["factors"]},
            "적용 장애요인(복수 선택)": {row["label"]: f"{row['rate']}%" for row in transfer["barriers"]},
        }

    grouped: dict[str, list[str]] = {}
    for course in courses:
        label = SOURCE_LABELS.get(str(course.get("source", "")), str(course.get("delivery_label") or "과정"))
        start = _start_text(course.get("next_start")) if course.get("source") == "public_edu_center" else ""
        grouped.setdefault(str(course.get("factor_name_ko") or ""), []).append(f"[{label}] {course.get('title', '')}{start}")
    if grouped:
        payload["검토 과정(목표보다 0.2점 이상 낮은 역량)"] = [{"역량": name, "과정": titles} for name, titles in grouped.items()]
    return payload


def cache_key(project_id: str, payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256((PROMPT_VERSION + json.dumps(payload, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()
    return f"{project_id}:{digest[:32]}"


def valid_commentary(result: Any, payload: Mapping[str, Any]) -> bool:
    """Shape check plus: every number in the commentary appears in the input (small counts aside)."""
    if not isinstance(result, Mapping):
        return False
    headline, findings, actions = result.get("headline"), result.get("findings"), result.get("actions")
    if not isinstance(headline, str) or not 0 < len(headline.strip()) <= 120:
        return False
    if not isinstance(findings, list) or not 2 <= len(findings) <= 4:
        return False
    if any(not isinstance(item, Mapping) or not str(item.get("title") or "").strip() or not str(item.get("body") or "").strip()
           for item in findings):
        return False
    if not isinstance(actions, list) or not 1 <= len(actions) <= 4 or any(not str(item or "").strip() for item in actions):
        return False
    known = set(_NUMBER.findall(json.dumps(payload, ensure_ascii=False)))
    text = " ".join([headline, *(f"{item['title']} {item['body']}" for item in findings), *map(str, actions)])
    return all(number in known or (number.isdigit() and int(number) <= 10) for number in _NUMBER.findall(text))


def _decode(text: str | None) -> dict[str, Any] | None:
    try:
        stored = json.loads(text) if text else None
    except ValueError:
        return None
    return stored if isinstance(stored, dict) and "result" in stored else None


def stored_commentary(store: Any, project_id: str, payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The commentary made for exactly these numbers, for the PDF. Never calls the API; any failure is None."""
    if not payload:
        return None
    try:
        stored = _decode(store.ai_cached(FEATURE, cache_key(project_id, payload)))
    except Exception:
        return None
    return stored if stored and valid_commentary(stored["result"], payload) else None


def commentary_state(store: Any, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """What the report shows: the commentary for these numbers, an older one, and whether one can be made."""
    try:
        current = _decode(store.ai_cached(FEATURE, cache_key(project_id, payload)))
        older = None if current else _decode((store.ai_latest_result(FEATURE, f"{project_id}:") or {}).get("text"))
        used = store.ai_project_month_count(FEATURE, project_id)
        feature = FEATURES[FEATURE]
        month = store.ai_month_usage()
        budget_left = (month.get(FEATURE, 0) + max_call_micros(feature) <= to_micros(feature.monthly_usd)
                       and sum(month.values()) + max_call_micros(feature) <= to_micros(MONTHLY_APP_LIMIT_USD))
        remaining = max(0, PROJECT_MONTHLY_LIMIT - used)
        can_make = remaining > 0 and budget_left and ai_ready(store)
    except Exception:
        return {"current": None, "older": None, "remaining": 0, "can_make": False}
    return {"current": current, "older": older, "remaining": remaining, "can_make": can_make}


def make_commentary(store: Any, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ask Claude once; keep the answer only when it passes valid_commentary."""
    try:
        if store.ai_project_month_count(FEATURE, project_id) >= PROJECT_MONTHLY_LIMIT:
            return None
    except Exception:
        return None
    prompt = "다음 집계로 해설을 써라.\n\n" + json.dumps(payload, ensure_ascii=False, indent=1)
    answer = generate(store, FEATURE, system=SYSTEM, prompt=prompt, project_id=project_id, output_schema=SCHEMA)
    if answer is None:
        return None
    try:
        result = json.loads(answer.text)
    except ValueError:
        return None
    if not valid_commentary(result, payload):
        return None
    stored = {"result": result, "created_at": datetime.fromtimestamp(store.now(), KST).strftime("%Y-%m-%d %H:%M")}
    try:
        store.ai_store_result(FEATURE, cache_key(project_id, payload), json.dumps(stored, ensure_ascii=False))
    except Exception:
        pass
    return stored
