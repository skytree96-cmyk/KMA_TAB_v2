"""Account portal: one authenticated router, with no role supplied by the browser."""
from __future__ import annotations

import os

import streamlit as st

from tap.account_store import AccountError, AccountStore
from tap.brand import brand_css, brand_html


TOKEN_KEY = "_tap_account_session"
ROLE_LABELS = {"kma": "KMA 관리자", "company": "교육담당자", "participant": "참여자"}

PORTAL_CSS = """
<style>
[data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer,
[data-testid="stSidebarNav"] {display:none !important;}
[data-testid="stHeader"] {background:transparent;height:0;}
.block-container {max-width:1180px;padding-top:2.5rem;padding-bottom:4rem;}
h1,h2,h3 {letter-spacing:-.035em;color:#102a2d;}
.tap-account-brand {font-size:1.45rem;font-weight:800;color:#087b76;margin-bottom:.4rem;}
.tap-account-intro {color:#53696b;line-height:1.7;margin-bottom:1.8rem;}
[data-testid="stSidebar"] {background:#fff;border-right:1px solid #d8e4e2;}
.stButton>button {border-radius:10px;}
</style>
"""


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
    left, center, right = st.columns([1, 2, 1])
    with center:
        st.markdown(brand_html(), unsafe_allow_html=True)
        st.title("로그인")
        st.markdown('<div class="tap-account-intro">교육 전·후 업무행동의 변화를 확인합니다.<br>발급받은 ID로 로그인하면 내 교육과 관리 화면이 열립니다.</div>', unsafe_allow_html=True)
        with st.form("_tap_login_form", clear_on_submit=True):
            login_id = st.text_input("로그인 ID", max_chars=64, placeholder="회사명-사번 또는 지정 ID", disabled=store is None)
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
    st.markdown(PORTAL_CSS + brand_css(), unsafe_allow_html=True)
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
    with st.sidebar:
        st.markdown(brand_html(compact=True), unsafe_allow_html=True)
        st.write(f"{principal['display_name']} · {ROLE_LABELS.get(role, '')}")
        st.caption(principal["login_id"])
        if st.button("로그아웃", key="_tap_logout", use_container_width=True):
            try:
                store.logout(token)
            except Exception:
                st.error("로그아웃을 처리하지 못했습니다. 다시 시도해 주세요.")
                st.stop()
            clear_identity()
            st.rerun()
        if not principal["must_change_password"]:
            account_menu = st.radio("내 계정", ["업무 화면", "비밀번호 변경"], key="_tap_account_menu")
        else:
            account_menu = "비밀번호 변경"
        st.caption("브라우저를 새로 열거나 새로고침하면 다시 로그인이 필요할 수 있습니다.")
    if principal["must_change_password"] or account_menu == "비밀번호 변경":
        _password_change(store, token, bool(principal["must_change_password"]))
        return
    try:
        if role in {"kma", "company"}:
            from tap.account_admin_ui import render_admin

            render_admin(store, token, principal)
        elif role == "participant":
            from tap.account_assessment_ui import render_participant

            render_participant(store, token, principal)
        else:
            st.error("접근 권한을 확인해 주세요.")
    except AccountError as exc:
        st.error(str(exc))
    except Exception:
        st.error("요청을 처리하지 못했습니다. 저장 여부를 확인한 뒤 다시 시도해 주세요.")
