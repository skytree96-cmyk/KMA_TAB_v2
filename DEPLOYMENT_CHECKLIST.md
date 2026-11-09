# TAP 배포 체크리스트

운영은 Cloud Run `kmatap`(프로젝트 `kma-tab`, 리전 `asia-northeast1`) 하나입니다. 주소는 https://tap.kma.or.kr 입니다.

## 릴리스마다

- [ ] 작업 브랜치에서 `python scripts/validate_project.py --write-manifest` 후 `python scripts/validate_project.py` 통과
- [ ] `TAP_APP_MODE=demo python -m unittest discover -s tests` 통과
- [ ] PR을 올리고 GitHub Actions `TAP validation` 통과 확인
- [ ] 담당자 확인 후 main에 머지. 머지하면 `Deploy to Cloud Run`이 자동으로 배포합니다.
- [ ] 배포 후 최신 리비전이 트래픽 100%를 받는지 확인. `preview` 태그 배포 뒤에는 트래픽이 이전 리비전에 고정돼 있을 수 있습니다.

  ```bash
  gcloud run services describe kmatap --project kma-tab --region asia-northeast1 --format="value(status.traffic)"
  ```

- [ ] https://tap.kma.or.kr 첫 화면과 `/_stcore/health`가 200으로 응답
- [ ] 새 리비전에 오류 로그가 없는지 확인
- [ ] 화면을 바꾼 릴리스는 KMA 관리자·교육담당자·참여자 세 역할로 확인
- [ ] 문제가 있으면 Cloud Run 콘솔에서 이전 리비전에 트래픽 100%를 돌려 롤백

## 교육과정 카탈로그

- 매주 월요일 03:00(KST) `Course catalog weekly refresh`가 과정을 다시 모아 main에 직접 커밋하고 배포까지 합니다. 바뀐 과정이 없으면 커밋·배포를 건너뜁니다.
- 실패하면 GitHub가 메일을 보냅니다. 결과는 Actions 실행 화면 요약에서 봅니다.

## 데이터·보안

- [ ] `.env`, `.streamlit/secrets.toml`, `deploy/gcp/config.env`, 개인정보가 든 파일이 커밋에 없는지 확인
- [ ] 비밀값(DB 주소, 관리자 해시)은 Secret Manager에만 둡니다.
- [ ] 개인정보 처리 항목·보관 기간·회사 제공 범위를 바꾸면 동의 화면 문구(`tap/account_consent.py`)와 동의 버전, 개인정보 처리방침, 이용 안내를 함께 고칩니다.
