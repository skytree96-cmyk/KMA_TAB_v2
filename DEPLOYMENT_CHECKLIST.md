# Streamlit Community Cloud 배포 체크리스트

## 공개 검토용 DEMO

- [ ] 이 폴더만 새 GitHub 저장소 루트에 업로드
- [ ] `.env`, `.streamlit/secrets.toml`, 개인식별정보 파일이 없는지 확인
- [ ] `python scripts/validate_project.py` 통과
- [ ] `python -m unittest discover -s tests -v` 통과
- [ ] GitHub 저장소 연결 후 엔트리 파일을 `streamlit_app.py`로 지정
- [ ] Python 3.12 선택
- [ ] 배포 후 처음 사용 안내·홈·프로젝트 설정·진단·개인리포트·조직리포트·문항은행 순회
- [ ] 사이드바 접기·파일 업로드 아이콘이 `keyboard_double...`, `upload` 글자로 노출되지 않는지 확인
- [ ] 밝은 화면과 운영체제 다크모드에서 본문·버튼·입력창 대비 확인
- [ ] 교육 전후 리포트 예시 워터마크, 짝지어진 참여자 N<5 보호, 인쇄용 HTML 다운로드 확인
- [ ] 교육 전·후에 같은 익명 참여자 ID와 같은 문항 버전이 유지되는지 확인
- [ ] 사후검사 시작일이 교육일 8주 이후인지, 검사기간 밖 제출 차단이 운영 환경에서 켜져 있는지 확인
- [ ] 공개 데모에 실제 개인정보·기밀자료를 업로드하지 않는다는 안내 확인

## 실제 회원사 운영

- [ ] 외부 PostgreSQL 연결 및 스키마 적용
- [ ] KMA 관리자·교육담당자·참여자 역할별 인증/인가 구현
- [ ] 프로젝트/문항/채점/과정매핑 버전 고정
- [ ] 조직 업로드에 project_id·assessment_version·target_level·assessment_date를 저장하고 혼합 집계 차단
- [ ] 개인정보 처리방침·동의·철회·보유기간 반영
- [ ] 개인결과 HR 공유는 별도 동의가 있을 때만 허용
- [ ] N<5 및 보완 억제 검증
- [ ] 과정코드·개설상태·URL을 실제 KMA 카탈로그와 대조
- [ ] 인지면접 표본과 파일럿 목표표본을 연구설계서에서 사용목적·집단구성·분석모형 근거와 함께 확정
- [ ] 신뢰도·요인구조·DIF 분석 후 문항/해석 기준 확정
- [ ] 비밀검사·의존성 감사·조직 간 접근 방지 테스트를 CI에 추가

공식 배포 안내: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app
