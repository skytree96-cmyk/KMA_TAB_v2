"""Account-based public landing page (/open): the v3 service introduction."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

import streamlit as st

from tap.brand import brand_css, brand_html
from tap.open_page import PUBLIC_PAGE_CSS


# Production copy lives in its own file (v3: tabs for reports, heatmap and assessment). The legacy demo page
# (tap.open_page.OPEN_PAGE_PATH) stays as it is for demo mode and Cloudflare.
LANDING_PATH = Path(__file__).resolve().parents[1] / "docs" / "TAP_오픈페이지_v3.html"

LANDING_SHELL_CSS = """
<style>
  html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"] {background:#ffffff !important;}
</style>
"""

_BRAND_SLOTS = {
    "HEADER": lambda: brand_html(compact=True),
    "FOOTER": lambda: brand_html(compact=True, variant="reverse"),
}


@lru_cache(maxsize=1)
def account_landing_html() -> str:
    """Fill the wordmark slots and embed the bundled brand font."""
    source = LANDING_PATH.read_text(encoding="utf-8")
    for slot, render in _BRAND_SLOTS.items():
        source, count = re.subn(
            rf"<!-- TAP:BRAND_{slot} -->.*?<!-- /TAP:BRAND_{slot} -->", lambda _: render(), source, count=1, flags=re.DOTALL,
        )
        if count != 1:
            raise ValueError("Landing brand structure has changed")
    if source.count("</head>") != 1:
        raise ValueError("Landing head structure has changed")
    return source.replace("</head>", brand_css() + "</head>", 1)


def render_account_landing() -> None:
    try:
        page_html = account_landing_html()
    except (OSError, ValueError):
        st.error("서비스 안내를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return
    st.markdown(PUBLIC_PAGE_CSS + LANDING_SHELL_CSS, unsafe_allow_html=True)
    st.html(page_html, width="stretch", unsafe_allow_javascript=True)
