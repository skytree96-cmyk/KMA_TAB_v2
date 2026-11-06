"""공개교육센터 과정 상세 페이지 확인: 링크가 살아 있는지(detail_ok)와 og:image 썸네일 (kma_offline_live.csv 보강).

KMA는 내려간 과정도 HTTP 200으로 안내 페이지를 돌려준다. 그 문구가 보이면 링크가 죽은 것으로 본다.
네트워크 오류는 판단을 비워 둔다(detail_ok=""): 그 과정은 빼지 않는다.
"""
import io
import re
import time

from catalog.common import read_csv, session, write_csv

ERROR_PAGE = "접속이 원활하지 않습니다"


def main() -> None:
    s = session()
    rows = read_csv("kma_offline_live.csv")
    log = io.open("crawl_kma_thumbs_log.txt", "w", encoding="utf-8")
    ok = broken = errors = 0
    for i, r in enumerate(rows):
        r.setdefault("detail_ok", "")
        try:
            resp = s.get(r["url_evergreen"], timeout=30)
            h = resp.text
            r["detail_ok"] = "False" if resp.status_code != 200 or ERROR_PAGE in h else "True"
            if r["detail_ok"] == "False":
                broken += 1
                log.write(f"{r['crscd']} detail page error\n")
            elif not r.get("thumb_url"):
                m = re.search(r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)', h)
                if m and "/upload/crs/" in m.group(1):
                    r["thumb_url"] = m.group(1)
                    r["thumb_file"] = m.group(1).rsplit("/", 1)[-1]
                    ok += 1
        except Exception as e:
            errors += 1
            log.write(f"{r['crscd']} ERR {e!r}\n")
        time.sleep(0.15)
    if rows:
        write_csv("kma_offline_live.csv", list(rows[0].keys()), rows)
    log.write(f"done thumbs={ok} broken={broken} errors={errors}/{len(rows)}\n")
    log.close()
    # 대부분이 "내려감"으로 나오면 사이트가 막혔거나 바뀐 것이다. 이때 내보내면 공개교육이 통째로 빠진다.
    if rows and broken > 0.3 * len(rows):
        raise SystemExit(f"detail pages: {broken}/{len(rows)} look broken; site may be blocking or changed")
    print(f"crawl_kma_thumbs: broken={broken}/{len(rows)} errors={errors} new_thumbs={ok}")


if __name__ == "__main__":
    main()
