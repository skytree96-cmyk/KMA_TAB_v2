from __future__ import annotations

from pathlib import Path

import streamlit as st

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
    "공개 데모의 저장 범위",
    "프로젝트와 응답은 현재 브라우저 세션에만 임시 저장됩니다. 실제 개인정보·응답·기밀자료는 입력하거나 업로드하지 마세요.",
    icon="i",
    tone="warn",
)

callout(
    "비교가 성립하는 세 가지 조건",
    "사전·사후에 동일한 참여자 익명 ID, 동일한 문항·척도·버전, 동일한 최근 8주 회상기간을 사용하세요. 한 시점의 ‘수행 기회 없음’은 0점이 아니라 비교 제외입니다.",
    icon="✓",
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
        2. **교육평가 프로젝트**에서 교육명·교육일·사전/사후 검사기간과 측정역량을 정합니다.
        3. 참여자에게 같은 익명 ID를 배정하고 **사전검사 → 교육·현업 적용 → 사후검사** 순서로 안내합니다.
        4. 사전·사후에는 동일한 문항·척도·버전을 유지하고, 행동 사후검사는 최근 8주 회상기간과 맞춰 기본 8~10주 후에 엽니다.
        5. **교육 전후 리포트**에서 짝지어진 인원, 역량별 변화, 수행기회·전이 장애요인을 확인합니다.
        6. `인쇄용 리포트 HTML`을 내려받아 브라우저에서 **인쇄 → PDF 저장**을 선택합니다.
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
        2. 화면의 검사단계가 `사전검사`인지 `사후검사`인지 먼저 확인합니다.
        3. 두 검사 모두 최근 8주에 해당 행동을 얼마나 자주 했는지 1~5점으로 답합니다.
        4. 그 행동을 할 기회가 없었다면 **수행 기회 없음**을 고릅니다. 미응답·0점과는 다릅니다.
        5. 사후검사에서는 교육내용을 적용할 기회, 상사지원, 도구·권한, 장애요인도 함께 답합니다.
        6. 결과는 규준·백분위·개인순위가 아니라 본인의 사전·사후 관찰 변화입니다.
        """
    )
    if st.button("사전·사후 검사 화면 열기", key="guide_assessment", type="primary", width="stretch"):
        switch_role_page("participant", "pages/2_assessment.py")

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
