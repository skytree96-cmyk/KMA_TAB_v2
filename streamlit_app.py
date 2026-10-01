from __future__ import annotations

from pathlib import Path

import streamlit as st

from tap.runtime_guard import stop_on_stale
from tap.account_mode import production_mode


st.set_page_config(
    page_title="KMA TAP",
    page_icon=Path(__file__).resolve().parent / "assets" / "kmatap-favicon.png",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if production_mode():
    from tap.account_portal import render_portal, TOKEN_KEY
    from tap.account_landing import render_account_landing
    from tap.account_guide import render_account_guide

    # Explicit navigation disables discovery of the legacy demo pages.
    def account_home():
        if st.session_state.get(TOKEN_KEY):
            render_portal()
        else:
            render_account_landing()

    from tap.account_navigation import register_pages
    from tap.session_cookie import restore_session, sync_cookie

    restore_session(TOKEN_KEY)
    sync_cookie(TOKEN_KEY)

    home = st.Page(account_home, title="KMA TAP", default=True)
    guide = st.Page(render_account_guide, title="이용 안내 · KMA TAP", url_path="guide")
    register_pages(home=home, guide=guide)
    st.navigation([
        home,
        st.Page(render_portal, title="로그인 · KMA TAP", url_path="login"),
        guide,
        # Public service introduction (formerly the Cloudflare open page); always
        # shows the landing page, even for a signed-in session.
        st.Page(render_account_landing, title="서비스 소개 · KMA TAP", url_path="open"),
    ], position="hidden").run()
    st.stop()

stop_on_stale(st, ("tap.open_page",))

from tap.open_page import render_open_page


render_open_page()
