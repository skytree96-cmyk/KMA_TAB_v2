"""Authenticated workspace navigation; the server principal defines every menu."""
from __future__ import annotations

from typing import Any, Callable, Mapping

import streamlit as st

from tap.brand import brand_html


SECTION_KEY = "_tap_workspace_section"
ACCOUNT_MENU_KEY = "_tap_account_menu"
PROFILE_KEY = "_tap_profile_popover"
ROLE_LABELS = {"kma": "KMA 관리자", "company": "교육담당자", "participant": "참여자"}
MENUS = {
    "kma": (
        ("dashboard", "대시보드", ":material/dashboard:"),
        ("companies", "회원사", ":material/apartment:"),
        ("accounts", "계정 관리", ":material/group:"),
        ("projects", "프로젝트", ":material/folder_open:"),
        ("question_bank", "문항은행·검수", ":material/library_books:"),
    ),
    "company": (
        ("dashboard", "대시보드", ":material/dashboard:"),
        ("projects", "프로젝트", ":material/folder_open:"),
        ("create_project", "프로젝트 만들기", ":material/add_circle:"),
        ("accounts", "참여자 계정", ":material/group:"),
    ),
    "participant": (("assessments", "내 교육", ":material/assignment:"),),
}


def _go_to_section(section: str) -> None:
    st.session_state[SECTION_KEY] = section
    st.session_state[ACCOUNT_MENU_KEY] = "업무 화면"
    st.session_state[PROFILE_KEY] = False


def _go_to_password() -> None:
    st.session_state[ACCOUNT_MENU_KEY] = "비밀번호 변경"
    st.session_state[PROFILE_KEY] = False


def render_workspace_header(principal: Mapping[str, Any], logout: Callable[[], None]) -> str:
    """Return an allowed section; menu events never supply a role or company."""
    role = str(principal["role"])
    menus = MENUS[role]
    allowed = {item[0] for item in menus}
    default = "assessments" if role == "participant" else "projects"
    if st.session_state.get(SECTION_KEY) not in allowed:
        st.session_state[SECTION_KEY] = default
    if st.session_state.get(ACCOUNT_MENU_KEY) not in {"업무 화면", "비밀번호 변경"}:
        st.session_state[ACCOUNT_MENU_KEY] = "업무 화면"
    section = st.session_state[SECTION_KEY]
    required = bool(principal.get("must_change_password"))

    with st.container(key="tap_workspace_topbar"):
        brand, navigation, profile = st.columns([1.2, 4, 1.3], gap="small", vertical_alignment="center")
        with brand, st.container(key="tap_workspace_brand"):
            st.html(brand_html(compact=True))
        with navigation, st.container(key="tap_workspace_nav"):
            columns = st.columns(len(menus), gap="small")
            for column, (value, label, icon) in zip(columns, menus):
                with column:
                    active = value == section and st.session_state[ACCOUNT_MENU_KEY] == "업무 화면" and not required
                    st.button(label, key="_tap_nav_" + value, icon=icon, width="stretch",
                              type="primary" if active else "tertiary", disabled=required,
                              on_click=_go_to_section, args=(value,))
        with profile, st.container(key="tap_workspace_profile"):
            with st.popover(ROLE_LABELS[role], icon=":material/account_circle:", type="tertiary",
                            width="stretch", key=PROFILE_KEY, on_change="rerun"):
                st.text(str(principal.get("display_name") or ROLE_LABELS[role]))
                st.caption(str(principal["login_id"]))
                if principal.get("company_name"):
                    st.text(str(principal["company_name"]))
                if not required:
                    st.button("비밀번호 변경", key="_tap_account_password_nav", icon=":material/lock:",
                              width="stretch", type="tertiary", on_click=_go_to_password)
                if st.button("로그아웃", key="_tap_logout", icon=":material/logout:", width="stretch", type="tertiary"):
                    logout()
    return section


def section_label(role: str, section: str) -> str:
    return next(label for value, label, _ in MENUS[role] if value == section)
