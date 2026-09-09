"""Account portal: one authenticated router, with no role supplied by the browser."""
from __future__ import annotations

import os

import streamlit as st

from tap.account_store import AccountError, AccountStore
from tap.brand import brand_css, brand_html
from tap.account_theme import account_theme_css, workspace_theme_css
from tap.account_navigation import ACCOUNT_MENU_KEY, render_workspace_header, section_label


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
    st.session_state.clear()
    st.query_params.clear()


def _notice() -> None:
    message = st.session_state.pop("_tap_account_notice", "")
    if message:
        st.success(message)


def _login(store: AccountStore | None) -> None:
    with st.container(key="tap_login_shell"):
        intro, account = st.columns([1.08, 1], gap="large", vertical_alignment="center")
        with intro:
            with st.container(key="tap_login_intro"):
                st.markdown(brand_html(), unsafe_allow_html=True)
                st.markdown(
                    '<div class="tap-login-eyebrow">TRAINING ASSESSMENT PLATFORM</div>'
                    '<div class="tap-login-headline">교육 전·후<br>업무행동의 <span>변화를<br>확인합니다.</span></div>'
                    '<p class="tap-login-lead">발급받은 ID로 로그인하면<br>내 교육과 관리 화면이 열립니다.</p>'
                    '<div class="tap-login-journey" aria-label="사전검사, 교육·현업 적용, 사후검사">'
                    '<span><b>01</b>사전검사</span><i aria-hidden="true"></i>'
                    '<span><b>02</b>교육·현업 적용</span><i aria-hidden="true"></i>'
                    '<span><b>03</b>사후검사</span></div>',
                    unsafe_allow_html=True,
                )
        with account:
            with st.container(border=True, key="tap_login_card"):
                st.title("로그인")
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
                        st.rerun()
                st.caption("참여자 계정·비밀번호 문의는 교육담당자에게, 교육담당자 계정 문의는 KMA 관리자에게 요청해 주세요.")
            with st.container(key="tap_login_links"):
                st.html('<nav class="tap-login-navigation" aria-label="서비스 안내"><a href="/" target="_self">서비스 소개</a><span>·</span><a href="/guide" target="_self">이용 안내</a></nav>')


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
            st.rerun()


def render_portal() -> None:
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
        clear_identity()
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

    st.html(workspace_theme_css())
    section = render_workspace_header(principal, logout)
    with st.container(key="tap_workspace_main"):
        password_screen = bool(principal["must_change_password"]) or st.session_state[ACCOUNT_MENU_KEY] == "비밀번호 변경"
        label = "비밀번호 변경" if password_screen else section_label(role, section)
        st.caption(f"워크스페이스 / {label}")
        if password_screen:
            _password_change(store, token, bool(principal["must_change_password"]))
            return
        try:
            if role in {"kma", "company"}:
                from tap.account_admin_ui import render_admin
                render_admin(store, token, principal, section=section)
            elif role == "participant":
                from tap.account_assessment_ui import render_participant
                render_participant(store, token, principal)
        except AccountError as exc:
            st.error(str(exc))
        except Exception:
            st.error("요청을 처리하지 못했습니다. 저장 여부를 확인한 뒤 다시 시도해 주세요.")
