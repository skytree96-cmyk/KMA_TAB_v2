from __future__ import annotations

from pathlib import Path

import streamlit as st

from tap.runtime_guard import source_fingerprint


__tap_source_sha256__ = source_fingerprint(__file__)


OPEN_PAGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "TAP_오픈페이지_와이어프레임_v1.html"
)


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


def render_open_page() -> None:
    """Render the trusted, self-contained public landing page."""

    if not OPEN_PAGE_PATH.is_file():
        st.error("오픈페이지 파일을 찾지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return
    st.markdown(PUBLIC_PAGE_CSS, unsafe_allow_html=True)
    # Render in the app document instead of a sandboxed iframe. Streamlit's iframe
    # blocks top-level navigation, which makes landing-page links appear inert.
    st.html(OPEN_PAGE_PATH, width="stretch", unsafe_allow_javascript=True)
