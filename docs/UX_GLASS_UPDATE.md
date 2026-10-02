# KMA TAP UX 변경 및 운영 기능 점검

## 적용 방향
PAI LOOP(https://pai-loop.pages.dev/)의 큰 제목, 밝은 배경, 넓은 여백과 절제된 패널 깊이를 참고한다. 기존 Teal(#087b76, #0a4f4a)과 Paperlogy CI를 유지한다. 카드와 폼을 반투명 그라데이션으로 통일하고, 블러는 헤더·큰 패널에 집중한다. 버튼의 가벼운 hover 이동만 사용하며 reduced-motion 설정에서는 제거한다.

## 실제 운영 경로
`streamlit_app.py`의 production 라우터는 `account_landing`, `account_portal`, `account_guide`를 연결한다. 기존 `pages/*`, `tap/ui.py`는 데모 경로이므로 이번 운영 UX 수정의 대상이 아니다. 오픈페이지 HTML은 `account_landing_html()`이 운영 문구와 /login·/guide 링크로 변환해서 사용한다.

## 변경 파일과 주요 선택자
- `docs/TAP_오픈페이지_와이어프레임_v1.html`: CSS만 수정. .site-header, .hero, .product-window, .step-card, .role-card, .method-card, .report-surface, .button과 반응형 규칙. 문서 구조·본문·앵커·스크립트를 유지한다.
- `tap/account_landing.py`: 운영 랜딩의 배경과 주입 CI를 다크 팔레트에 맞춘다. 기존 문구 변환·링크·렌더링 흐름은 유지한다.
- `assets/account-ui.css`: --tap-* 토큰, .stApp 범위의 폼·입력·탭·확장 영역·버튼·라디오·카드 공통 표현. 생성되는 Emotion 클래스와 nth-child는 사용하지 않는다.
- `tap/account_theme.py`: 로컬 CSS를 읽어 재사용한다. 외부 요청이나 데이터 접근이 없다.
- `tap/account_portal.py`: 소개 영역과 로그인 카드의 2열 배치. 760px 이하에서는 세로 배치한다. 기존 form key·로그인·비밀번호·세션 로직은 유지한다.
- `tap/account_admin_ui.py`: 발급 정보 컨테이너에 스타일용 고정 key만 추가한다.
- `tap/account_guide.py`: 처음 로그인·역할별 안내·결과·비밀번호 안내를 카드로 배치하고 기존 문구와 링크를 유지한다.

## CSS 적용 원칙
- 카드: 밝은 반투명 border, translucent gradient, 16~26px radius, inset highlight와 얕은 shadow.
- 버튼: Teal gradient와 흰 글자. primary와 primaryFormSubmit을 모두 포함한다.
- 입력: Streamlit 1.61의 [data-testid="stTextInputRootElement"], select의 [role="group"], 기존 date 입력을 대상으로 얇은 테두리·focus ring·충분한 터치 높이를 적용한다.
- 탭과 라디오: role 및 aria-selected, [data-testid="stRadioOption"][data-selected="true"]를 기준으로 선택 상태를 표시한다.
- 상태 보호: account_admin_* 탭·CSV key와 on_change, _tap_participant_* 문항 key·저장 콜백을 변경하지 않는다.
- 다크 화면: 내부 화면은 Streamlit의 color-scheme에 대응하는 light-dark() 토큰, 랜딩은 prefers-color-scheme 규칙을 사용한다. 차트·표는 내용 판독을 우선한다.
- 모바일: 로그인과 안내 카드 세로 배치, 탭 가로 스크롤, 44px 이상 주요 조작 영역, 문항 카드 패딩 조정.
- 폰트·아이콘·스타일은 기존 로컬 자산을 사용한다. 새 외부 의존성을 추가하지 않는다.

## 렌더링 방식
현재의 st.html 렌더링을 유지한다. 문서 내부 섹션 이동과 같은 서비스의 로그인·이용안내 링크가 정상 작동하며, iframe으로 바꾸면 높이 동기화·중첩 스크롤·상위 페이지 이동 문제를 다시 다뤄야 한다. 고정된 저장소 HTML에만 기존 JavaScript 허용을 유지하고, 로그인과 검사 입력은 native Streamlit 위젯으로 처리한다. 이번 변경에서는 랜딩 렌더러와 JavaScript를 변경하지 않는다. 내부 공통 CSS는 st.html로 주입하여 Markdown이 CSS 선택자를 해석하지 않도록 한다.

## 앞선 요청 재점검
| 요청 | 현재 구현 |
|---|---|
| 역할 분리 | 서버의 KMA·교육담당자·참여자 권한 및 회사/배정 범위 검증 |
| 회사 식별정보 | 사업자등록번호 ASCII 숫자 10자리, 앞자리 0 보존·중복 거부 |
| 로그인 ID | 교육담당자는 지정 ID, 참여자는 회사 접두어를 포함한 ID |
| 임시 비밀번호 | 교육담당자·참여자 신규/CSV 발급·재발급 kma, 처음 로그인 시 변경 |
| 비밀번호 길이 | 3~128자 |
| 참여자 추가 정보 | 부서·직급·이메일·연락처 선택 입력 및 DB·CSV 지원 |
| 사전·사후 결과 | DB에 배정/단계별 저장, 재로그인 복원, 완료 불변성과 전후 비교 |
| 관리자 탭·CSV | 업로드/발급/프로젝트 생성/발급정보 닫기 후 상태 유지 |
| 다음 문항 오류·대기 | 저장 확인 후 다음 문항 1회 렌더, 검사 UI 저장소 호출 7→3회 |
| 저장 실패·동시 제출 | 현재 문항/선택값 보존, 최신 완료 상태가 바뀌면 DB 재조회 |
| 브랜딩·데모 제거 | Paperlogy CI, 초기 HTML부터 KMA TAP/T 아이콘, 운영 데모 문구·역할 전환 차단 |

기존 ID·실제 비밀번호를 일괄 재설정하지 않는다. 계정·검사 응답의 원본은 PostgreSQL이며 GitHub에는 코드가 저장된다. 비용 없는 Render 테스트 범위를 유지한다.

## 검증
수정 전 운영 기능은 배포 커밋 4dde209와 일치하며 기존 300개 테스트가 통과한 상태에서 시작했다. 로컬 브라우저에서 데스크톱·390px 모바일·768px 태블릿, 내부 다크 테마와 랜딩 다크 CSS 분기를 확인했다. 로그인 입력·모바일 메뉴와 섹션 이동·교육담당자 탭·참여자 저장 후 다음 문항 전환을 확인했다. 기존 계정·탭·문항 회귀 검사와 전체 CI/PostgreSQL 검증을 배포 전에 실행한다. 변경 diff는 같은 배포 브랜치의 UX 커밋에 기록한다.
