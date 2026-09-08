from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def _portal_entry():
    from tap.account_portal import render_portal
    render_portal()


class PortalAccessTests(unittest.TestCase):
    def test_missing_database_never_falls_back_to_public_demo(self):
        with patch.dict(os.environ, {"TAP_APP_MODE": "production", "DATABASE_URL": ""}):
            app = AppTest.from_function(_portal_entry).run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("연결을 준비" in item.value for item in app.info))
        self.assertTrue(all(item.disabled for item in app.text_input))
        self.assertFalse(any(item.label in {"교육담당자", "참여자", "KMA 관리자"} for item in app.button))
        self.assertFalse(any("공개 데모" in item.value for item in app.markdown))

    def test_all_legacy_entrypoints_stop_before_loading_demo(self):
        with patch.dict(os.environ, {"TAP_APP_MODE": "production"}):
            for path in sorted((ROOT / "pages").glob("*.py")):
                with self.subTest(page=path.name):
                    app = AppTest.from_file(str(path)).run()
                    self.assertEqual(len(app.exception), 0)
                    self.assertTrue(any("로그인 후" in item.value for item in app.info))
                    self.assertFalse(app.text_input)
                    self.assertFalse(app.dataframe)
                    self.assertFalse(app.button)

    def test_browser_role_does_not_override_authenticated_role(self):
        from tap import account_portal
        class Store:
            def principal(self, token):
                return dict(id="p1", login_id="acme-001", display_name="참여자", role="participant", company_id="c1", must_change_password=False)
        with patch.dict(os.environ, {"TAP_APP_MODE": "production", "DATABASE_URL": "postgresql://test.invalid/test"}), patch.object(account_portal, "_configured_store", return_value=Store()), patch("tap.account_assessment_ui.render_participant") as participant, patch("tap.account_admin_ui.render_admin") as admin:
            app=AppTest.from_file(str(ROOT / "streamlit_app.py"))
            app.session_state[account_portal.TOKEN_KEY]="opaque-token"
            app.query_params["tap_role"]="kma"
            app.run()
            self.assertEqual(len(app.exception),0)
            participant.assert_called_once()
            admin.assert_not_called()

    def test_temporary_password_blocks_every_work_screen(self):
        from tap import account_portal
        class Store:
            def principal(self, token):
                return dict(id="k1", login_id="kma.admin", display_name="KMA 관리자", role="kma", company_id=None, must_change_password=True)
        with patch.dict(os.environ,{"TAP_APP_MODE":"production","DATABASE_URL":"postgresql://test.invalid/test"}), patch.object(account_portal,"_configured_store",return_value=Store()), patch("tap.account_admin_ui.render_admin") as admin:
            app=AppTest.from_file(str(ROOT / "streamlit_app.py"))
            app.session_state[account_portal.TOKEN_KEY]="opaque-token"
            app.run()
            self.assertEqual(len(app.exception),0)
            self.assertTrue(any("처음 사용할" in item.value for item in app.subheader))
            admin.assert_not_called()

    def test_logout_clears_all_identity_bound_widget_data(self):
        from tap import account_portal
        class Store:
            def principal(self, token):
                return dict(id="p1",login_id="acme-001",display_name="참여자",role="participant",company_id="c1",must_change_password=False)
            def logout(self, token):
                self.logged_out=token
        store=Store()
        with patch.dict(os.environ,{"TAP_APP_MODE":"production","DATABASE_URL":"postgresql://test.invalid/test"}), patch.object(account_portal,"_configured_store",return_value=store), patch("tap.account_assessment_ui.render_participant"):
            app=AppTest.from_file(str(ROOT / "streamlit_app.py"))
            app.session_state[account_portal.TOKEN_KEY]="opaque-token"
            app.session_state["account_admin_credentials"]=[{"password":"old-secret"}]
            app.session_state["responses"]={"old-person":5}
            app.query_params["tap_role"]="kma"
            app.run()
            app.button(key="_tap_logout").click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(store.logged_out,"opaque-token")
            for key in [account_portal.TOKEN_KEY,"account_admin_credentials","responses"]:
                self.assertNotIn(key,app.session_state)
            self.assertNotIn("tap_role",app.query_params)


if __name__ == "__main__":
    unittest.main()