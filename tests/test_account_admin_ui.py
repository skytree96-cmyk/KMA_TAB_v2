from __future__ import annotations

import csv
import hashlib
import io
import unittest
from datetime import date

from streamlit.testing.v1 import AppTest

from tap.account_admin_ui import build_project_config, credentials_csv, parse_participant_csv
from tap.data import questions_for_factors


class AccountAdminInputTests(unittest.TestCase):
    def config(self, **changes):
        values = dict(
            name="리더 교육", course_name="협업 과정", target_level="staff", optional_factors=["AI_USE"],
            training_date=date(2026, 10, 8), pre_start=date(2026, 10, 1), pre_end=date(2026, 10, 7),
            post_start=date(2026, 12, 3), post_end=date(2026, 12, 10),
        )
        values.update(changes)
        return build_project_config(**values)

    def test_csv_normalizes_company_prefix_and_rejects_duplicate_identity(self):
        rows = parse_participant_csv("login_id,display_name\nUser001,홍길동\nacme-user002,김참여\n".encode(), "acme")
        self.assertEqual([row["login_id"] for row in rows], ["acme-user001", "acme-user002"])
        with self.assertRaisesRegex(ValueError, "같은 아이디"):
            parse_participant_csv(b"login_id,display_name\nuser001,A\nacme-USER001,B\n", "acme")

    def test_csv_rejects_bad_rows_before_returning_any_participants(self):
        for content in (
            b"login_id,display_name\nuser001,A,extra\n",
            b"login_id,display_name\nuser001\n",
            b"login_id,display_name\nuser001,A\n=HYPERLINK,B\n",
            b"email,display_name\na@example.com,A\n",
            b"login_id,display_name\n",
            b"login_id,display_name\nuser001,\xff\n",
        ):
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_participant_csv(content, "acme")

    def test_csv_export_does_not_execute_spreadsheet_formulas(self):
        payload = credentials_csv([{"login_id": "acme-user001", "display_name": "=HYPERLINK(\"x\")", "temp_password": "T7!example"}])
        rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
        self.assertTrue(rows[1][1].startswith("'="))
        self.assertEqual(rows[1][2], "T7!example")

    def test_project_snapshot_matches_existing_instrument_contract(self):
        config = self.config()
        questions = questions_for_factors(config["selected_factors"])
        snapshot = "\n".join("|".join(parts) for parts in sorted(
            (str(row["question_code"]), str(row["revised_text"]), str(row.get("scoring_direction", "direct")))
            for row in questions
        ))
        digest = hashlib.sha256(snapshot.encode()).hexdigest()
        self.assertEqual(config["question_snapshot_hash"], digest)
        self.assertEqual(config["assessment_version"], f"TAP-1.0+{digest[:12]}")
        self.assertEqual(set(config["question_snapshot_codes"]), {row["question_code"] for row in questions})
        self.assertFalse(config["allow_schedule_override"])
        self.assertEqual(config["project_start_date"], config["pre_start_date"])
        self.assertEqual(config["question_snapshot_hash"], self.config(name="다른 이름")["question_snapshot_hash"])

    def test_project_rejects_incompatible_factors_and_schedules(self):
        for changes in (
            {"optional_factors": ["STRAT_CORE"]},
            {"optional_factors": ["AI_USE", "PLAN_STR", "DATA_ANA", "DX_APPLY"]},
            {"pre_end": date(2026, 10, 8)},
            {"post_start": date(2026, 10, 7)},
            {"priorities": ["missing"]},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.config(**changes)


APP = '''
import streamlit as st
from tap.account_admin_ui import render_admin
class Store:
    def list_companies(self, token):
        return [{"id":"co1", "name":"테스트 회원사", "slug":"acme", "active":True}]
    def list_users(self, token):
        return []
    def list_projects(self, token):
        return []
    def create_user(self, token, login_id, display_name, role, company_id, temp_password):
        st.session_state["issued"] = {"login_id":login_id, "role":role, "company_id":company_id, "password":temp_password}
        return {"id":"u2"}
render_admin(Store(), "opaque-token", {"id":"u1", "role":ROLE, "company_id":"co1"})
'''


class AccountAdminRenderTests(unittest.TestCase):
    def test_assignment_can_be_removed_and_reactivated_without_deleting_account(self):
        app = AppTest.from_string('''
import streamlit as st
from tap.account_admin_ui import _render_assignments
class Store:
    def list_assignments(self, token, project_id):
        return [{"id":"a1", "user_id":"u2", "user_name":"참여자", "login_id":"acme-user001", "active":st.session_state.get("assignment_active", True)}]
    def set_assignment_active(self, token, assignment_id, active):
        st.session_state["assignment_active"] = active
        st.session_state["changed_assignment"] = assignment_id
_render_assignments(Store(), "token", {"id":"p1", "company_id":"co1"}, [{"id":"u2", "role":"participant", "company_id":"co1", "active":True}])
''').run(timeout=30)
        self.assertEqual(list(app.exception), [])
        next(item for item in app.button if item.label == "프로젝트 배정 해제").click()
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertFalse(app.session_state["assignment_active"])
        self.assertEqual(app.session_state["changed_assignment"], "a1")
        next(item for item in app.button if item.label == "프로젝트 다시 배정").click()
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(app.session_state["assignment_active"])

    def test_kma_and_manager_render_without_old_role_switch(self):
        for role in ("kma", "company"):
            app = AppTest.from_string(APP.replace("ROLE", repr(role))).run(timeout=30)
            self.assertEqual(list(app.exception), [])
            self.assertFalse(any("역할 전환" in item.label for item in app.radio))
            self.assertEqual(len(app.title), 1)

    def test_manager_can_issue_participant_without_email_or_manual_password(self):
        app = AppTest.from_string(APP.replace("ROLE", repr("company"))).run(timeout=30)
        next(item for item in app.text_input if item.label == "아이디").input("user001")
        next(item for item in app.text_input if item.label == "이름").input("참여자")
        next(item for item in app.button if item.label == "참여자 계정 발급").click()
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        issued = app.session_state["issued"]
        self.assertEqual(issued["login_id"], "acme-user001")
        self.assertEqual(issued["role"], "participant")
        self.assertEqual(issued["company_id"], "co1")
        self.assertGreaterEqual(len(issued["password"]), 20)
        self.assertTrue(any(item.label == "전달 완료 · 발급 정보 닫기" for item in app.button))
        next(item for item in app.button if item.label == "전달 완료 · 발급 정보 닫기").click()
        app.run(timeout=30)
        self.assertNotIn("account_admin_credentials", app.session_state.filtered_state)


if __name__ == "__main__":
    unittest.main()
