"""Deployment-owned mode selection; browser query parameters never select a mode."""
from __future__ import annotations

import os


def production_mode() -> bool:
    return os.environ.get("TAP_APP_MODE", "production").strip().lower() != "demo"


def guard_legacy_page() -> None:
    """Block every legacy/demo entry point on the account deployment."""
    if production_mode():
        import streamlit as st

        st.info("로그인 후 배정된 화면에서 이용해 주세요.")
        st.markdown("[로그인 화면으로 이동](/)")
        st.stop()
