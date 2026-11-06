"""stud.io 이러닝 전체 목록 수집: 과정명 <-> eduSeq (+썸네일). 출력(작업 폴더): studio_elearning_live.csv"""
import io
import json
import time

from catalog.common import session, with_retry, write_csv

URL = "https://studio.kma.or.kr/papi/u/education/elearning/retrieveAllView"
PAGE_SIZE = 30
MAX_PAGES = 200


def main() -> None:
    s = session()
    s.headers.update({"Content-Type": "application/json", "Accept": "application/json",
                      "Referer": "https://studio.kma.or.kr/member/eLearning/view-all/01"})

    def fetch(page: int) -> list:
        body = {"cateSeq1": None, "cateSeq2": None, "cateSeq3": None, "crsNm": "", "testYn": "", "srvyYn": "",
                "size": PAGE_SIZE, "pageNumber": page, "eduDiv": "01"}
        r = s.post(URL, data=json.dumps(body), timeout=30)
        r.raise_for_status()
        content = r.json().get("result", {}).get("content")
        if not isinstance(content, list):
            raise ValueError("unexpected stud.io answer")
        return content

    items = []
    for page in range(1, MAX_PAGES + 1):
        content = with_retry(lambda: fetch(page))
        if not content:
            break
        items.extend(content)
        time.sleep(0.3)
    log = io.open("crawl_studio_log.txt", "w", encoding="utf-8")
    log.write(f"collected={len(items)} unique eduSeq={len({i['eduSeq'] for i in items})}\n")
    log.close()
    cols = ["eduSeq", "crsNm", "diffLvl", "crsCostAmt", "dscntRt", "thmbSeq", "thmbFileName", "thmbOriginalFileName", "url"]
    write_csv("studio_elearning_live.csv", cols,
              [{**{c: i.get(c) for c in cols}, "url": f"https://studio.kma.or.kr/member/eLearning/{i.get('eduSeq')}"}
               for i in items])
    print(f"crawl_studio: {len(items)} e-learning courses")


if __name__ == "__main__":
    main()
