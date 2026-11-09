# KMA TAP — Google Cloud 운영 가이드

운영: **Cloud Run(도쿄) + Cloud SQL PostgreSQL 18**, 주소 `https://tap.kma.or.kr`.

| 구성 | 값 |
| --- | --- |
| 앱 | Cloud Run `kmatap`, asia-northeast1, 최소 1대 / 최대 3대, 세션 고정(session affinity) |
| DB | Cloud SQL `kmatap-db` (db-f1-micro, SSD 10GB, 자동백업 14일) |
| 비밀값 | Secret Manager `tap-database-url` (선택: `tap-bootstrap-admin-hash`) |
| 예상 비용 | 월 약 $25~35 (Cloud SQL ~$10, Cloud Run 최소 1대 ~$10~20, 기타) |

서울 리전(asia-northeast3)은 Cloud Run 도메인 매핑을 지원하지 않아 도쿄를 씁니다.

## 0. 준비

```bash
gcloud auth login
cp deploy/gcp/config.env.example deploy/gcp/config.env   # PROJECT_ID, DOMAIN 수정
```

Cloud Shell(브라우저)에서 실행해도 됩니다. 이 경우 저장소를 클론한 뒤 같은 명령을 쓰면 됩니다.

## 1. 인프라 생성 (최초 1회, 약 10분)

```bash
bash deploy/gcp/01_setup.sh
```

## 3. 앱 배포 (릴리스마다 반복)

```bash
bash deploy/gcp/03_deploy.sh
```

출력된 `https://kmatap-xxxx.a.run.app` 주소로 로그인·검사·리포트 PDF를 확인합니다.

빈 DB로 새로 시작하는 경우에만 관리자 비밀번호 해시를 먼저 넣습니다(사용자가 1명이라도 있으면 무시됨):

```bash
printf '%s' '$2b$...' | gcloud secrets create tap-bootstrap-admin-hash --data-file=-
```

## 4. 도메인 연결

### 4-1. 도메인 소유권 인증 (IT팀 협조)

Cloud Run 도메인 매핑은 gcloud 로그인 계정이 Google Search Console에서 도메인 소유자로 인증되어 있어야 합니다.

```bash
gcloud domains verify kma.or.kr
```

열리는 Search Console 화면에서 제시하는 `google-site-verification=...` TXT 값을 IT팀에 전달해 **kma.or.kr**에 TXT 레코드로 등록합니다. (서브도메인 자체에 TXT를 걸면 이후 CNAME과 충돌하므로 상위 도메인 인증을 권장)

### 4-2. 매핑 생성 및 CNAME 등록

```bash
bash deploy/gcp/04_domain.sh
```

출력되는 레코드(보통 `tap  CNAME  ghs.googlehosted.com.`)를 IT팀에 등록 요청합니다. DNS 반영 후 SSL 인증서는 자동 발급(15분~24시간).

#### IT팀 요청 문구 예시

> TAP 서비스 운영을 위해 아래 DNS 레코드 등록을 요청드립니다.
> 1) `kma.or.kr` TXT `google-site-verification=…` (Google 도메인 소유 인증용, 기존 레코드 유지)
> 2) `tap.kma.or.kr` CNAME `ghs.googlehosted.com.` (Google Cloud Run 연결)

## 문제 해결

- `--allow-unauthenticated` 실패: 조직 정책 `iam.allowedPolicyMemberDomains`가 공개 접근을 막는 경우입니다. 회사 GCP 관리자에게 이 서비스 예외를 요청하세요.
- 로그: `gcloud run services logs read kmatap --region=asia-northeast1 --limit=100`
- 롤백: Cloud Run 콘솔 → 리비전 → 이전 리비전에 트래픽 100%

## 자동 배포 (main 머지 시)

`.github/workflows/deploy.yml`이 main에 머지된 커밋의 검증(`TAP validation`)이 통과하면 `03_deploy.sh`를 실행하고, 새 리비전이 트래픽 100%를 받는지 확인합니다. 수동 실행은 GitHub Actions 화면의 **Deploy to Cloud Run → Run workflow**입니다.

최초 1회 프로젝트 소유자 계정으로 실행합니다(키 파일 없이 워크로드 아이덴티티 사용, 이 저장소의 main 브랜치만 허용).

```bash
bash deploy/gcp/05_github_deploy.sh
```

- 만드는 것: 서비스 계정 `tap-deploy`, 워크로드 아이덴티티 풀 `github`과 공급자 `kma-tab-v2`, 저장소 변수 3개(`GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SERVICE_ACCOUNT`, `GCP_DEPLOY_CONFIG`).
- `tap-deploy` 권한: Cloud Run 서비스 `kmatap` 배포, Cloud Build 실행, 빌드 소스 업로드, 빌드·실행 서비스 계정 사용. 비밀값과 DB는 읽지 못합니다.
- 자동 배포를 멈추려면 저장소 변수 `GCP_WORKLOAD_IDENTITY_PROVIDER`를 지우거나 워크플로를 비활성화합니다.
- `03_deploy.sh --preview`로 미리보기 배포를 한 뒤에는 트래픽이 고정될 수 있습니다. 그 상태에서는 자동 배포의 마지막 확인 단계가 실패로 알려 줍니다.
