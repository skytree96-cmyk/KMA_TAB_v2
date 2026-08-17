# GitHub 테스트 저장소 설정

이 기능은 자체 서버 구축 전 기획·화면 검증을 위한 합성 데이터 저장 기능입니다. 실제 개인정보나 실제 교육평가 응답을 저장하지 않습니다.

## 저장 구조

- 코드: `main` 브랜치
- 합성 테스트 데이터: `demo-data` 브랜치의 `tap-demo/v1/`
- 프로젝트 정의: `projects/{project_id}.json`
- 완료검사 스냅샷: `submissions/{project_id}/{participant_key}.json`
- 참여자 식별: 원문 ID가 아닌 프로젝트별 해시 키
- 저장 시점: 문항별 저장이 아닌 교육 전·후 검사 완료 시점

데이터 커밋을 코드 브랜치와 분리하므로 검사 저장으로 Streamlit 앱이 다시 배포되지 않습니다.

## 1. GitHub 토큰 생성

GitHub의 Fine-grained personal access token을 다음과 같이 생성합니다.

1. 대상 저장소: `skytree96-cmyk/KMA_TAB_v2`만 선택
2. Repository permissions: `Contents`의 `Read and write`만 허용
3. 짧은 만료기간 설정

`Actions`, `Administration`, 다른 저장소 권한은 필요하지 않습니다.

## 2. Streamlit Secrets 등록

Streamlit Community Cloud의 앱 설정에서 **Secrets**에 다음 내용을 등록합니다. 토큰은 코드나 GitHub 파일에 커밋하지 않습니다.

```toml
[github_demo_store]
enabled = true
repository = "skytree96-cmyk/KMA_TAB_v2"
branch = "demo-data"
token = "github_pat_발급값"
participant_hash_salt = "충분히-길고-임의적인-테스트용-문자열"
access_code = "교육담당자와-참여자에게-별도전달할-기획검증-접속코드"
report_preview_code = "교육담당자에게만-전달할-별도-리포트미리보기-코드"
```

`access_code`는 공개 앱의 무제한 쓰기와 참여자 결과 조회를 막는 기획검증용 공유코드입니다. GitHub 토큰·salt와 마찬가지로 저장소 파일에 커밋하지 말고 Streamlit Secrets에만 보관합니다. 프로젝트 생성 및 검사 화면에서 **기획검증 접속코드**에 같은 값을 입력해야 프로젝트·완료 결과 저장과 사후검사의 교육 전 결과 연결이 동작합니다. 코드가 없거나 일치하지 않아도 현 브라우저 세션과 기준파일(JSON) 흐름은 계속 사용할 수 있습니다.

공유 접속코드는 사용자별 인증이 아닙니다. 합성 테스트에서도 교육 참여자 ID는 이름·사번·순번이 아니라 참여자별로 무작위 배정한 추측하기 어려운 가명 코드를 사용하세요. 실제 운영에서는 참여자별 만료형 이어하기 토큰과 서버 인증으로 교체합니다.

`report_preview_code`는 N<5 소표본의 전·후 N각형을 **화면에서만** 확인하는 교육담당자용 기획검증 코드입니다. 쓰기용 GitHub 토큰은 요구하지 않으며, 설정하면 참여자용 `access_code`와 분리됩니다. 기존 설정과의 호환을 위해 이 항목이 없으면 `access_code`가 대신 사용되지만, 이 공유코드 방식은 데모 접근 마찰을 위한 장치일 뿐 인증·권한 관리가 아닙니다. 자체 서버 전환 시에는 별도의 강한 관리자 비밀값과 역할 기반 접근제어(RBAC)로 반드시 교체합니다.

저장 후 앱을 재시작하고 관리자 대시보드의 `GitHub 테스트 저장소 연결됨` 표시를 확인합니다.

## 3. 테스트 순서

1. 교육평가 프로젝트 생성 및 GitHub 게시 확인
2. 다른 브라우저에서 프로젝트 코드 불러오기
3. 무작위 가명 교육 참여자 ID로 교육 전 검사 완료
4. 같은 프로젝트·참여자 ID로 교육 후 검사 완료
5. 관리자 대시보드에서 누적 프로젝트·참여자·교육 전/후·짝지은 완료 확인
6. 조직 리포트에서 GitHub 누적 결과 선택 및 N≥5 공개 기준 확인

## 운영 전환 주의

GitHub 저장은 트랜잭션·개인정보 삭제·대량 동시 제출에 적합한 운영 DB가 아닙니다. 자체 서버 전환 시 `database/production_schema.sql` 기반 PostgreSQL 저장소로 교체하고, 현재 GitHub 저장 어댑터는 제거하거나 합성 데이터 전용으로 유지합니다.
