# TAP Streamlit MVP

KMA 회원사의 교육 요구를 확인하고 교육과정을 연결하기 위한 Streamlit 공개 검토용 MVP입니다.

이번 버전은 인터랙티브 목업의 Teal·Mint 디자인 시스템을 적용하고 역할별 화면을 분리했습니다.

화면의 Material 아이콘 글꼴 충돌과 다크모드 대비를 수정했으며, 조직 리포트는 A4 페이퍼형 4쪽 구조와 인쇄용 HTML 다운로드를 제공합니다. 사이드바의 영문 자동 페이지명은 숨기고 사용자 화면을 한글로 통일했습니다.

| 데모 역할 | 기본 화면 | 제공 범위 |
|---|---|---|
| 교육담당자 | 관리자 대시보드 | 자사 프로젝트·참여율·조직 집계·교육 추천 |
| 참여자 | 진단 참여 | 본인 진단·개인 리포트·선택적 결과 공유 |
| KMA 관리자 | KMA 대시보드 | 회원사 운영상태·문항 버전·과정 매핑·감사로그 |

사이드바의 역할 전환은 공개 검토용 데모 기능입니다. 실제 운영에서는 인증·조직 소속·서버단 권한검사를 연결해야 합니다.

## 핵심 정리

| 구분 | 원본 | 이번 배포본 |
|---|---:|---:|
| 전체 역량 | 36 | 운영 31, 비활성 5 |
| 전체 문항 | 144 | 운영 124, 비활성 20 |
| 파일럿 후보 | - | 4개 후보역량·16문항, 점수 산출 비활성 |
| 역문항 | 5 | 0 |
| 점수 | 임의 규준 T점수·백분위 | 행동빈도 평균 1~5 + 표시용 0~100 |
| 직급 | 5개 독립 점수 | 대상자·문항 적용 기준 |
| 조직 집계 | 소표본 억제 없음 | N<5 비공개 |

## 화면·선택 UI

- 목업과 같은 `#102A2D / #087B76 / #DFF4F1 / #F4F8F7` 팔레트, 20px 카드, 다크틸 히어로를 사용합니다.
- 프로젝트의 기본역량은 체크된 고정 카드로 표시합니다.
- 전문·미래역량은 체크박스로 최대 3개, 직무역량은 최대 1개, 합계 최대 4개를 선택합니다.
- 조직 우선역량과 학습 희망역량도 목록형 선택 대신 체크박스를 사용합니다.
- 현재 원본의 `target_levels`를 유지하므로 기본값인 관리자·리더는 8개·32문항, 실무자는 적용 가능한 6개·24문항입니다. CORE8을 전 직급 공통으로 고정하려면 전문가 감수 후 해당 메타데이터를 먼저 변경해야 합니다.

## 빠른 사용법

1. 사이드바 `처음 사용 안내`에서 자신의 역할을 확인합니다.
2. 교육담당자는 `진단 프로젝트`에서 대상·기간·역량·임시 목표를 설정합니다.
3. 참여자는 `진단 참여`에서 최근 8주 행동을 한 문항씩 응답합니다. 공개 데모의 응답은 브라우저 세션에만 임시 저장됩니다.
4. 개인은 본인 리포트를 보고, 교육담당자는 `조직 리포트`에서 익명 집계를 확인합니다.
5. 조직 리포트의 `인쇄용 리포트 HTML`을 내려받아 브라우저의 `인쇄 → PDF 저장`을 사용합니다.

화면 안의 상세 안내와 PPT 가이드는 `pages/0_user_guide.py`, `docs/TAP_빠른사용가이드_v3.pptx`에서 제공합니다.

운영용 조직 리포트 CSV에는 `participant_id`, `factor_code`, `factor_name_ko`, `score_1_to_5`, `project_id`, `assessment_version`, `assessment_date` 7개 열이 모두 필요합니다. 화면의 `CSV 양식 내려받기`를 사용하면 올바른 형식으로 시작할 수 있습니다. 공개 데모에는 실제 개인정보나 기밀 응답을 업로드하지 마세요.

원본 144문항은 모두 `data/question_bank.csv`에 보존돼 있습니다. 직급 20문항은 `active=false`, `original_decision=삭제`로 표시됩니다. 영업 4문항과 마케팅 1문항은 정적 SQL과 실행 API 문구가 달라 두 원문을 함께 기록했습니다.

## 실행

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/validate_project.py
python -m unittest discover -s tests -v
python scripts/smoke_pages.py
streamlit run streamlit_app.py
```

## GitHub → Streamlit Community Cloud

1. 이 폴더의 내용만 GitHub 저장소 루트에 업로드합니다.
2. Streamlit Community Cloud에서 저장소를 연결합니다.
3. 엔트리 파일은 `streamlit_app.py`, Python은 3.12로 설정합니다.
4. 공개 검토용은 별도 secret 없이 실행됩니다.
5. 실제 운영 secret은 GitHub가 아닌 Streamlit Secrets 화면에 입력합니다.

GitHub Actions는 push와 pull request마다 데이터 무결성, 단위 테스트, Python 문법 검사를 실행합니다.

Streamlit은 배포용 의존성을 `requirements.txt` 등으로 선언하도록 안내하며, 비밀값은 별도 Secrets 관리에 넣도록 안내합니다.

- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management

## 문항·채점

공통 지시문은 `최근 8주 동안 실제 업무에서 다음 행동을 얼마나 자주 했습니까?`입니다.

| 응답 | 점수 | 표시용 지수 |
|---|---:|---:|
| 전혀 없었다 | 1 | 0 |
| 드물게 있었다 | 2 | 25 |
| 가끔 있었다 | 3 | 50 |
| 자주 있었다 | 4 | 75 |
| 거의 항상 있었다 | 5 | 100 |
| 수행 기회 없음 | NA | 분모 제외 |

- 역량별 4문항은 동일가중입니다.
- 유효문항 3개 이상일 때만 역량 평균을 산출합니다.
- 미응답과 `수행 기회 없음`은 별도로 집계합니다.
- `difficulty`는 원본 메타데이터이며 배점에 사용하지 않습니다.
- 서로 다른 역량을 합친 종합점수는 제공하지 않습니다.
- 규준이 없으므로 T점수·백분위·개인순위는 제공하지 않습니다.
- 사전·사후 차이는 `자기보고 행동빈도 변화`로만 해석합니다.
- 행동빈도 구간은 파일럿 전 `임시 기술구간`이며 표준설정 결과가 아닙니다.

## 교육 추천 100점

| 항목 | 배점 |
|---|---:|
| 목표수준과 현재수준의 격차 | 40 |
| 역량–과정 내용 매핑 적합도 | 30 |
| 조직 우선순위 | 15 |
| 본인 학습희망 | 10 |
| 대상수준·교육방식 적합 | 5 |

격차 원인이 권한·도구·프로세스 등 시스템 요인이라면 교육 추천은 0으로 차단합니다. 원인을 아직 모르면 총점에 0.5 게이트를 적용합니다. 과정명과 URL은 원본 코드의 예시를 정리한 것이므로 실제 운영 전 KMA 과정코드·개설상태와 대조해야 합니다.

이 점수는 `교육과정 검토 우선순위`를 돕는 휴리스틱입니다. 목표 3.5에서는 격차 항목의 실제 최대가 25점이며, 0.5 게이트는 모든 과정에 동일하게 적용되어 순위를 바꾸지 않습니다. 가중치는 전문가 합의와 민감도 분석 후 확정해야 합니다.

## 구조

```text
streamlit_app.py
pages/                    # 설정·진단·개인·조직·문항은행·KMA 대시보드
tap/                      # 데이터·채점·추천·집계·선택·대시보드 로직
data/                     # 144문항, 36역량, 과정·매핑, 명시적 데모 데이터
docs/                     # 교육평가 검토보고서와 빠른 사용 가이드
database/                 # 실제 운영용 PostgreSQL 참조 스키마
tests/                    # 순수 로직과 데이터 무결성 테스트
scripts/validate_project.py
```

## 타당화 상태

현재 문항 판정은 역량 정의·행동구체성·단일성·수행기회·편향·척도 적합성에 대한 1차 내용검토입니다. 통계적 타당화 완료를 의미하지 않습니다.

후속 절차:

1. 교육측정·평가 전문가 검수
2. 직무·직급별 인지면접
3. 회원사 파일럿
4. 문항 결측/NA율·천장/바닥효과·문항-총점상관·신뢰도 분석
5. 요인구조·집단별 DIF 검토
6. 충분한 표본과 사용목적별 타당도 근거가 확보된 뒤 규준 검토

근거:

- Standards for Educational and Psychological Testing: https://www.testingstandards.net/uploads/7/6/6/4/76643089/standards_2014edition.pdf
- CDC Cognitive Interviewing: https://www.cdc.gov/nchs/ccqder/question-evaluation/cognitive-interviewing.html
- CDC Training Needs Analysis: https://www.cdc.gov/training-development/php/about/assess-training-needs-conducting-needs-analysis.html

## 운영 한계

이 ZIP은 별도 DB·로그인 없이 즉시 공개 검토 배포가 가능합니다. 응답은 브라우저 세션에만 유지되므로 실사용 데이터를 수집하지 마세요. 실제 운영 조건은 `SECURITY.md`, `DEPLOYMENT_CHECKLIST.md`, `database/production_schema.sql`을 따릅니다.
