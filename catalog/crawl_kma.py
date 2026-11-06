"""공개교육센터 라이브 수집: 카테고리별 과정·기수·교육비·썸네일.

입력: catalog/inputs/kma_categories.csv (카테고리 ID·메뉴 ID·카테고리명)
출력(작업 폴더): kma_offline_live.csv, kma_offline_schedule_live.csv, crawl_kma_log.txt
기수 목록 호출이 재시도 뒤에도 하나라도 실패하면 멈춘다. 일부 카테고리가 빠진 목록을 내보내면 그 과정들이 추천에서 사라지기 때문이다.
"""
import collections
import html
import io
import re
import time

from catalog.common import INPUTS, read_csv, session, today_kst, with_retry, write_csv

ROW = "https://www.kma.or.kr/usrs/eduRegMgnt/eduRegRowDataList.do"
MON = "https://www.kma.or.kr/usrs/eduRegMgnt/eduRegMgntMonthList.do"
FORM = "https://www.kma.or.kr/usrs/eduRegMgnt/eduRegMgntForm.do?p_ctgry_id={ctg}&mkey={mk}"


def main() -> None:
    today = today_kst()
    years = [today.year, today.year + 1]
    cats = {(int(r["CRS_CTGRY_ID"]), int(r["MENU_ID"])): r["TREE_CTGRY_NM"] for r in read_csv(INPUTS / "kma_categories.csv")}
    s = session()
    first = next(iter(sorted(cats)))
    s.get(FORM.format(ctg=first[0], mk=first[1]), timeout=30)   # 목록 API는 세션 쿠키가 있어야 답한다
    log = io.open("crawl_kma_log.txt", "w", encoding="utf-8")
    courses = {}   # crscd -> dict
    seqs = []      # (crscd, crsseq_id, start, end)
    thumbs = {}
    for (ctg, mk), cat_nm in sorted(cats.items()):
        ref = FORM.format(ctg=ctg, mk=mk)
        hdr = {"X-Requested-With": "XMLHttpRequest", "Referer": ref, "Accept": "application/json, text/javascript, */*; q=0.01"}
        n_rows = 0
        for yr in years:
            params = dict(page=0, rows=0, sidx="EDU_STRTDT", sord="ASC", p_srch_crs_ctgry_id=ctg, p_hmpgcd=30,
                          subMenuNm="", p_usrid="", totalCnt="", moreCnt="", p_srch_year_month="", p_srch_year=yr,
                          curr_month=today.month, curr_year=today.year, currListType="R", crsCtgryType="", g_mod="N",
                          p_month_idx="", p_month_ord="", p_cmn_jobposcd="", p_srch_area="", p_srch_text="",
                          p_srch_calendar_text="", mkey=mk)

            def fetch():
                r = s.get(ROW, params=params, headers=hdr, timeout=30)
                r.raise_for_status()
                rows = r.json().get("dataList")
                if not isinstance(rows, list):
                    raise ValueError("unexpected list answer")
                return rows

            try:
                data = with_retry(fetch)
            except Exception as e:
                log.write(f"[{ctg}/{mk}] {cat_nm} year {yr} ERROR {e!r}\n")
                log.close()
                raise SystemExit(f"KMA list call failed: category {ctg} year {yr}: {e!r}")
            n_rows += len(data)
            for d in data:
                crscd = str(d["CRSCD"])
                courses.setdefault(crscd, {
                    "crscd": crscd, "crs_nm": html.unescape(d["CRS_NM"]), "category": cat_nm, "crs_ctgry_id": ctg,
                    "menu_id": mk, "edutype_cd": d.get("EDUTYPE_CD"), "edu_day": d.get("EDUDAY"),
                    "edu_time": d.get("EDUTIME"), "place": d.get("TRAININST_NM"), "fee_member": d.get("EDUCST_MBRCOMP"),
                    "fee_nonmember": d.get("EDUCST_NMBRCOMP"), "crsreg_type_cd": d.get("CRSREG_TYPE_CD"),
                })
                for m in range(1, 13):
                    for part in (d.get(f"EDU_MONTH_{m}") or "").split("|"):
                        bits = part.split("@")
                        if len(bits) >= 3 and bits[1].isdigit():
                            seqs.append((crscd, bits[1], bits[2].split("~")[0].replace(".", ""),
                                         bits[2].split("~")[-1].replace(".", "")))
                if d.get("LINK_CRSSEQ_ID"):
                    seqs.append((crscd, str(d["LINK_CRSSEQ_ID"]), str(d.get("EDU_STRTDT") or ""), str(d.get("EDU_ENDDT") or "")))
        # 썸네일: 렌더링 HTML 목록. 실패해도 상세 페이지 확인 단계(og:image)가 보강한다.
        try:
            params = dict(page=1, rows=500, sidx="CRSREG_YN DESC, EDU_JOIN_YN DESC, CRSREG_ENDDT ASC, CRSSEQ_NM", sord="DESC",
                          p_srch_crs_ctgry_id=ctg, p_hmpgcd=30, g_mod="N", mkey=mk)
            h = s.get(MON, params=params, headers=hdr, timeout=30).text
            for cc, fn in re.findall(r'/upload/crs/(\d+)/([^"\'\s)]+)', h):
                thumbs.setdefault(cc, fn)
            n_th = len(re.findall(r'/upload/crs/\d+/', h))
        except Exception as e:
            n_th = f"ERR {e!r}"
        log.write(f"[{ctg}/{mk}] {cat_nm}: rows={n_rows} thumbs={n_th}\n")
        time.sleep(0.2)

    seqs = sorted(set(seqs))
    by_crs = collections.defaultdict(list)
    for crscd, sq, st, en in seqs:
        by_crs[crscd].append((st, sq, en))
    stamp = today.strftime("%Y%m%d")
    rows = []
    for crscd, c in sorted(courses.items()):
        sch = sorted(by_crs.get(crscd, []))
        fut = [x for x in sch if x[0] >= stamp]
        nxt = fut[0] if fut else ("", "", "")
        c.update({
            "schedule_count": len(sch), "next_start": nxt[0], "next_crsseq_id": nxt[1], "next_end": nxt[2],
            "has_upcoming": bool(fut), "thumb_file": thumbs.get(crscd, ""),
            "thumb_url": f"https://www.kma.or.kr/upload/crs/{crscd}/{thumbs[crscd]}" if crscd in thumbs else "",
            "url_evergreen": ("https://www.kma.or.kr/usrs/eduRegMgnt/eduRegInfoDetailForm.do?p_edutype_cd=001"
                              f"&p_crscd={crscd}&p_crsseq_id=&p_view_type=S&p_ctgry_id={c['crs_ctgry_id']}&CRSCD={crscd}"
                              f"&CRSSEQ_ID=&p_hmpgcd=30&mkey={c['menu_id']}"),
        })
        rows.append(c)
    write_csv("kma_offline_live.csv",
              ["crscd", "crs_nm", "category", "crs_ctgry_id", "menu_id", "edutype_cd", "edu_day", "edu_time", "place",
               "fee_member", "fee_nonmember", "crsreg_type_cd", "schedule_count", "next_start", "next_end",
               "next_crsseq_id", "has_upcoming", "thumb_file", "thumb_url", "url_evergreen"], rows)
    write_csv("kma_offline_schedule_live.csv", ["crscd", "crsseq_id", "edu_strtdt", "edu_enddt"],
              [dict(zip(["crscd", "crsseq_id", "edu_strtdt", "edu_enddt"], x)) for x in seqs])
    upcoming = sum(1 for c in by_crs.values() if any(x[0] >= stamp for x in c))
    log.write(f"\ncourses={len(courses)} schedules={len(seqs)} thumbs={len(thumbs)} upcoming={upcoming}\n")
    log.close()
    print(f"crawl_kma: courses={len(courses)} schedules={len(seqs)} upcoming={upcoming}")


if __name__ == "__main__":
    main()
