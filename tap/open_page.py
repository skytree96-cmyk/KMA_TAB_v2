from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

from tap.runtime_guard import source_fingerprint


__tap_source_sha256__ = source_fingerprint(__file__)


OPEN_PAGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "TAP_오픈페이지_와이어프레임_v1.html"
)
GUIDE_PDF_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "TAP_사용설명서_v3.pdf"
)
GUIDE_PDF_BASE64_TOKEN = "__TAP_GUIDE_PDF_BASE64__"


PUBLIC_PAGE_CSS = """
<style>
  [data-testid="stSidebar"],
  [data-testid="stHeader"],
  [data-testid="stToolbar"],
  [data-testid="stFooter"],
  #MainMenu,
  [data-testid="stDecoration"] { display: none !important; }

  html, body, .stApp,
  [data-testid="stAppViewContainer"],
  [data-testid="stMain"] { margin: 0 !important; background: #ffffff !important; }

  [data-testid="stMainBlockContainer"] {
    width: 100% !important;
    max-width: none !important;
    padding: 0 !important;
  }

  [data-testid="stHtml"] {
    display: block !important;
    width: 100% !important;
  }
</style>
"""


@lru_cache(maxsize=1)
def _rendered_open_page_html() -> str:
    """Return the landing page with one in-memory PDF download payload."""

    source = OPEN_PAGE_PATH.read_text(encoding="utf-8")
    if source.count(GUIDE_PDF_BASE64_TOKEN) != 1:
        raise ValueError("사용설명서 다운로드 토큰은 오픈페이지에 정확히 1개여야 합니다.")
    encoded_guide = base64.b64encode(GUIDE_PDF_PATH.read_bytes()).decode("ascii")
    return source.replace(GUIDE_PDF_BASE64_TOKEN, encoded_guide, 1)


def render_open_page() -> None:
    """Render the trusted, self-contained public landing page."""

    if not OPEN_PAGE_PATH.is_file() or not GUIDE_PDF_PATH.is_file():
        st.error("오픈페이지 파일을 찾지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return
    try:
        page_html = _rendered_open_page_html()
    except (OSError, ValueError):
        st.error("오픈페이지 또는 사용설명서를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return
    st.markdown(PUBLIC_PAGE_CSS, unsafe_allow_html=True)
    # Render in the app document instead of a sandboxed iframe. Streamlit's iframe
    # blocks top-level navigation, which makes landing-page links appear inert.
    st.html(page_html, width="stretch", unsafe_allow_javascript=True)
