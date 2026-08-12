from __future__ import annotations

from pathlib import Path

import streamlit as st

from tap.config import PROJECT_ROOT
from tap.ui import callout, page_header, setup_page, switch_role_page


setup_page("처음 사용 안내", "?")
page_header(
    "처음 사용 안내",
    "TAP은 네 단계만 기억하면 됩니다",
    "프로젝트를 정하고, 최근 행동에 응답하고, 결과의 맥락을 확인한 뒤, 교육 또는 조직개선으로 연결합니다.",
    badge="약 2분 안내",
)

st.markdown(
    """
    <div class="tap-guide-grid">
      <div class="tap-guide-step"><span>1</span><b>프로젝트 설정</b><small>대상·기간·측정역량·임시 목표를 정합니다.</small></div>
      <div class="tap-guide-step"><span>2</span><b>행동 응답</b><small>최근 8주를 떠올려 문항을 한 개씩 응답합니다.</small></div>
      <div class="tap-guide-step"><span>3</span><b>결과 확인</b><small>점수 순위가 아니라 상대적 패턴과 수행 맥락을 봅니다.</small></div>
      <div class="tap-guide-step"><span>4</span><b>다음 행동 결정</b><small>교육으로 해결할지, 권한·도구·프로세스를 바꿀지 정합니다.</small></div>
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

company_tab, participant_tab, kma_tab = st.tabs(["교육담당자", "참여자", "KMA 관리자"])

with company_tab:
    st.markdown("#### 교육담당자는 프로젝트에서 조직 리포트까지 봅니다")
    st.markdown(
        """
        1. 사이드바 **역할 전환**에서 `교육담당자`를 선택합니다.
        2. **진단 프로젝트**에서 대상과 기간을 정하고, 기본역량을 확인한 뒤 선택역량을 고릅니다.
        3. **설정 저장 후 참여자 화면 확인**을 눌러 실제 응답 흐름을 점검합니다.
        4. **조직 리포트**에서 예시 결과를 보거나, `CSV 양식 내려받기`로 만든 익명 집계파일을 올립니다.
        5. `인쇄용 리포트 HTML`을 내려받아 브라우저에서 **인쇄 → PDF 저장**을 선택합니다.
        """
    )
    col_a, col_b = st.columns(2)
    if col_a.button("프로젝트 설정 열기", type="primary", width="stretch"):
        switch_role_page("company", "pages/1_project_setup.py")
    if col_b.button("조직 리포트 열기", width="stretch"):
        switch_role_page("company", "pages/4_organization_report.py")

with participant_tab:
    st.markdown("#### 참여자는 최근 행동에 응답하고 본인 결과만 확인합니다")
    st.markdown(
        """
        1. 사이드바 **역할 전환**에서 `참여자`를 선택합니다.
        2. 최근 8주에 해당 행동을 얼마나 자주 했는지 1~5점으로 답합니다.
        3. 그 행동을 할 기회가 없었다면 **수행 기회 없음**을 고릅니다. 미응답과는 다르게 처리됩니다.
        4. **저장하고 다음**을 누르고 마지막 문항에서 **결과 보기**를 선택합니다.
        5. 결과는 규준·백분위·개인순위가 아닙니다. 실제 업무환경과 수행기회를 함께 해석합니다.
        """
    )
    if st.button("진단 참여 화면 열기", key="guide_assessment", type="primary", width="stretch"):
        switch_role_page("participant", "pages/2_assessment.py")

with kma_tab:
    st.markdown("#### KMA 관리자는 버전·검증상태·과정 매핑을 관리합니다")
    st.markdown(
        """
        1. 사이드바 **역할 전환**에서 `KMA 관리자`를 선택합니다.
        2. **KMA 대시보드**에서 문항은행과 역량체계의 검증상태를 확인합니다.
        3. **문항은행·검수**에서 운영 문항과 비활성 문항의 근거를 추적합니다.
        4. 파일럿 후보 문항은 전문가 검토와 인지면접 전까지 프로젝트에 사용하지 않습니다.
        5. 회원사의 개인응답과 조직점수는 기본 열람범위에 포함하지 않습니다.
        """
    )
    if st.button("문항은행 검수 열기", key="guide_question_bank", type="primary", width="stretch"):
        switch_role_page("kma", "pages/5_question_bank.py")

guide_path = Path(PROJECT_ROOT) / "docs" / "TAP_빠른사용가이드_v3.pptx"
if guide_path.exists():
    st.divider()
    st.download_button(
        "PPT 빠른 사용 가이드 내려받기",
        guide_path.read_bytes(),
        guide_path.name,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        width="stretch",
    )
