"""Account portal: one authenticated router, with no role supplied by the browser."""
from __future__ import annotations

import os

import streamlit as st

from tap.account_store import AccountError, AccountStore
from tap.brand import brand_css, brand_html
from tap.account_theme import account_theme_css, workspace_theme_css
from tap.account_navigation import (
    ACCOUNT_MENU_KEY, PASSWORD_ROUTE, ROUTE_KEY, enter_route, follow_route,
    render_workspace_header, section_label,
)


TOKEN_KEY = "_tap_account_session"
ROLE_LABELS = {"kma": "KMA 관리자", "company": "교육담당자", "participant": "참여자"}

PORTAL_CSS = account_theme_css()


@st.cache_resource(show_spinner=False)
def _configured_store(dsn: str, bootstrap_login: str, bootstrap_hash: str) -> AccountStore:
    store = AccountStore(dsn)
    store.initialize()
    if bootstrap_hash:
        store.bootstrap_admin(bootstrap_login, bootstrap_hash)
    return store


def clear_identity() -> None:
    # Includes old demo responses, participant widgets and newly issued passwords.
    from tap.session_cookie import forget_restored_cookie

    st.session_state.clear()
    st.query_params.clear()
    forget_restored_cookie()


def _notice() -> None:
    message = st.session_state.pop("_tap_account_notice", "")
    if message:
        st.success(message)


def _login(store: AccountStore | None) -> None:
    login_slot = st.empty()
    with login_slot.container():
        with st.container(key="tap_login_shell"):
            # Single centered card with the wordmark on top, as in the PAI sign-in screen.
            with st.container(border=True, key="tap_login_card"):
                st.html('<div class="tap-login-brand">' + brand_html(compact=True) + '<span>교육 전·후<br>변화 평가 플랫폼</span></div>')
                st.title("로그인")
                st.caption("발급받은 ID로 로그인하면 내 교육과 관리 화면이 열립니다.")
                with st.form("_tap_login_form", clear_on_submit=True, border=False):
                    login_id = st.text_input("로그인 ID", max_chars=64, placeholder="발급받은 로그인 ID", disabled=store is None)
                    password = st.text_input("비밀번호", type="password", max_chars=128, disabled=store is None)
                    submitted = st.form_submit_button("로그인", type="primary", use_container_width=True, disabled=store is None)
                if store is None:
                    st.info("계정 서비스 연결을 준비하고 있습니다. 설정이 완료되면 로그인할 수 있습니다.")
                if submitted and store is not None:
                    try:
                        token = store.login(login_id, password)
                    except AccountError as exc:
                        st.error(str(exc))
                    except Exception:
                        st.error("로그인을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.")
                    else:
                        clear_identity()
                        st.session_state[TOKEN_KEY] = token
                        login_slot.empty()
                        st.rerun()
                st.html('<div class="tap-login-foot">참여자 계정·비밀번호 문의는 교육담당자에게, 교육담당자 계정 문의는 KMA 관리자에게 요청해 주세요.'
                        '<a href="/open" target="_self">서비스 소개</a></div>')


def _password_change(store: AccountStore, token: str, required: bool) -> None:
    st.subheader("처음 사용할 비밀번호 설정" if required else "비밀번호 변경")
    st.caption("3~128자로 설정해 주세요. 담당자는 기존 비밀번호를 조회할 수 없습니다.")
    with st.form("_tap_change_password", clear_on_submit=True):
        old = st.text_input("현재 비밀번호", type="password", max_chars=128)
        new = st.text_input("새 비밀번호", type="password", max_chars=128)
        confirm = st.text_input("새 비밀번호 확인", type="password", max_chars=128)
        submitted = st.form_submit_button("비밀번호 저장", type="primary")
    if submitted:
        if new != confirm:
            st.error("새 비밀번호가 서로 다릅니다.")
            return
        try:
            next_token = store.change_password(token, old, new)
        except AccountError as exc:
            st.error(str(exc))
        except Exception:
            st.error("비밀번호를 저장하지 못했습니다. 다시 시도해 주세요.")
        else:
            clear_identity()
            st.session_state[TOKEN_KEY] = next_token
            st.session_state["_tap_account_notice"] = "비밀번호를 변경했습니다. 다른 로그인 세션은 종료되었습니다."
            # Mark /password as already entered so the rerun leaves it for work.
            st.session_state[ROUTE_KEY] = PASSWORD_ROUTE
            st.rerun()


def render_portal(route: str | None = None, *, routed: bool = False) -> None:
    """Render the workspace; ``routed`` pages keep the URL in step with the menu."""
    st.html(PORTAL_CSS + brand_css())
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        _login(None)
        return
    try:
        store = _configured_store(dsn, os.environ.get("BOOTSTRAP_ADMIN_LOGIN", "kma.admin"), os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_HASH", ""))
    except Exception:
        st.title("KMA TAP")
        st.error("계정 서비스에 연결하지 못했습니다. 잠시 후 다시 이용해 주세요.")
        st.stop()
    _notice()
    token = st.session_state.get(TOKEN_KEY)
    if not isinstance(token, str) or not token:
        _login(store)
        return
    try:
        principal = store.principal(token)
    except AccountError:
        from tap.session_cookie import sync_cookie

        clear_identity()
        sync_cookie(TOKEN_KEY)
        st.info("로그인이 만료되었거나 계정 상태가 변경되었습니다. 다시 로그인해 주세요.")
        _login(store)
        return
    except Exception:
        st.error("계정 상태를 확인하지 못했습니다. 잠시 후 새로고침해 주세요.")
        st.stop()
    role = principal["role"]
    if role not in ROLE_LABELS:
        st.error("접근 권한을 확인해 주세요.")
        return

    def logout() -> None:
        try:
            store.logout(token)
        except Exception:
            st.error("로그아웃을 처리하지 못했습니다. 다시 시도해 주세요.")
            st.stop()
        clear_identity()
        st.rerun()

    if routed:
        enter_route(route)
    st.html(workspace_theme_css())
    section = render_workspace_header(principal, logout)
    if routed:
        follow_route(route, bool(principal["must_change_password"]))
    with st.container(key="tap_workspace_main"):
        password_screen = bool(principal["must_change_password"]) or st.session_state[ACCOUNT_MENU_KEY] == "비밀번호 변경"
        label = "비밀번호 변경" if password_screen else section_label(role, section)
        with st.container(key="tap_workspace_breadcrumb"):
            st.caption(f"워크스페이스 / {label}")
        if password_screen:
            _password_change(store, token, bool(principal["must_change_password"]))
            return
        try:
            if section == "dashboard" and role in {"kma", "company"}:
                from tap.account_dashboard import render_dashboard
                render_dashboard(store, token, principal)
            elif section == "question_bank" and role == "kma":
                from tap.account_question_bank import render_question_bank
                render_question_bank(store, token, principal)
            elif role in {"kma", "company"}:
                from tap.account_admin_ui import render_admin
                render_admin(store, token, principal, section=section)
            elif role == "participant":
                from tap.account_assessment_ui import render_participant
                render_participant(store, token, principal)
        except AccountError as exc:
            st.error(str(exc))
        except Exception:
            st.error("요청을 처리하지 못했습니다. 저장 여부를 확인한 뒤 다시 시도해 주세요.")
