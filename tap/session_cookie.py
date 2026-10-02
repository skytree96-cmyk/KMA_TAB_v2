"""Keep the account session across full page loads with a first-party cookie.

Streamlit session state lives only as long as one websocket connection, so a
refresh or a typed URL (for example /login) used to sign the user out. The
opaque session token is mirrored into a SameSite=Strict cookie and restored on
the next connection; AccountStore still validates expiry and idle time on every
request, so a stale cookie only leads back to the login screen.
"""
from __future__ import annotations

import re

import streamlit as st

from tap.account_store import SESSION_SECONDS


COOKIE_NAME = "tap_session"
CHECKED_KEY = "_tap_cookie_checked"
SYNCED_KEY = "_tap_cookie_synced"
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")


def _valid(value: object) -> str:
    return value if isinstance(value, str) and _TOKEN_RE.fullmatch(value) else ""


def _browser_cookie() -> str:
    try:
        return _valid(st.context.cookies.get(COOKIE_NAME))
    except Exception:
        return ""


def restore_session(token_key: str) -> None:
    """Adopt the cookie token once per connection, before any page renders."""
    if st.session_state.get(CHECKED_KEY):
        return
    st.session_state[CHECKED_KEY] = True
    cookie = _browser_cookie()
    if not st.session_state.get(token_key) and cookie:
        st.session_state[token_key] = cookie
    # Record what the browser holds so an unchanged state emits nothing.
    st.session_state[SYNCED_KEY] = cookie


def forget_restored_cookie() -> None:
    """Call after clearing identity: the handshake cookie of this connection is stale."""
    st.session_state[CHECKED_KEY] = True


def cookie_update_script(token_key: str) -> str:
    """Return the script that brings the browser cookie in line with the session, or ""."""
    desired = _valid(st.session_state.get(token_key))
    if st.session_state.get(SYNCED_KEY) == desired:
        return ""
    st.session_state[SYNCED_KEY] = desired
    if desired:
        cookie = f"{COOKIE_NAME}={desired}; Path=/; Max-Age={SESSION_SECONDS}; SameSite=Strict"
    else:
        cookie = f"{COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Strict"
    return f"<script>document.cookie = {cookie!r} + (location.protocol === 'https:' ? '; Secure' : '');</script>"


def sync_cookie(token_key: str) -> None:
    """Write or delete the browser cookie when the session token changed."""
    script = cookie_update_script(token_key)
    # Always emit this slot. Adding it only on some reruns shifts every later
    # element, and the shifted login card briefly showed twice while Streamlit
    # kept the stale copy until the slow password check finished.
    with st.container(key="tap_session_cookie_sync"):
        st.html("<style>.st-key-tap_session_cookie_sync{display:none}</style>" + script,
                unsafe_allow_javascript=True)
