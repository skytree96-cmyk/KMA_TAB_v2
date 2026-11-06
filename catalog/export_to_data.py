"""v3 카탈로그/매핑(작업 폴더) -> 앱 데이터 data/courses.csv, data/competency_course_map.csv."""
from __future__ import annotations

import collections
import io
from pathlib import Path
import urllib.parse

from catalog.common import DATA, read_csv, today_kst, write_csv

RATIONALE = {
    "category+title": "공개교육센터 카테고리·과정명 기반 연계",
    "b2b_title+tag": "교육문의형 과정명·태그 기반 연계(조직 리포트 전용)",
    "lxp_subcategory+title": "이러닝 분류·과정명 기반 연계",
    "studio_title": "stud.io 콘텐츠명 기반 연계(보조)",
}
COLS = ["course_id", "title", "source", "delivery", "target_level", "url", "thumb_url", "category", "crscd",
        "next_start", "next_end", "next_crsseq_id", "schedule_count", "edu_day", "edu_time", "place",
        "has_upcoming", "active", "catalog_version", "upcoming_starts"]


def build_rows(src_dir: Path | str = ".") -> tuple[list[dict], list[dict]]:
    today = today_kst()
    stamp = today.strftime("%Y%m%d")
    version = today.strftime("KMA-LIVE-%Y%m")
    src = Path(src_dir)
    cat = read_csv(src / "kma_course_catalog_v3.csv")
    mp = read_csv(src / "kma_competency_course_map_v3.csv")
    # 공개교육 기수 전체. 앱은 이 목록에서 리포트를 읽는 날 기준으로 신청할 수 있는 다음 기수를 고른다.
    starts = collections.defaultdict(set)
    for s in read_csv(src / "kma_offline_schedule_live.csv"):
        if len(s["edu_strtdt"]) == 8 and s["edu_strtdt"] >= stamp:
            starts[s["crscd"]].add(s["edu_strtdt"])
    # 이러닝 썸네일: stud.io 목록의 thmbSeq -> 이미지 최적화 주소로 축소본 사용
    studio_thumbs = {s["eduSeq"]: s["thmbSeq"] for s in read_csv(src / "studio_elearning_live.csv")
                     if s.get("thmbSeq", "").isdigit()}
    courses = []
    for c in sorted(cat, key=lambda c: c["course_id"]):
        row = {k: c.get(k, "") for k in COLS}
        if c["source"] == "public_edu_center":
            upcoming = sorted(starts.get(c["crscd"], ()))
            row["upcoming_starts"] = "|".join(upcoming)
            row["has_upcoming"] = "True" if upcoming else "False"   # 수집일이 아니라 내보내는 날 기준
        else:
            row["upcoming_starts"] = ""
            row["has_upcoming"] = "True" if c["has_upcoming"] == "True" else "False"
        if c["source"] == "studio_elearning" and not row["thumb_url"]:
            seq = studio_thumbs.get(c["url"].rstrip("/").rsplit("/", 1)[-1])
            if seq:
                row["thumb_url"] = ("https://studio.kma.or.kr/_next/image?url="
                                    + urllib.parse.quote(f"https://studio.kma.or.kr/papi/storage/imgDownload/{seq}", safe="")
                                    + "&w=384&q=75")
        row["active"] = row["has_upcoming"]
        row["catalog_version"] = version
        courses.append(row)
    mapping = [{"factor_code": m["factor_code"], "course_id": m["course_id"], "content_fit": m["content_fit"],
                "rationale": RATIONALE.get(m["basis"], m["basis"])}
               for m in sorted(mp, key=lambda m: (m["factor_code"], -float(m["content_fit"]), m["course_id"]))]
    return courses, mapping


def write_data(courses: list[dict], mapping: list[dict], dst_dir: Path | str = DATA) -> None:
    dst = Path(dst_dir)
    write_csv(dst / "courses.csv", COLS, courses)
    write_csv(dst / "competency_course_map.csv", ["factor_code", "course_id", "content_fit", "rationale"], mapping)
