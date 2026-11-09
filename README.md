# KMA TAP

KMA 회원사 임직원의 교육 전후 업무행동 변화를 같은 문항으로 재고, 개인·조직 리포트와 KMA 교육과정 추천으로 이어 주는 서비스입니다.

## 운영

- 주소: https://tap.kma.or.kr
- Google Cloud Run `kmatap` (프로젝트 `kma-tab`, 리전 `asia-northeast1`) + Cloud SQL PostgreSQL 18 `kmatap-db`
- 앱은 Streamlit 프레임워크로 동작하며, 컨테이너는 `scripts/start_accounts.py`로 시작합니다(`Dockerfile`).
- 인프라·도메인·자동 배포 설정: [`deploy/gcp/README.md`](deploy/gcp/README.md)
- 계정·데이터·환경변수: [`docs/ACCOUNT_DEPLOYMENT.md`](docs/ACCOUNT_DEPLOYMENT.md)
- 배포 점검 순서: [`DEPLOYMENT_CHECKLIST.md`](DEPLOYMENT_CHECKLIST.md)

| 역할 | 하는 일 |
|---|---|
| KMA 관리자 | 회원사·교육담당자 계정, 회사별 운영 현황, 접속 기록 |
| 교육담당자 | 참여자 계정·부서·직급, 프로젝트와 배정, 진행 현황, 조직 리포트 |
| 참여자 | 첫 검사 전 개인정보 동의, 교육 전·후 검사, 본인 리포트 |

## 배포 흐름

1. 작업 브랜치에서 고치고 PR을 올립니다. GitHub Actions `TAP validation`(`.github/workflows/ci.yml`)이 검증·PostgreSQL 점검·테스트를 돌립니다.
2. main에 머지하면 `Deploy to Cloud Run`(`.github/workflows/deploy.yml`)이 검증 통과 후 자동으로 배포합니다. **머지가 곧 운영 배포입니다.**
3. 배포 후 새 리비전이 트래픽 100%를 받는지 확인합니다.
4. 교육과정 카탈로그는 `.github/workflows/catalog-weekly.yml`이 매주 월요일 03:00(KST)에 갱신해 main에 커밋하고 배포합니다([`catalog/`](catalog/README.md)).

## 로컬 검증

```bash
python -m venv .venv
.venv\Scripts\activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python scripts/validate_project.py --write-manifest   # 파일을 바꾼 뒤 MANIFEST_SHA256.txt 갱신
python scripts/validate_project.py
TAP_APP_MODE=demo python -m unittest discover -s tests
TAP_APP_MODE=demo python scripts/smoke_pages.py
```

PostgreSQL 점검은 `TEST_DATABASE_URL`을 지정하고 `python scripts/check_postgres_accounts.py`를 실행합니다. 운영 모드 앱은 PostgreSQL(`DATABASE_URL`)이 있어야 뜹니다.

`TAP_APP_MODE=demo`는 초기 공개 MVP 화면(`pages/`, GitHub `demo-data` 합성 데이터 저장소)을 띄우는 모드입니다. 운영에는 쓰지 않고, 기존 검사·리포트 회귀 테스트에서만 씁니다.

## 구조

```text
streamlit_app.py   # 진입점 (운영: 계정 앱, 데모 모드: 초기 MVP)
tap/               # 앱 로직: account_*(운영 계정 앱), 채점·추천·리포트·PDF
pages/             # 초기 MVP 화면 (데모 모드 전용, 운영 이미지에서 제외)
data/              # 문항 144개·역량 36개, 과정과 역량 매핑
catalog/           # KMA 과정 수집·매핑, 주간 갱신
assets/            # 화면 CSS, 글꼴
docs/              # 사용설명서, 오픈페이지, 설계 문서
database/          # PostgreSQL 스키마
deploy/gcp/        # Cloud Run·Cloud SQL 설정 스크립트
scripts/           # 시작·검증·점검 스크립트
tests/             # 단위·화면 테스트
```

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
- 사전·사후 어느 한쪽이 `수행 기회 없음`이거나 유효문항 수가 부족하면 해당 역량의 변화값은 계산하지 않습니다.
- 사전·사후 변화는 동일 참여자·동일 역량·동일 문항 버전이 모두 확인된 짝만 계산합니다.
- `difficulty`는 원본 메타데이터이며 배점에 사용하지 않습니다.
- 서로 다른 역량을 합친 종합점수는 제공하지 않습니다.
- 규준이 없으므로 T점수·백분위·개인순위는 제공하지 않습니다.
- 비교집단이 없는 사전·사후 차이는 `교육 전후 관찰된 자기보고 행동빈도 변화`로만 해석하며 교육의 인과효과로 표현하지 않습니다.
- 행동빈도 구간은 파일럿 전 `임시 기술구간`이며 표준설정 결과가 아닙니다.

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
