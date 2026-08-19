from __future__ import annotations

import streamlit as st

from tap.runtime_guard import stop_on_stale


st.set_page_config(
    page_title="KMA TAP | 교육 전·후 업무행동 변화점검",
    page_icon="T",
    layout="wide",
    initial_sidebar_state="collapsed",
)

stop_on_stale(st, ("tap.open_page",))

from tap.open_page import render_open_page


render_open_page()
