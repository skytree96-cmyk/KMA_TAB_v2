# 교육과정 카탈로그 주간 갱신

리포트의 교육 추천은 `data/courses.csv`(과정)와 `data/competency_course_map.csv`(역량-과정 연결)를 읽는다.
이 폴더는 그 두 파일을 KMA 사이트에서 다시 만든다.

## 자동 실행

`.github/workflows/catalog-weekly.yml`이 매주 월요일 03:00(KST)에 돈다. PC를 켜 둘 필요는 없다.

1. 공개교육센터 카테고리별 과정·기수 수집 (`crawl_kma.py`)
2. 과정 상세 페이지가 살아 있는지 확인하고 썸네일 보강 (`crawl_kma_thumbs.py`)
3. stud.io 이러닝 목록 수집 (`crawl_studio.py`), LXP 과정명과 맞추기 (`match_lxp.py`)
4. 역량 매핑 규칙 적용 (`build_catalog.py`)
5. 이전 카탈로그와 비교: 출처별 과정 수가 30% 넘게 줄거나 연결 수가 20% 넘게 줄면 이번 결과를 쓰지 않는다 (`run_weekly.py`)
6. `data/` 갱신, 배포 해시 목록 갱신, CI와 같은 검사 전체 실행
7. 바뀐 게 있으면 main에 바로 커밋하고 Cloud Run 배포를 시작한다

수집이 실패하거나 검사를 통과하지 못하면 커밋하지 않는다. 앱은 지난 카탈로그를 그대로 쓰고, GitHub가 실패 메일을 보낸다.
실행 결과(출처별 과정 수, 새 과정·빠진 과정)는 Actions 실행 화면 요약에 남는다.

손으로 돌리기: GitHub Actions → "Course catalog weekly refresh" → Run workflow. `dry_run`을 켜면 수집·검사만 하고 커밋하지 않는다.

## 입력 (`inputs/`)

KMA 내부 엑셀에서 필요한 열만 옮긴 것이다. 저장소가 공개라서 담당자 이름 같은 열은 넣지 않았다.

| 파일 | 원본 | 언제 고치나 |
|---|---|---|
| `kma_categories.csv` | 오프라인교육_수강신청형 엑셀 1번 시트의 카테고리 ID·메뉴 ID | 공개교육센터에 카테고리가 생기거나 없어질 때. 새 카테고리는 `build_catalog.py`의 `CAT_MAP`에도 넣어야 추천 후보가 된다 |
| `kma_b2b_courses.csv` | 같은 엑셀 2번 시트(교육문의형) | 교육문의형 과정이 바뀔 때 |
| `lxp_courses.csv` | LXP 이러닝 과정리스트 엑셀 | 이러닝 과정이 추가될 때 |
| `studio_original.csv` | stud.io 임대 가능 콘텐츠 리스트 엑셀 | 오리지널 콘텐츠가 추가될 때 |

## 로컬 실행

```
python -m pip install -r catalog/requirements.txt
python -m catalog.run_weekly --dry-run   # data/를 바꾸지 않고 요약만
python -m catalog.run_weekly             # data/ 갱신
python scripts/validate_project.py --write-manifest
```

수집 결과는 `.tmp/catalog_work/`에 남는다(커밋하지 않음).

## 개강일

카탈로그와 별도로, 앱은 공개교육 개강일을 하루 한 번 KMA 사이트에서 직접 받는다(`tap/course_schedule.py`, `TAP_LIVE_SCHEDULE=1`).
응답이 없는 카테고리는 이 카탈로그의 날짜를 쓴다.
