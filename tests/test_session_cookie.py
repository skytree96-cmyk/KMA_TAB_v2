from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "A" * 43
ENV = {"TAP_APP_MODE": "production", "DATABASE_URL": "postgresql://test.invalid/test"}


class Store:
    def __init__(self):
        self.valid = {TOKEN}
        self.logged_out = []

    def principal(self, token):
        from tap.account_store import AccountError
        if token not in self.valid:
            raise AccountError("expired")
        return dict(id="p1", login_id="acme-001", display_name="참여자", role="participant",
                    company_id="c1", must_change_password=False)

    def logout(self, token):
        self.valid.discard(token)
        self.logged_out.append(token)


def _cookie_scripts(app):
    return [node.proto.body for node in app.get("html") if "document.cookie" in node.proto.body]


class SessionCookieTests(unittest.TestCase):
    def _app(self, store, cookie):
        from tap import account_portal
        stack = [patch.dict(os.environ, ENV), patch.object(account_portal, "_configured_store", return_value=store),
                 patch("tap.account_assessment_ui.render_participant"),
                 patch("tap.session_cookie._browser_cookie", return_value=cookie)]
        for item in stack:
            item.start()
            self.addCleanup(item.stop)
        return AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30)

    def test_reload_with_cookie_restores_login_on_login_route(self):
        from tap.account_portal import TOKEN_KEY
        app = self._app(Store(), TOKEN)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state[TOKEN_KEY], TOKEN)
        self.assertTrue(app.button(key="_tap_logout"))
        # Cookie already matches the restored token: nothing is rewritten.
        self.assertEqual(_cookie_scripts(app), [])

    def test_login_writes_cookie_and_logout_deletes_it_without_restoring(self):
        from tap.account_portal import TOKEN_KEY
        store = Store()
        app = self._app(store, "")
        app.session_state[TOKEN_KEY] = TOKEN
        app.run()
        self.assertTrue(any(f"tap_session={TOKEN};" in s and "Max-Age=28800" in s for s in _cookie_scripts(app)))
        app.button(key="_tap_logout").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(store.logged_out, [TOKEN])
        self.assertNotIn(TOKEN_KEY, app.session_state)
        self.assertTrue(any("tap_session=;" in s and "Max-Age=0" in s for s in _cookie_scripts(app)))

    def test_stale_handshake_cookie_is_not_restored_after_logout(self):
        from tap.account_portal import TOKEN_KEY
        store = Store()
        app = self._app(store, TOKEN)
        app.run()
        app.button(key="_tap_logout").click().run()
        app.run()
        self.assertNotIn(TOKEN_KEY, app.session_state)
        self.assertFalse(any("만료" in item.value for item in app.info))

    def test_expired_cookie_shows_login_and_clears_cookie(self):
        from tap.account_portal import TOKEN_KEY
        store = Store()
        store.valid.clear()
        app = self._app(store, TOKEN)
        app.run()
        self.assertFalse(app.exception)
        self.assertNotIn(TOKEN_KEY, app.session_state)
        self.assertTrue(any("tap_session=;" in s for s in _cookie_scripts(app)))

    def test_malformed_cookie_is_ignored(self):
        from tap.session_cookie import _valid
        self.assertEqual(_valid("abc'; alert(1);//" + "x" * 20), "")
        self.assertEqual(_valid(TOKEN), TOKEN)


if __name__ == "__main__":
    unittest.main()
