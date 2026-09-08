# KMA TAP 계정 서비스

주소 목표: https://kmatap.onrender.com · 배포 브랜치: `codex/production-accounts`.

## 계정과 데이터

- `kma`: 초기 운영자. 회원사와 교육담당자 계정을 생성하고 회사별 운영 현황을 본다.
- `company`: 소속 회사의 프로젝트·참여자 계정·배정을 관리한다.
- `participant`: 본인의 활성 배정에서만 검사와 개인 전후 결과를 이용한다.
- 로그인은 이메일 없이 회사 접두어가 포함된 지정 ID와 비밀번호를 사용한다.
- 비밀번호 길이는 최소 3자, 최대 128자다. 초기 관리자·신규 계정·비밀번호 변경·재설정에 같은 기준을 적용한다.
- 임시 비밀번호는 처음 사용할 때 변경한다. 비밀번호 원문은 DB/GitHub에 저장하지 않는다.
- 비밀번호 변경·재설정·계정 중지는 기존 세션을 폐기한다. 계정 중지와 프로젝트 배정 해제는 별도 기능이며 기존 결과는 보존한다.

PostgreSQL의 `tap_users`, `tap_companies`, `tap_projects`, `tap_assignments`, `tap_assessments`가 원본 데이터다. 검사 결과는 **참여자 계정의 프로젝트 배정 + pre/post**에 연결된다. 문항별 임시저장, 재로그인 복원, 사전 완료 후 사후 검사, 동일 문항 교집합 비교를 지원한다. 최종 제출한 응답은 변경할 수 없다. 서버가 회사·소유권·검사 기간·문항 버전을 확인하며, 조직 결과는 역량별 전후 유효응답 N≥5일 때 공개한다.

## Render 연결

`render.yaml`은 무료 Python 웹서비스 `kmatap`과 Singapore의 무료 PostgreSQL `kmatap-db`를 연결한다. 사용자 승인 범위는 비용 없는 초기 검증이다. [무료 DB는 생성 후 30일간 저장 가능하며 그 뒤 만료된다](https://render.com/docs/free). 만료 전 유료 전환 또는 내보내기/이전이 필요하다. 운영 중 로컬 SQLite나 GitHub 저장으로 자동 전환하지 않는다.

환경변수:

- `TAP_APP_MODE=production`: 기본값도 운영 모드다. 기존 데모 페이지는 이 모드에서 차단된다.
- `DATABASE_URL`: Blueprint가 DB의 내부 연결 주소를 참조한다. 소스에 기록하지 않는다.
- `BOOTSTRAP_ADMIN_LOGIN=kma.admin`
- `BOOTSTRAP_ADMIN_PASSWORD_HASH`: 첫 관리자용 scrypt 해시. Render 비밀 설정으로만 입력한다. DB에 사용자가 있으면 재부팅 때 관리자를 재생성하지 않는다.
- `GITHUB_DEMO_STORE_ENABLED=false`
- `TAP_POSTGRES_PREFLIGHT=1`: 최초 연결 검증용. 통과 후 `0`으로 바꾼다.

시작 명령은 `python scripts/start_accounts.py`다. DB 초기화가 성공한 뒤 Streamlit을 시작한다. 기본 주소 `/`, 로그인 `/login`, 새 이용안내 `/guide`만 운영 경로로 등록한다. 공용 첫 화면과 사이드바 CI는 공식 OFL Paperlogy 폰트를 로컬로 포함해 표시한다.

## 검증 명령

```text
python -B -m unittest discover -s tests -p "test_account*.py" -q
python -B scripts/validate_project.py --write-manifest
python -B scripts/validate_project.py
```

기존 검사·리포트 회귀 검증은 `TAP_APP_MODE=demo`를 명시한 별도 테스트 프로세스에서 전체 unittest와 `scripts/smoke_pages.py`를 실행한다. 이 설정을 운영 서비스에 적용하지 않는다.

실제 PostgreSQL 검증은 `TEST_DATABASE_URL`을 지정하고 `python scripts/check_postgres_accounts.py`를 실행한다. Render 최초 실행에서는 `TAP_POSTGRES_PREFLIGHT=1`과 `--render-preflight`를 함께 사용한다. 고유한 임시 스키마에서 생성·로그인·사전 저장·별도 연결 복원·사후 비교·접근 차단·세션 폐기를 확인한 후 그 스키마만 정리한다. 실제 관리자와 운영 테이블의 데이터는 테스트에 사용하지 않는다.

배포 전후에는 DB 재접속·권한 차단과 브라우저에서 로그인/최초 비밀번호 변경/회사·프로젝트 배정을 점검한다. 무료 웹서버는 유휴 시 중단되지만 별도 PostgreSQL에 성공적으로 저장한 검사 응답은 웹서버 재시작과 분리된다.
