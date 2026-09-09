# Render 시험 이전

2026-09-08 · **공개 합성자료 테스트용. 로그인·운영 DB 구현은 다음 단계다.**

- 시험 URL: [kma-tap-staging](https://kma-tap-staging.onrender.com)
- 코드: [KMA_TAB_v2](https://github.com/skytree96-cmyk/KMA_TAB_v2)
- 최초 시험 배포: `main`, 기준 커밋 `83e640fc259f4c1351e2958660401f79a41fee82`
- 이어지는 수정 배포: `codex/render-staging`. `render.yaml`은 이 브랜치를 지정한다.

순서는 **Render 시험 구동 → 로그인·권한·DB 구현 → 역할별 검증 → 정식 전환**이다. 현재 역할 전환과 회사 확인은 데모 기능이다. 실명·실제 사번·비밀번호·검사 응답을 넣지 않는다.

## 배포 설정

Python / Singapore / Free, 자동 배포 Off, GitHub 데모 저장 비활성화다. 처음에는 Render의 공개 Git URL 방식으로 만들었다. YAML 추가만으로 기존 서비스 설정이 동기화되는 것은 아니므로 대시보드에서도 대상 브랜치와 설정을 맞춘다.

```text
Build: python -m pip install -r requirements.txt
Start: python -m streamlit run streamlit_app.py --server.address=0.0.0.0 --server.port=$PORT --client.toolbarMode=minimal
Health: /_stcore/health
GITHUB_DEMO_STORE_ENABLED=false
```

`autoDeployTrigger: "off"`는 수동 배포 설정이다. 서비스 이름이 다른 기존 서비스와 중복되면 새 이름을 선택한다. [Blueprint 명세](https://render.com/docs/blueprint-spec)

기존 `.python-version`의 `3.12`를 유지한다. Render는 최신 3.12 패치를 선택한다. 우선순위가 더 높은 `PYTHON_VERSION` 환경변수는 전체 패치 버전을 요구하므로 이번에는 추가하지 않는다. [Python 설정](https://render.com/docs/python-version)

기존 Streamlit 앱·도메인·GitHub 데모 데이터 브랜치는 유지한다. 기존 저장 토큰·공유 코드·salt·실제 secrets 파일·공유 환경변수 그룹을 Render로 복사하지 않는다. 이번 구성에는 DB·디스크가 없다. 무료 서비스는 유휴 중 중단될 수 있고 로컬 파일은 재시작 시 사라진다. 현재 세션 응답의 장기 보존은 지원하지 않는다. [무료 서비스 제한](https://render.com/docs/free)

## 랜딩 링크 수정

`tap/open_page.py`가 HTML을 표시할 때만 기존 Streamlit 호스트의 앱 링크를 `/pre_assessment` 같은 상대 경로로 바꾼다. Render·로컬·자체 도메인에서 현재 호스트를 유지하고 경로·역할 쿼리는 보존한다. 원본 HTML과 Cloudflare 빌드는 변경하지 않는다.

## 다음 구현 범위

- KMA 관리자 개인 계정 초기 발급 → 회사·교육담당자 생성 → 담당자의 프로젝트 개설·참여자 일괄 등록·배정.
- 이메일 없이 지정 ID·비밀번호 사용. 회사 구분을 포함한 유일 로그인 ID와 내부 사용자 ID를 분리한다. 최초 임시 비밀번호 변경, 담당자 재설정, 비활성화·세션 폐기를 구현한다. 기존 비밀번호 조회는 제공하지 않는다.
- 계정은 유지하고 교육마다 참여 배정을 추가한다. 한 프로젝트에서 제외해도 다른 배정은 유지한다. 로그인 후 하나면 해당 교육, 여러 개면 내 교육 목록을 보여준다.
- GitHub는 코드·문항 버전 관리에 사용한다. 회사·계정·권한·프로젝트·배정·응답·감사 이력은 PostgreSQL에 저장한다. DB·인증 비밀은 서버 설정에만 둔다. 현재 참고 SQL에 계정·소속·배정 마이그레이션과 DB 연결을 추가해야 한다.

점검한 파일은 `tap/runtime_guard.py`, `tap/ui.py`, `tap/state.py`, `tap/tenant.py`, `tap/github_demo_store.py`, `pages/1_project_setup.py`부터 검사·리포트·KMA·담당자 페이지, `database/production_schema.sql`이다. runtime guard는 소스 버전 검사이며 인증이 아니다. 공유 코드·회사 확인·역할 메뉴·참여자 ID 입력은 서버 권한을 대체하지 못한다.

운영에서는 모든 조회·저장·다운로드에 역할·회사·참여 배정 소유권을 강제한다. 캐시도 권한 범위별로 나누고 계정·프로젝트 변경 시 세션 응답을 초기화한다. 프로젝트 코드·임의 ID·JSON 기준파일 복원은 인증된 배정과 DB 자동 복원으로 대체한다. DB·인증 미설정 및 저장 실패는 완료로 처리하지 않는다.

## 검증

시험 단계에서는 상태 확인뿐 아니라 랜딩 CTA가 Render 안에서 이동하는지, 안내·검사·리포트가 합성 자료로 동작하는지, GitHub 저장이 꺼져 있는지 확인한다. 문항·채점 회귀 검증과 manifest 갱신도 수행한다.

정식 전에는 비로그인 직접 URL·역할 쿼리 조작·타 회사와 타인 ID 접근 차단, 계정 교체·다중 프로젝트 응답 격리, 비밀번호 재설정 후 세션 폐기, 중복·동시 제출, DB 저장 실패, 재시작 후 사전·사후 복원과 백업 복구를 검증한다.
