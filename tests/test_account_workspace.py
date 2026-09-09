from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest


APP = '''
import streamlit as st
from tap.account_admin_ui import render_admin
class Store:
    def record(self, method):
        st.session_state["reads"] = st.session_state.get("reads", []) + [method]
    def list_companies(self, token):
        self.record("companies")
        return [{"id":"co1", "name":"알파 교육", "slug":"0123456789", "active":True}, {"id":"co2", "name":"Beta Academy", "slug":"9999999999", "active":True}]
    def list_users(self, token):
        self.record("users")
        return st.session_state.get("users", [
            {"id":"u1", "display_name":"홍길동", "login_id":"alpha-hong", "company_id":"co1", "role":"participant", "department":"교육팀", "job_title":"대리", "email":"hong@example.com", "phone":"010-1234-5678", "active":True},
            {"id":"u2", "display_name":"김하나", "login_id":"Beta-Kim", "company_id":"co2", "role":"participant", "active":True},
            {"id":"u3", "display_name":"알파 담당자", "login_id":"alpha-manager", "company_id":"co1", "role":"company", "active":True},
            {"id":"admin", "display_name":"KMA", "login_id":"kma.admin", "role":"kma", "active":True},
        ])
    def list_projects(self, token):
        self.record("projects")
        return st.session_state.get("projects", [
            {"id":"p1", "name":"리더 성장", "company_id":"co1", "config":{"course_name":"AI Leadership", "training_date":"2026-10-08", "selected_factors":[]}},
            {"id":"p2", "name":"협업 강화", "company_id":"co2", "config":{"course_name":"Team Workshop", "selected_factors":[]}},
        ])
    def project_results(self, token, project_id):
        st.session_state["report_target"] = project_id
        return []
    def list_assignments(self, token, project_id):
        st.session_state["assignment_target"] = project_id
        return []
    def reset_password(self, token, user_id, password):
        st.session_state["reset_target"] = (user_id, password)
    def set_user_active(self, token, user_id, active):
        st.session_state["active_target"] = (user_id, active)
    def create_user(self, token, login_id, display_name, role, company_id, password, *, profile=None):
        st.session_state["issued"] = {"login_id":login_id, "role":role, "company_id":company_id, "password":password, "profile":profile}
        return {"id":"issued-user"}
role = st.session_state.get("role", "kma")
render_admin(Store(), "token", {"id":"principal", "role":role, "company_id":"co1"}, section=st.session_state.get("section", "projects"))
'''


def rerun(app: AppTest) -> AppTest:
    states = app._tree.get_widget_states()
    # AppTest omits stateful expander values although browsers submit them.
    for key in ("account_admin_workspace_issue_kma", "account_admin_workspace_issue_company", "account_admin_batch_expander_co1"):
        if key in app.session_state.filtered_state:
            widget = states.widgets.add()
            widget.id = app.session_state._state._key_id_mapper.get_id_from_key(key)
            widget.bool_value = app.session_state[key]
    result = app._run(states, timeout=30)
    if result.exception:
        raise AssertionError([item.value for item in result.exception])
    return result


class AccountWorkspaceTests(unittest.TestCase):
    def app(self, section="projects", role="kma", **state):
        app = AppTest.from_string(APP)
        app.session_state["section"] = section
        app.session_state["role"] = role
        for key, value in state.items():
            app.session_state[key] = value
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def test_workspace_dispatch_has_no_internal_tabs_and_rejects_wrong_role_section(self):
        for role, sections in (("kma", ("companies", "accounts", "projects")), ("company", ("projects", "create_project", "accounts"))):
            for section in sections:
                with self.subTest(role=role, section=section):
                    app = self.app(section, role)
                    self.assertEqual(len(app.tabs), 0)
                    self.assertEqual(len(app.title), 1)
        for role, section in (("company", "companies"), ("kma", "create_project"), ("participant", "accounts")):
            with self.subTest(role=role, section=section):
                app = self.app(section, role)
                self.assertTrue(app.error)
                self.assertNotIn("reads", app.session_state.filtered_state)

    def test_project_search_selects_actual_project_and_never_auto_selects_new_match(self):
        app = self.app()
        self.assertIsNone(app.radio(key="account_admin_project_select").value)
        for query, project_id in (("성장", "p1"), ("lEaDeR", "p1"), ("beta", "p2")):
            app.text_input(key="account_admin_project_search").input(query)
            rerun(app)
            self.assertEqual(app.radio(key="account_admin_project_select").value, "p1" if query == "lEaDeR" else None)
            app.radio(key="account_admin_project_select").set_value(project_id)
            rerun(app)
            self.assertEqual(app.session_state["report_target"], project_id)
        app.text_input(key="account_admin_project_search").input("아무 결과 없음")
        del app.session_state["report_target"]
        rerun(app)
        self.assertFalse(app.radio)
        self.assertNotIn("report_target", app.session_state.filtered_state)

    def test_company_workspace_filters_projects_users_and_assignment_candidates(self):
        app = self.app(role="company")
        self.assertEqual(app.radio(key="account_admin_project_select").options, ["리더 성장"])
        app.radio(key="account_admin_project_select").set_value("p1")
        rerun(app)
        self.assertEqual(app.session_state["assignment_target"], "p1")
        self.assertEqual(app.multiselect(key="account_admin_assign_p1").options, ["홍길동 · alpha-hong"])
        app.text_input(key="account_admin_project_search").input("Beta")
        rerun(app)
        self.assertFalse(app.radio)
        app.session_state["section"] = "accounts"
        rerun(app)
        self.assertEqual(app.radio(key="account_admin_manage_user").options, ["홍길동 · alpha-hong"])
        app.text_input(key="account_admin_manage_user_search").input("알파 담당자")
        rerun(app)
        self.assertFalse(app.radio)

    def test_account_search_and_reset_never_target_a_filtered_out_account(self):
        app = self.app("accounts")
        for query in ("길동", "PHA-HO", "알파 교육"):
            app.text_input(key="account_admin_manage_user_search").input(query)
            rerun(app)
            self.assertIn("홍길동 · alpha-hong", app.radio(key="account_admin_manage_user").options)
        app.radio(key="account_admin_manage_user").set_value("u1")
        rerun(app)
        app.text_input(key="account_admin_manage_user_search").input("beta")
        app.button(key="account_admin_password_reset").click()
        rerun(app)
        self.assertNotIn("reset_target", app.session_state.filtered_state)
        self.assertIsNone(app.radio(key="account_admin_manage_user").value)
        self.assertFalse(any(button.key == "account_admin_password_reset" for button in app.button))
        app.radio(key="account_admin_manage_user").set_value("u2")
        rerun(app)
        app.button(key="account_admin_password_reset").click()
        rerun(app)
        self.assertEqual(app.session_state["reset_target"], ("u2", "kma"))
        app.button(key="account_admin_toggle_active").click()
        rerun(app)
        self.assertEqual(app.session_state["active_target"], ("u2", False))

    def test_search_and_selection_survive_navigation_and_refresh_validity_on_return(self):
        app = self.app("accounts")
        app.text_input(key="account_admin_manage_user_search").input("HONG")
        rerun(app)
        app.radio(key="account_admin_manage_user").set_value("u1")
        rerun(app)
        app.session_state["section"] = "projects"
        rerun(app)
        app.session_state["section"] = "accounts"
        rerun(app)
        self.assertEqual(app.text_input(key="account_admin_manage_user_search").value, "HONG")
        self.assertEqual(app.radio(key="account_admin_manage_user").value, "u1")
        app.session_state["section"] = "projects"
        rerun(app)
        app.session_state["users"] = []
        app.session_state["section"] = "accounts"
        rerun(app)
        self.assertIsNone(app.session_state["account_admin_manage_user"])
        self.assertFalse(any(button.key == "account_admin_password_reset" for button in app.button))

    def test_paginated_lists_clear_hidden_targets_and_keep_current_page_after_navigation(self):
        projects = [{"id":f"p{i}", "name":f"교육 {i}", "company_id":"co1", "config":{"selected_factors":[]}} for i in range(25)]
        app = self.app(projects=projects)
        self.assertEqual(len(app.radio(key="account_admin_project_select").options), 12)
        app.radio(key="account_admin_project_select").set_value("p1")
        rerun(app)
        app.button(key="account_admin_project_select_next_page").click()
        rerun(app)
        self.assertIsNone(app.radio(key="account_admin_project_select").value)
        self.assertEqual(app.radio(key="account_admin_project_select").options[0], "교육 12")
        app.radio(key="account_admin_project_select").set_value("p14")
        rerun(app)
        app.session_state["section"] = "accounts"
        rerun(app)
        app.session_state["section"] = "projects"
        rerun(app)
        self.assertEqual(app.radio(key="account_admin_project_select").value, "p14")
        app.text_input(key="account_admin_project_search").input("교육 0")
        rerun(app)
        self.assertIsNone(app.radio(key="account_admin_project_select").value)
        self.assertEqual(app.session_state["account_admin_project_select_page"], 0)

    def test_account_issuance_keeps_company_prefix_profile_and_credential_receipt(self):
        app = self.app("accounts", "company")
        values = {"아이디":"NewUser", "이름":"새 참여자", "부서":"개발팀", "직급":"과장", "이메일":"new@example.com", "연락처":"010-9876-5432"}
        for label, value in values.items():
            next(field for field in app.text_input if field.label == label).input(value)
        next(button for button in app.button if button.label == "참여자 계정 발급").click()
        rerun(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["issued"], {"login_id":"0123456789-newuser", "role":"participant", "company_id":"co1", "password":"kma", "profile":{"department":"개발팀", "job_title":"과장", "email":"new@example.com", "phone":"010-9876-5432"}})
        self.assertTrue(any(button.key == "account_admin_credentials_clear" for button in app.button))
        self.assertTrue(any(item.label == "CSV로 참여자 일괄 등록" for item in app.expander))
        app.button(key="account_admin_credentials_clear").click()
        rerun(app)
        self.assertNotIn("account_admin_credentials", app.session_state.filtered_state)


if __name__ == "__main__":
    unittest.main()
