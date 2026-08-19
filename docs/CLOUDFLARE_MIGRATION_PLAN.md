# Cloudflare 이전 현황

## 현재 적용

- 공개 오픈페이지: Cloudflare Workers Static Assets
- 공개 주소: https://kma-tap-open.skytree96.workers.dev
- 사용설명서 PDF: Cloudflare 정적 자산
- 검사·프로젝트·대시보드·리포트: 기존 Streamlit 앱 연결
- 기획검증 저장: GitHub demo-data JSON

무료 Cloudflare Workers에서는 Python Streamlit 서버를 그대로 실행할 수 없습니다. 따라서 현재 배포는 오픈페이지를 Cloudflare로 분리하고, 실제 기능 화면은 기존 Streamlit로 연결하는 1단계 구조입니다.

## 전체 이전안

1. Cloudflare D1용 프로젝트·검사·응답·리포트 스키마 설계
2. Worker API의 프로젝트 생성·검사 저장·사전/사후 연결 구현
3. 참여자 교육 전·후 검사 화면의 웹 프런트엔드 전환
4. 교육담당자·KMA 대시보드와 리포트 전환
5. 데이터 이전·권한검증·회귀검사 후 Streamlit 종료

현재 PostgreSQL 참조 스키마의 jsonb, 배열, RLS 등은 D1(SQLite)과 Worker 권한검사에 맞게 바꿔야 합니다. 전체 이전 전까지 Cloudflare 공개페이지와 Streamlit 기능 앱을 병행합니다.

## 배포

    cd cloudflare
    pnpm install
    pnpm run build
    pnpm exec wrangler deploy

배포 전 cloudflare/dist/index.html의 기능 링크가 https://kmatap.streamlit.app 을 가리키는지, /tap-user-guide.pdf가 정상 열리는지 확인합니다.
