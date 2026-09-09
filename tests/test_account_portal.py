from __future__ import annotations

from contextlib import contextmanager
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

    def test_successful_login_replaces_login_layout_with_workspace(self):
        from tap import account_portal
        class Store:
            def login(self, login_id, password):
                return "opaque-token"
            def principal(self, token):
                return dict(id="p1", login_id="user", display_name="참여자", role="participant", company_id="c1", must_change_password=False)
        with patch.dict(os.environ, {"DATABASE_URL":"postgresql://test.invalid/test"}), patch.object(account_portal, "_configured_store", return_value=Store()), patch("tap.account_assessment_ui.render_participant") as participant:
            app = AppTest.from_function(_portal_entry).run()
            app.text_input[0].input("user")
            app.text_input[1].input("kma")
            next(button for button in app.button if button.label == "로그인").click().run()
            self.assertEqual(list(app.exception), [])
            self.assertEqual(app.session_state[account_portal.TOKEN_KEY], "opaque-token")
            self.assertFalse(app.text_input)
            self.assertFalse(any(title.value == "로그인" for title in app.title))
            participant.assert_called_once()

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
            app.session_state["_tap_workspace_section"]="assessments"
            app.session_state["_tap_account_menu"]="업무 화면"
            app.query_params["tap_role"]="kma"
            app.run()
            app.button(key="_tap_logout").click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(store.logged_out,"opaque-token")
            for key in [account_portal.TOKEN_KEY,"account_admin_credentials","responses","_tap_workspace_section","_tap_account_menu"]:
                self.assertNotIn(key,app.session_state)
            self.assertNotIn("tap_role",app.query_params)


class _NavigationStore:
    def __init__(self, role, must_change_password=False):
        self.user = dict(
            id="user-1", login_id="acme-001", display_name="테스트 사용자",
            role=role, company_id=None if role == "kma" else "company-1",
            company_name="테스트 회사", must_change_password=must_change_password,
        )
        self.password_change = None

    def principal(self, token):
        return self.user.copy()

    def change_password(self, token, old, new):
        self.password_change = (token, old, new)
        self.user["must_change_password"] = False
        return "rotated-token"


def _run_navigation(app):
    # Stateful popovers are Blocks in Streamlit 1.61 AppTest. Preserve their
    # boolean value, as the browser does, when testing a widget rerun.
    states = app._tree.get_widget_states()
    key = "_tap_profile_popover"
    if key in app.session_state.filtered_state:
        widget = states.widgets.add()
        widget.id = app.session_state._state._key_id_mapper.get_id_from_key(key)
        widget.bool_value = app.session_state[key]
    return app._run(states, timeout=30)


@contextmanager
def _authenticated_navigation(role, *, required=False, section=None):
    from tap import account_portal
    store = _NavigationStore(role, required)
    with patch.dict(os.environ, {"TAP_APP_MODE": "production", "DATABASE_URL": "postgresql://test.invalid/test"}), patch.object(account_portal, "_configured_store", return_value=store), patch("tap.account_admin_ui.render_admin") as admin, patch("tap.account_assessment_ui.render_participant") as participant:
        app = AppTest.from_function(_portal_entry)
        app.session_state[account_portal.TOKEN_KEY] = "opaque-token"
        if section is not None:
            app.session_state["_tap_workspace_section"] = section
        app.run()
        yield app, store, admin, participant


class PortalNavigationTests(unittest.TestCase):
    def assert_no_error(self, app):
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)

    def test_topbar_only_exposes_authenticated_role_destinations(self):
        expectations = {
            "kma": {"_tap_nav_dashboard": "대시보드", "_tap_nav_question_bank": "문항은행·검수", "_tap_nav_companies": "회원사", "_tap_nav_accounts": "계정 관리", "_tap_nav_projects": "프로젝트"},
            "company": {"_tap_nav_dashboard": "대시보드", "_tap_nav_projects": "프로젝트", "_tap_nav_create_project": "프로젝트 만들기", "_tap_nav_accounts": "참여자 계정"},
            "participant": {"_tap_nav_assessments": "내 교육"},
        }
        for role, expected in expectations.items():
            with self.subTest(role=role), _authenticated_navigation(role) as (app, store, admin, participant):
                self.assert_no_error(app)
                actual = {button.key: button.label for button in app.button if button.key and button.key.startswith("_tap_nav_")}
                self.assertEqual(actual, expected)
                self.assertFalse(app.sidebar.button)
                self.assertFalse(app.sidebar.radio)
                if role == "participant":
                    participant.assert_called_once()
                    admin.assert_not_called()
                else:
                    self.assertEqual(admin.call_args.kwargs["section"], "projects")
                    participant.assert_not_called()

    def test_dashboard_and_bank_routes_keep_role_boundaries(self):
        for role in ("kma", "company"):
            with patch("tap.account_dashboard.render_dashboard") as dashboard:
                with _authenticated_navigation(role, section="dashboard") as (app, store, admin, participant):
                    self.assert_no_error(app)
                    dashboard.assert_called_once()
                    admin.assert_not_called()
        with patch("tap.account_question_bank.render_question_bank") as bank:
            with _authenticated_navigation("kma", section="question_bank") as (app, store, admin, participant):
                self.assert_no_error(app)
                bank.assert_called_once()
                admin.assert_not_called()
            bank.reset_mock()
            with _authenticated_navigation("company", section="question_bank") as (app, store, admin, participant):
                self.assert_no_error(app)
                bank.assert_not_called()
                self.assertEqual(admin.call_args.kwargs["section"], "projects")

    def test_selected_section_persists_through_unrelated_reruns(self):
        with _authenticated_navigation("kma") as (app, store, admin, participant):
            app.button(key="_tap_nav_accounts").click()
            _run_navigation(app)
            self.assert_no_error(app)
            self.assertEqual(admin.call_args.kwargs["section"], "accounts")
            app.session_state["account_admin_account_search"] = "테스트"
            _run_navigation(app)
            self.assert_no_error(app)
            self.assertEqual(app.session_state["_tap_workspace_section"], "accounts")
            self.assertEqual(admin.call_args.kwargs["section"], "accounts")
            self.assertEqual(app.session_state["account_admin_account_search"], "테스트")

    def test_company_cannot_reach_kma_section_from_stale_session(self):
        with _authenticated_navigation("company", section="companies") as (app, store, admin, participant):
            self.assert_no_error(app)
            self.assertEqual(app.session_state["_tap_workspace_section"], "projects")
            self.assertEqual(admin.call_args.kwargs["section"], "projects")
            self.assertEqual(admin.call_args.args[2]["role"], "company")
            participant.assert_not_called()

    def test_participant_cannot_route_to_admin_from_tampered_section(self):
        with _authenticated_navigation("participant", section="accounts") as (app, store, admin, participant):
            app.query_params["tap_role"] = "kma"
            _run_navigation(app)
            self.assert_no_error(app)
            self.assertEqual(app.session_state["_tap_workspace_section"], "assessments")
            self.assertEqual(participant.call_count, 2)
            admin.assert_not_called()

    def test_profile_password_link_and_work_navigation_close_popover(self):
        with _authenticated_navigation("company", section="accounts") as (app, store, admin, participant):
            app.session_state["_tap_profile_popover"] = True
            _run_navigation(app)
            admin.reset_mock()
            app.button(key="_tap_account_password_nav").click()
            _run_navigation(app)
            self.assert_no_error(app)
            self.assertEqual(app.session_state["_tap_account_menu"], "비밀번호 변경")
            self.assertFalse(app.session_state["_tap_profile_popover"])
            self.assertTrue(any(item.value == "비밀번호 변경" for item in app.subheader))
            admin.assert_not_called()
            app.button(key="_tap_nav_projects").click()
            _run_navigation(app)
            self.assert_no_error(app)
            self.assertEqual(app.session_state["_tap_account_menu"], "업무 화면")
            self.assertEqual(admin.call_args.kwargs["section"], "projects")
            self.assertFalse(any(item.label == "현재 비밀번호" for item in app.text_input))

    def test_required_password_disables_work_navigation_for_every_role(self):
        for role in ("kma", "company", "participant"):
            with self.subTest(role=role), _authenticated_navigation(role, required=True) as (app, store, admin, participant):
                self.assert_no_error(app)
                navigation = [button for button in app.button if button.key and button.key.startswith("_tap_nav_")]
                self.assertTrue(navigation)
                self.assertTrue(all(button.disabled for button in navigation))
                self.assertFalse(app.button(key="_tap_logout").disabled)
                self.assertTrue(any("처음 사용할" in item.value for item in app.subheader))
                admin.assert_not_called()
                participant.assert_not_called()

    def test_password_save_rotates_session_and_returns_to_work(self):
        from tap.account_portal import TOKEN_KEY
        with _authenticated_navigation("company", section="accounts") as (app, store, admin, participant):
            app.session_state["account_admin_credentials"] = [{"password": "old-secret"}]
            app.button(key="_tap_account_password_nav").click()
            _run_navigation(app)
            fields = {item.label: item for item in app.text_input}
            fields["현재 비밀번호"].input("kma")
            fields["새 비밀번호"].input("new-password")
            fields["새 비밀번호 확인"].input("new-password")
            next(button for button in app.button if button.label == "비밀번호 저장").click()
            _run_navigation(app)
            self.assert_no_error(app)
            self.assertEqual(store.password_change, ("opaque-token", "kma", "new-password"))
            self.assertEqual(app.session_state[TOKEN_KEY], "rotated-token")
            self.assertNotIn("account_admin_credentials", app.session_state)
            self.assertEqual(admin.call_args.kwargs["section"], "projects")
            self.assertFalse(any(item.label == "현재 비밀번호" for item in app.text_input))


if __name__ == "__main__":
    unittest.main()