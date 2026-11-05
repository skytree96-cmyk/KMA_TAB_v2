"""Live session dates of KMA public courses, refreshed in the background once a day.

The catalog (data/courses.csv) is rebuilt by hand, so its session lists age. The course
links do not: they carry the course code and no session id. What ages is the "다음 개강"
date and the rule that only courses with a session at least a week away are offered.
This module asks the KMA public education site for every category the catalog uses and
keeps the answer in memory.

It is off unless TAP_LIVE_SCHEDULE=1, never makes a report wait, and hands back None
(use the catalog) until a refresh has fully succeeded.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import http.cookiejar
import json
import logging
import os
import threading
import time
from typing import Any, Iterable, Mapping
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)
ENV_FLAG = "TAP_LIVE_SCHEDULE"
FORM_URL = "https://www.kma.or.kr/usrs/eduRegMgnt/eduRegMgntForm.do?p_ctgry_id={category}&mkey={menu}"
LIST_URL = "https://www.kma.or.kr/usrs/eduRegMgnt/eduRegRowDataList.do"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
REFRESH_SECONDS = 24 * 3600      # a successful answer is reused for a day
RETRY_SECONDS = 3600             # after a failed refresh, wait an hour before the next try
MAX_AGE_SECONDS = 3 * 24 * 3600  # older than this, the answer is dropped and the catalog is used again
# The catalog lists several hundred public courses. An answer covering far fewer means the site changed.
MIN_COVERAGE = 0.3

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"starts": None, "fetched_at": 0.0, "tried_at": 0.0, "running": False}


def catalog_categories(courses: Iterable[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """(category id, menu id) pairs of the public courses, read from their evergreen links."""
    pairs = set()
    for course in courses:
        if str(course.get("source", "")) != "public_edu_center":
            continue
        query = urllib.parse.parse_qs(urllib.parse.urlparse(str(course.get("url", ""))).query)
        category, menu = query.get("p_ctgry_id", [""])[0], query.get("mkey", [""])[0]
        if category.isdigit() and menu.isdigit():
            pairs.add((category, menu))
    return sorted(pairs)


def parse_sessions(rows: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    """Session start dates (YYYYMMDD) per course code from one list answer.

    Each row carries EDU_MONTH_1..12 as "name@session id@YYYY.MM.DD~YYYY.MM.DD|…" and may name one
    linked session with its start date.
    """
    starts: dict[str, set[str]] = {}
    for row in rows:
        code = str(row.get("CRSCD") or "")
        if not code:
            continue
        for month in range(1, 13):
            for part in str(row.get(f"EDU_MONTH_{month}") or "").split("|"):
                bits = part.split("@")
                if len(bits) >= 3 and bits[1].isdigit():
                    start = bits[2].split("~")[0].replace(".", "").strip()
                    if len(start) == 8 and start.isdigit():
                        starts.setdefault(code, set()).add(start)
        linked = str(row.get("EDU_STRTDT") or "")
        if row.get("LINK_CRSSEQ_ID") and len(linked) == 8 and linked.isdigit():
            starts.setdefault(code, set()).add(linked)
    return starts


def _list_request(category: str, menu: str, year: int) -> urllib.request.Request:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    params = dict(page=0, rows=0, sidx="EDU_STRTDT", sord="ASC", p_srch_crs_ctgry_id=category, p_hmpgcd=30,
                  subMenuNm="", p_usrid="", totalCnt="", moreCnt="", p_srch_year_month="", p_srch_year=year,
                  curr_month=now.month, curr_year=now.year, currListType="R", crsCtgryType="", g_mod="N",
                  p_month_idx="", p_month_ord="", p_cmn_jobposcd="", p_srch_area="", p_srch_text="",
                  p_srch_calendar_text="", mkey=menu)
    return urllib.request.Request(LIST_URL + "?" + urllib.parse.urlencode(params), headers={
        "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": FORM_URL.format(category=category, menu=menu)})


def fetch_session_starts(categories: Iterable[tuple[str, str]], years: Iterable[int], *,
                         timeout: float = 20, workers: int = 6) -> dict[str, list[str]]:
    """Ask the site for every category and year. Any failed call fails the whole fetch: a course that is
    missing from a partial answer would wrongly read as "no sessions"."""
    categories, years = list(categories), list(years)
    if not categories:
        raise ValueError("no categories to fetch")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    opener.addheaders = [("User-Agent", USER_AGENT)]
    # The list endpoint answers only inside a browsing session, so open one page first for the cookie.
    opener.open(FORM_URL.format(category=categories[0][0], menu=categories[0][1]), timeout=timeout).read()

    def call(job: tuple[str, str, int]) -> list[Mapping[str, Any]]:
        category, menu, year = job
        with opener.open(_list_request(category, menu, year), timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        rows = payload.get("dataList")
        if not isinstance(rows, list):
            raise ValueError("unexpected list answer")
        return rows

    merged: dict[str, set[str]] = {}
    jobs = [(category, menu, year) for category, menu in categories for year in years]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rows in pool.map(call, jobs):
            for code, starts in parse_sessions(rows).items():
                merged.setdefault(code, set()).update(starts)
    return {code: sorted(starts) for code, starts in merged.items()}


def _refresh() -> None:
    try:
        from tap.data import load_courses
        courses = [course for course in load_courses() if str(course.get("source", "")) == "public_edu_center"]
        year = datetime.now(ZoneInfo("Asia/Seoul")).year
        starts = fetch_session_starts(catalog_categories(courses), (year, year + 1))
        known = {str(course.get("crscd", "")) for course in courses}
        if len(known & starts.keys()) < MIN_COVERAGE * max(1, len(known)):
            raise ValueError("live schedule covers too few catalog courses")
        with _LOCK:
            _STATE.update(starts=starts, fetched_at=time.time())
        LOGGER.info("Course schedule refreshed: %d courses", len(starts))
    except Exception as exc:  # network, site change, parsing: keep the catalog and try again later
        LOGGER.warning("Course schedule refresh failed: %s", type(exc).__name__)
    finally:
        with _LOCK:
            _STATE["running"] = False


def live_session_starts() -> Mapping[str, list[str]] | None:
    """Current session starts per course code, or None when the catalog should be used.

    A stale or missing answer starts one background refresh; the caller never waits for it.
    """
    if os.environ.get(ENV_FLAG, "").strip() != "1":
        return None
    now = time.time()
    with _LOCK:
        fresh = _STATE["starts"] is not None and now - _STATE["fetched_at"] < REFRESH_SECONDS
        if not fresh and not _STATE["running"] and now - _STATE["tried_at"] >= RETRY_SECONDS:
            _STATE.update(running=True, tried_at=now)
            threading.Thread(target=_refresh, name="tap-course-schedule", daemon=True).start()
        if _STATE["starts"] is not None and now - _STATE["fetched_at"] < MAX_AGE_SECONDS:
            return _STATE["starts"]
        return None


def schedule_basis() -> str:
    """One sentence for the screen: where the session dates shown right now come from."""
    fetched = 0.0
    if os.environ.get(ENV_FLAG, "").strip() == "1":
        with _LOCK:
            if _STATE["starts"] is not None and time.time() - _STATE["fetched_at"] < MAX_AGE_SECONDS:
                fetched = _STATE["fetched_at"]
    if fetched:
        moment = datetime.fromtimestamp(fetched, ZoneInfo("Asia/Seoul"))
        return f"개강일은 {moment.month}월 {moment.day}일 {moment:%H:%M}에 KMA 사이트에서 조회한 일정 기준입니다."
    return "개강일은 과정 카탈로그에 담긴 일정 기준입니다."


def reset_for_tests() -> None:
    with _LOCK:
        _STATE.update(starts=None, fetched_at=0.0, tried_at=0.0, running=False)
