"""Rebuild the course catalog from the live KMA sites and write data/.

    python -m catalog.run_weekly            # crawl, build, check, write data/
    python -m catalog.run_weekly --dry-run  # same, but leave data/ untouched

Crawl results go to a scratch folder (CATALOG_WORK, default .tmp/catalog_work). The new catalog is written
only when it is not much smaller than the current one: a sudden drop means a crawl went wrong, not that KMA
closed a third of its courses, and the current data is kept instead (exit code 2).
A short Markdown summary is printed and, inside GitHub Actions, added to the run page.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import os
from pathlib import Path
import runpy
import sys

from catalog import crawl_kma, crawl_kma_thumbs, crawl_studio, match_lxp
from catalog.common import DATA, PACKAGE, read_csv, work_dir
from catalog.export_to_data import build_rows, write_data

# A source may shrink this far in one run before the run is refused (new / current).
MIN_SOURCE_RATIO = 0.7
MIN_MAPPING_RATIO = 0.8
LIST_LIMIT = 15


@contextlib.contextmanager
def _inside(path: Path):
    before = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(before)


def crawl_and_build(work: Path) -> None:
    with _inside(work):
        crawl_kma.main()
        crawl_kma_thumbs.main()
        crawl_studio.main()
        match_lxp.main()
        runpy.run_path(str(PACKAGE / "build_catalog.py"), run_name="__main__")


def shrink_problems(old: list[dict], new: list[dict], old_map: list[dict], new_map: list[dict]) -> list[str]:
    problems = []
    old_by, new_by = collections.Counter(c["source"] for c in old), collections.Counter(c["source"] for c in new)
    for source, before in old_by.items():
        if before >= 20 and new_by[source] < MIN_SOURCE_RATIO * before:
            problems.append(f"{source}: {before} -> {new_by[source]}")
    if old_map and len(new_map) < MIN_MAPPING_RATIO * len(old_map):
        problems.append(f"mappings: {len(old_map)} -> {len(new_map)}")
    return problems


def summary(old: list[dict], new: list[dict], old_map: list[dict], new_map: list[dict], problems: list[str]) -> str:
    old_by, new_by = collections.Counter(c["source"] for c in old), collections.Counter(c["source"] for c in new)
    old_ids, new_ids = {c["course_id"]: c for c in old}, {c["course_id"]: c for c in new}
    added = [new_ids[i] for i in sorted(new_ids.keys() - old_ids.keys())]
    removed = [old_ids[i] for i in sorted(old_ids.keys() - new_ids.keys())]
    offered = sum(1 for c in new if c["source"] == "public_edu_center" and c["upcoming_starts"])
    out = io.StringIO()
    out.write("## 교육과정 카탈로그 주간 갱신\n\n")
    out.write("| 구분 | 이전 | 이번 |\n|---|---:|---:|\n")
    for source in sorted(old_by.keys() | new_by.keys()):
        out.write(f"| {source} | {old_by[source]} | {new_by[source]} |\n")
    out.write(f"| 역량-과정 연결 | {len(old_map)} | {len(new_map)} |\n\n")
    out.write(f"남은 기수가 있는 공개교육 {offered}개 · 새 과정 {len(added)}개 · 빠진 과정 {len(removed)}개\n")
    for label, rows in (("새 과정", added), ("빠진 과정", removed)):
        if rows:
            out.write(f"\n**{label}**\n")
            for c in rows[:LIST_LIMIT]:
                out.write(f"- {c['title']} ({c['source']})\n")
            if len(rows) > LIST_LIMIT:
                out.write(f"- 외 {len(rows) - LIST_LIMIT}개\n")
    if problems:
        out.write("\n**갱신 보류**: 과정 수가 크게 줄어 이번 결과를 쓰지 않았습니다. " + "; ".join(problems) + "\n")
    return out.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="crawl and check, but do not write data/")
    parser.add_argument("--skip-crawl", action="store_true", help="reuse the crawl results already in the work folder")
    args = parser.parse_args(argv)
    work = work_dir()
    if not args.skip_crawl:
        crawl_and_build(work)
    new, new_map = build_rows(work)
    old, old_map = read_csv(DATA / "courses.csv"), read_csv(DATA / "competency_course_map.csv")
    problems = shrink_problems(old, new, old_map, new_map)
    text = summary(old, new, old_map, new_map, problems)
    print(text)
    (work / "summary.md").write_text(text, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with io.open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)
    if problems:
        return 2
    if not args.dry_run:
        write_data(new, new_map)
    return 0


if __name__ == "__main__":
    sys.exit(main())
