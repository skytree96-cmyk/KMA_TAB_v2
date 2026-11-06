"""LXP 이러닝 과정명(catalog/inputs/lxp_courses.csv) <-> stud.io 라이브 eduSeq 제목 매칭. 출력: lxp_to_studio_match.csv"""
import collections
import difflib
import io
import re

from catalog.common import INPUTS, read_csv, write_csv

EXCLUDED = ("자격증", "어학", "법정교육", "인문교양")


def norm(t):
    t = str(t or "").lower()
    t = re.sub(r"\(\s*20\d\d\s*\)", "", t)          # (2026) 연도 꼬리
    t = re.sub(r"[\s　]+", "", t)
    t = re.sub(r"[\[\]\(\)\{\}·ㆍ∙•:：\-_–—~,.!?'\"“”‘’/&+※|]", "", t)
    return t


def main() -> None:
    lxp = read_csv(INPUTS / "lxp_courses.csv")
    live = read_csv("studio_elearning_live.csv")
    live_by_norm = {}
    for r in live:
        live_by_norm.setdefault(norm(r["crsNm"]), []).append(r)
    live_norms = list(live_by_norm)

    out_rows = []
    stats = collections.Counter()
    for r in lxp:
        name = r["과정명"]
        n = norm(name)
        hit = live_by_norm.get(n)
        how = "exact" if hit else ""
        if not hit:
            # 연도 꼬리 제거 후 라이브 제목이 엑셀 제목을 포함/포함되는 경우
            cands = [k for k in live_norms if n and (n in k or k in n) and min(len(n), len(k)) >= 8]
            if len(cands) == 1:
                hit, how = live_by_norm[cands[0]], "contains"
            else:
                close = difflib.get_close_matches(n, live_norms, n=1, cutoff=0.92)
                if close:
                    hit, how = live_by_norm[close[0]], "fuzzy92"
        stats[how or "none"] += 1
        best = hit[0] if hit else {}
        out_rows.append({
            "lxp_title": name, "대분류": r["대분류"], "중분류": r["중분류"], "소분류": r["소분류"], "개발년도": r["개발년도"],
            "match": how or "none", "eduSeq": best.get("eduSeq", ""), "live_title": best.get("crsNm", ""),
            "url": best.get("url", ""), "thmbSeq": best.get("thmbSeq", ""),
        })
    write_csv("lxp_to_studio_match.csv", list(out_rows[0].keys()), out_rows)
    target = [o for o in out_rows if o["대분류"] not in EXCLUDED]
    tstats = collections.Counter(o["match"] for o in target)
    with io.open("match_lxp_summary.txt", "w", encoding="utf-8") as rep:
        rep.write(f"LXP {len(lxp)} / stud.io 라이브 이러닝 {len(live)}\n전체 매칭: {dict(stats)}\n추천대상({len(target)}) 매칭: {dict(tstats)}\n")
    print(f"match_lxp: target={len(target)} {dict(tstats)}")


if __name__ == "__main__":
    main()
