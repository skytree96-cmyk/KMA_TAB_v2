"""Account-based public landing page, preserving the original presentation."""
from __future__ import annotations

from functools import lru_cache
import re

import streamlit as st

from tap.brand import brand_css, brand_html
from tap.open_page import GUIDE_PDF_BASE64_TOKEN, OPEN_PAGE_PATH, PUBLIC_PAGE_CSS


LANDING_BRAND_CSS = """
<style>
  html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"] {background:var(--paper,#f8fbff) !important;}
  .site-header .brand {text-decoration:none;flex-shrink:0;}
  .site-header .tap-ci {flex-direction:row;align-items:center;gap:13px;margin:0;flex-wrap:nowrap;}
  .site-header .tap-ci .tap-ci-wordmark {font-size:32px;}
  .site-header .tap-ci .tap-ci-description {font-size:9px !important;line-height:1.6 !important;}
  .footer-brand .tap-ci {margin:0;gap:10px;}
  .footer-brand .tap-ci .tap-ci-wordmark {font-size:34px;}
  @media(max-width:1150px) {.site-header .tap-ci .tap-ci-description {display:none;}}
  @media(max-width:640px) {.site-header .tap-ci .tap-ci-wordmark {font-size:29px;}}
  @media(prefers-color-scheme:dark) {.site-header .tap-ci {--ci-kma:#e7f6f3;--ci-tap:#7dded0;--ci-caption:#b9cfd0;}}
</style>
"""


@lru_cache(maxsize=1)
def account_landing_html() -> str:
    """Render production copy without mutating the legacy HTML or bundled PDF."""
    source = OPEN_PAGE_PATH.read_text(encoding="utf-8")
    source = source.replace(GUIDE_PDF_BASE64_TOKEN, "")
    source = source.replace(' data-guide-download href="/tap-user-guide.pdf"', ' href="/guide"')
    source = source.replace(' download="TAP_사용설명서_v3.pdf"', "")
    source, notices = re.subn(r'\s*<div class="notice" role="note">.*?</div>', "", source, count=1, flags=re.DOTALL)
    if notices != 1:
        raise ValueError("Landing notice structure has changed")

    def login_link(match: re.Match[str]) -> str:
        return re.sub(r'href="[^"]*"', 'href="/login"', match.group(0), count=1)

    source, links = re.subn(r'<a\b(?=[^>]*\bdata-app-link\b)[^>]*>', login_link, source)
    if links != 8:
        raise ValueError("Landing account link count has changed")

    replacements = {
        "프로젝트 코드로 검사 참여": "로그인하고 검사 참여",
        "합성 데이터 기반": "서비스 소개용 예시",
        "합성 예시 데이터": "리포트 예시",
        "합성 예시": "예시 데이터",
        "합성 샘플 리포트를 먼저 보거나 교육 전/후 검사 단계로 이동할 수 있습니다.": "리포트 예시를 먼저 확인하거나 로그인하여 배정된 교육 전/후 검사를 진행할 수 있습니다.",
        "원문 ID 미저장": "계정별 접근 관리",
        "프로젝트별 가명 연결": "배정된 프로젝트에서 검사 진행",
        "같은 ID와 같은 문항으로": "같은 계정과 같은 문항으로",
        "동일 문항과 동일 참여자 ID로 다시 측정": "같은 계정에서 동일 문항으로 다시 측정",
        "목적에 맞는 화면으로 바로 이동할 수 있습니다.": "발급받은 계정으로 로그인하면 담당 역할에 맞는 화면이 열립니다.",
        "평가도구와 문항, 교육과정 매핑의 품질을 관리합니다.": "회원사와 교육담당자 계정을 관리하고 프로젝트 운영 현황을 확인합니다.",
        "기획검증 프로젝트 현황": "회원사·교육담당자 계정 관리",
        "문항은행 및 검수 근거": "프로젝트 운영 현황 확인",
        "역량·교육과정 매핑 확인": "회사별 결과 집계 확인",
        "교육 전/후에 같은 ID를 사용하는 이유는 무엇인가요?": "교육 전/후에 같은 계정을 사용하는 이유는 무엇인가요?",
        "동일 참여자의 결과를 연결하기 위해서입니다. 실명이나 사번 대신 기관에서 정한 가명 교육 참여자 ID를 사용해야 합니다.": "동일 참여자의 교육 전/후 결과를 연결하기 위해서입니다. 교육담당자가 발급한 아이디로 로그인한 뒤, 본인에게 배정된 프로젝트에서 검사를 진행해 주세요.",
        "승인된 기업 범위의 프로젝트 설정과 검사 완료 결과만 기획검증용 저장소에 보관합니다. 사업자등록번호 원문, 참여자 원문 ID, 입력 중인 응답은 저장하지 않습니다.": "회사별 프로젝트와 검사 결과를 구분하여 저장합니다. 참여자는 본인에게 배정된 검사를 진행하고, 교육담당자는 담당 회사의 운영 현황과 공개 기준을 충족한 조직 리포트를 확인합니다.",
        "demo-badge": "preview-badge",
    }
    for old, new in replacements.items():
        source = source.replace(old, new)

    source, headers = re.subn(
        r'<a class="brand" href="#top" aria-label="KMA TAP 첫 화면으로 이동">.*?</a>',
        '<a class="brand" href="#top" aria-label="KMA TAP 첫 화면으로 이동">' + brand_html(compact=True) + '</a>',
        source, count=1, flags=re.DOTALL,
    )
    source, footers = re.subn(
        r'<div class="footer-brand">.*?</div>',
        '<div class="footer-brand">' + brand_html(compact=True, variant="reverse") + '</div>',
        source, count=1, flags=re.DOTALL,
    )
    source, notes = re.subn(r'<p class="footer-note">.*?</p>', '<p class="footer-note">© KMA TAP. 교육 전·후 변화 평가 플랫폼.</p>', source, count=1, flags=re.DOTALL)
    if (headers, footers, notes) != (1, 1, 1):
        raise ValueError("Landing brand structure has changed")
    return source.replace("</head>", brand_css() + LANDING_BRAND_CSS + "</head>", 1)


def render_account_landing() -> None:
    try:
        page_html = account_landing_html()
    except (OSError, ValueError):
        st.error("서비스 안내를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return
    st.markdown(PUBLIC_PAGE_CSS, unsafe_allow_html=True)
    st.html(page_html, width="stretch", unsafe_allow_javascript=True)
