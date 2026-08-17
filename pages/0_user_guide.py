from __future__ import annotations

from pathlib import Path

import streamlit as st

from tap.runtime_guard import stop_on_stale


stop_on_stale(st, ("tap.ui",))

from tap.config import PROJECT_ROOT
from tap.ui import callout, page_header, setup_page, switch_role_page


setup_page("처음 사용 안내", "?")
page_header(
    "처음 사용 안내",
    "TAP 교육평가는 네 단계만 기억하면 됩니다",
    "교육 전 출발점을 기록하고, 교육 후 현업 적용 시점에 같은 기준으로 다시 측정해 변화와 현업 적용환경을 확인합니다.",
    badge="약 2분 안내",
)

st.markdown(
    """
    <div class="tap-guide-grid">
      <div class="tap-guide-step"><span>1</span><b>교육·평가 설정</b><small>교육일과 사전·사후 기간, 공통 측정역량을 정합니다.</small></div>
      <div class="tap-guide-step"><span>2</span><b>사전검사</b><small>교육 전에 최근 8주의 행동을 기준으로 응답합니다.</small></div>
      <div class="tap-guide-step"><span>3</span><b>교육·현업 적용</b><small>교육 후 실제 업무에 적용할 시간을 확보합니다.</small></div>
      <div class="tap-guide-step"><span>4</span><b>사후검사·리포트</b><small>같은 기준으로 재검사해 짝지은 변화와 현업 적용환경을 봅니다.</small></div>
    </div>
    """,
    unsafe_allow_html=True,
)

callout(
    "기획검증용 GitHub 누적 저장",
    "GitHub 테스트 저장소를 연결하면 합성 프로젝트와 검사 완료 시점의 교육 전·후 응답 스냅샷을 별도 demo-data 브랜치에 누적합니다. 교육 참여자 ID 원문은 저장하지 않고 프로젝트별 가명키로 바꿉니다. 저장·사후 연결에는 별도로 전달받은 기획검증 접속코드가 필요하며, 연결하지 않거나 코드가 맞지 않으면 현재 브라우저 세션과 기준파일(JSON) 방식으로 동작합니다.",
    icon="i",
    tone="warn",
)

callout(
    "관리자 대시보드의 실제 데이터 범위",
    "GitHub 테스트 저장소가 연결되면 저장된 합성 프로젝트·참여자의 완료 결과를 누적 집계합니다. 미연결 또는 조회 실패 때에는 현재 브라우저 세션의 프로젝트 0~1개와 참여자 0~1명만 표시합니다. GitHub 저장은 자체 서버 DB를 대신하는 운영 기능이 아닙니다.",
    icon="i",
)

callout(
    "다른 브라우저에서 실제 검사 시작",
    "참여자는 왼쪽 메뉴에서 ‘교육 전 검사’ 또는 ‘교육 후 검사’를 먼저 선택합니다. GitHub 테스트 저장소가 연결되면 교육담당자가 전달한 프로젝트 코드를 선택한 검사 화면에 입력해 동일 문항·일정·버전을 불러올 수 있습니다. 교육 전·후 완료 결과만 저장되며 문항을 넘길 때마다 저장되지는 않습니다. 미연결 때에는 동일 브라우저에서 시작하거나 기준파일(JSON)로 교육 후 검사를 이어갑니다.",
    icon="!",
    tone="warn",
)

st.markdown("### GitHub 테스트 저장소 연결 시 진행 순서")
st.markdown(
    """
    <div class="tap-guide-grid">
      <div class="tap-guide-step"><span>1</span><b>프로젝트 게시</b><small>교육담당자가 기획검증 접속코드를 입력하고 프로젝트를 저장한 뒤 생성된 프로젝트 코드를 전달합니다.</small></div>
      <div class="tap-guide-step"><span>2</span><b>검사 메뉴 선택</b><small>참여자가 ‘교육 전 검사’ 또는 ‘교육 후 검사’를 선택한 뒤 프로젝트 코드와 기획검증 접속코드를 입력합니다.</small></div>
      <div class="tap-guide-step"><span>3</span><b>완료 결과 누적</b><small>교육 전·후 각 검사를 모두 완료한 시점에만 가명 결과 스냅샷을 저장합니다.</small></div>
      <div class="tap-guide-step"><span>4</span><b>대시보드·리포트</b><small>누적 완료현황을 새로고침하고 역량별 짝지은 N≥5 결과를 확인합니다.</small></div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("### 브라우저가 바뀌면 기준파일로 교육 후 검사를 이어갑니다")
st.markdown(
    """
    <div class="tap-guide-grid">
      <div class="tap-guide-step"><span>1</span><b>사전검사 완료</b><small>사전검사를 끝내고 개인 리포트로 이동합니다.</small></div>
      <div class="tap-guide-step"><span>2</span><b>기준파일 저장</b><small>개인 리포트에서 ‘교육 전 검사 기준파일 저장’을 누릅니다.</small></div>
      <div class="tap-guide-step"><span>3</span><b>8~10주 개인 보관</b><small>교육 후 검사 전까지 본인만 접근할 수 있는 위치에 안전하게 보관합니다.</small></div>
      <div class="tap-guide-step"><span>4</span><b>교육 후 검사 이어하기</b><small>왼쪽 ‘교육 후 검사’를 열고 ‘교육 전 검사 기준파일(JSON)’을 선택하면 프로젝트·ID·사전응답이 자동 복원됩니다. 검사를 완료한 뒤 비교 리포트를 확인합니다.</small></div>
    </div>
    """,
    unsafe_allow_html=True,
)

callout(
    "기준파일과 결과 JSON은 서로 다른 파일",
    "기준파일(tap_pre_baseline_…json)은 교육 후 검사를 잇기 위한 파일이며 서버 원본이나 전체 백업이 아닙니다. 이름·사번 대신 가명 교육 참여자 ID를 사용하고, 문항별 응답이 포함되므로 본인만 보관하세요.",
    icon="!",
    tone="warn",
)

callout(
    "비교가 성립하는 세 가지 조건",
    "사전·사후에 동일한 교육 참여자 ID, 동일한 문항·척도·버전, 동일한 최근 8주 회상기간을 사용하세요. 한 시점의 ‘수행 기회 없음’은 0점이 아니라 비교 제외입니다.",
    icon="✓",
)

callout(
    "조직 결과 공개 기준",
    "조직 리포트는 역량별로 교육 전·후가 모두 유효한 짝지은 참여자 N≥5일 때만 평균과 변화량을 공개합니다. GitHub 합성 기획검증 프로젝트의 N<5 결과는 리포트 미리보기 코드와 화면 전용 미리보기 확인을 거친 경우에만 볼 수 있으며 다운로드·인쇄할 수 없습니다. 이 기준은 개인정보 보호를 위한 최소값이며 통계적 안정성이나 교육의 인과효과를 보장하지 않습니다.",
    icon="5+",
)

callout(
    "결과 표현 원칙",
    "비교집단이 없는 자기보고식 사전·사후 검사는 교육의 인과효과가 아니라 ‘교육 전후 관찰된 변화’를 보여줍니다. 최근 8주 회상기간과 맞추기 위해 행동 사후검사는 교육 8~10주 후를 권장합니다.",
    icon="i",
    tone="warn",
)

company_tab, participant_tab, kma_tab = st.tabs(["교육담당자", "참여자", "KMA 관리자"])

with company_tab:
    st.markdown("#### 교육담당자는 교육 일정에서 짝지은 변화 리포트까지 운영합니다")
    st.markdown(
        """
        1. 사이드바 **역할 전환**에서 `교육담당자`를 선택합니다.
        2. **교육평가 프로젝트**에서 교육명·교육일·사전/사후 검사기간과 측정역량을 정하고 저장합니다.
        3. GitHub 테스트 저장소가 연결된 경우 **기획검증 접속코드**를 입력해 프로젝트를 게시하고, 화면의 **프로젝트 코드**와 접속코드를 참여자에게 별도로 전달합니다. 미연결이면 동일 브라우저 세션에서 검사를 시작합니다.
        4. 참여자별로 추측하기 어려운 무작위 가명 교육 참여자 ID를 배정하고 왼쪽 메뉴의 **교육 전 검사 → 교육·현업 적용 → 교육 후 검사** 순서로 안내합니다.
        5. 사전·사후에는 동일한 문항·척도·버전을 유지하고, 행동 사후검사는 최근 8주 회상기간과 맞춰 기본 8~10주 후에 엽니다.
        6. **관리자 대시보드**에서 GitHub에 누적된 합성 프로젝트·교육 전·후 완료 상태를 새로고침해 확인합니다.
        7. **교육 전후 리포트**에서 먼저 실시 프로젝트를 선택합니다. 프로젝트명·코드·교육 전/후 완료 인원을 확인한 뒤 해당 프로젝트 리포트를 바로 엽니다.
        8. 교육 전·후 비교는 최대 8개 역량의 레이더 그래프와 상세표로 확인합니다. 선택 역량이 8개를 넘으면 그래프에 표시할 3~8개를 고릅니다. 별도 파일 비교가 필요할 때만 하단 **CSV 파일로 직접 비교하기**를 펼쳐 업로드합니다.
        9. GitHub 합성 기획검증 프로젝트가 N<5이면 **리포트 미리보기 코드**를 확인하고 **소표본 실제값을 화면에서만 미리보기**를 켤 수 있습니다. 이 화면은 기획검증용이며 다운로드·인쇄·외부 공유 대상이 아닙니다.
        10. 역량별 짝지은 유효 참여자 N≥5 결과에서 변화와 수행기회·전이 장애요인을 확인하고 `인쇄용 리포트 HTML`을 내려받습니다.
        """
    )
    col_a, col_b = st.columns(2)
    if col_a.button("프로젝트 설정 열기", type="primary", width="stretch"):
        switch_role_page("company", "pages/1_project_setup.py")
    if col_b.button("조직 리포트 열기", width="stretch"):
        switch_role_page("company", "pages/4_organization_report.py")

with participant_tab:
    st.markdown("#### 참여자는 사전·사후에 같은 기준으로 응답하고 본인 변화만 확인합니다")
    st.markdown(
        """
        1. 사이드바 **역할 전환**에서 `참여자`를 선택합니다.
        2. 왼쪽 **교육 전 검사**를 선택합니다. GitHub 테스트 저장소가 연결된 경우 교육담당자에게 받은 **프로젝트 코드**와 **기획검증 접속코드**를 입력해 검사도구를 불러옵니다. 미연결이면 프로젝트를 만든 동일 브라우저에서 시작합니다.
        3. 교육담당자가 무작위로 배정한 가명 **교육 참여자 ID**를 입력합니다. 이름·사번은 사용하지 않습니다. ID가 없을 때도 문항은 보이지만 응답 저장·다음 문항 이동·검사 완료는 할 수 없습니다.
        4. 최근 8주에 해당 행동을 얼마나 자주 했는지 1~5점으로 답합니다. 그 행동을 할 기회가 없었다면 **수행 기회 없음**을 고릅니다. 미응답·0점과는 다릅니다.
        5. 교육 전 검사 완료 후 개인 리포트에서 **교육 전 검사 기준파일**을 내려받아 본인만 접근할 수 있는 위치에 보관합니다.
        6. 교육 8~10주 후 왼쪽 **교육 후 검사**를 선택합니다. GitHub에 교육 전 결과가 저장됐다면 같은 프로젝트 코드·접속코드·교육 참여자 ID로 연결합니다.
        7. GitHub 연결을 사용하지 않거나 브라우저 세션이 달라졌다면 `교육 전 검사 기준파일(JSON)`을 선택해 프로젝트·ID·교육 전 응답을 복원합니다.
        8. 교육 후 검사에서는 같은 문항과 함께 교육내용 적용 기회, 상사지원, 도구·권한, 장애요인에도 답합니다.
        9. 개인결과 공유 동의 체크박스는 의사 표시일 뿐 자동 전송 기능이 아닙니다. 조직 집계가 필요하면 **결과 CSV**를 정해진 안전한 방법으로 교육담당자에게 전달합니다.
        10. 결과는 규준·백분위·개인순위가 아니라 본인의 교육 전·후 관찰 변화입니다.
        """
    )
    pre_col, post_col = st.columns(2)
    if pre_col.button("교육 전 검사 시작", key="guide_pre_assessment", type="primary", width="stretch"):
        switch_role_page("participant", "pages/7_pre_assessment.py")
    if post_col.button("교육 후 검사 시작", key="guide_post_assessment", width="stretch"):
        switch_role_page("participant", "pages/8_post_assessment.py")

with kma_tab:
    st.markdown("#### KMA 관리자는 버전·검증상태·과정 매핑을 관리합니다")
    st.markdown(
        """
        1. 사이드바 **역할 전환**에서 `KMA 관리자`를 선택합니다.
        2. **KMA 대시보드**에서 문항은행과 역량체계의 검증상태를 확인합니다.
        3. **문항은행·검수**에서 운영 문항과 비활성 문항의 근거를 추적합니다.
        4. 한 프로젝트의 사전·사후 사이에는 문항 문구·코드·척도·회상기간과 버전을 변경하지 않습니다.
        5. 파일럿 후보 문항은 전문가 검토와 인지면접 전까지 프로젝트에 사용하지 않습니다.
        6. 회원사의 개인응답과 조직점수는 기본 열람범위에 포함하지 않습니다.
        """
    )
    if st.button("문항은행 검수 열기", key="guide_question_bank", type="primary", width="stretch"):
        switch_role_page("kma", "pages/5_question_bank.py")

guide_path = Path(PROJECT_ROOT) / "docs" / "TAP_사용설명서_v3.pdf"
if guide_path.exists():
    st.divider()
    st.download_button(
        "사용설명서 내려받기",
        guide_path.read_bytes(),
        guide_path.name,
        "application/pdf",
        width="stretch",
    )
