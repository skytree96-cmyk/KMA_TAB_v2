from __future__ import annotations

import csv
import hashlib
import io
import unittest
from datetime import date

from streamlit.testing.v1 import AppTest

from tap.account_admin_ui import (
    CSV_TEMPLATE, _company_registration_label, _login_id, _registration_number, _safe_error,
    _temporary_password, build_project_config, credentials_csv, parse_participant_csv,
)
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

    def test_csv_template_uses_korean_headers_and_parses(self):
        self.assertNotIn("login_id", CSV_TEMPLATE)
        self.assertEqual(len(parse_participant_csv(CSV_TEMPLATE.encode("utf-8"), "acme")), 2)
        row = parse_participant_csv("아이디,이름,연락처,부서\nuser001,홍길동,010-1234-5678,교육팀\n".encode(), "acme")[0]
        self.assertEqual((row["login_id"], row["display_name"], row["department"], row["phone"]),
                         ("acme-user001", "홍길동", "교육팀", "010-1234-5678"))
        with self.assertRaisesRegex(ValueError, "첫 두 열은 아이디, 이름"):
            parse_participant_csv("이름,아이디\n홍길동,user001\n".encode(), "acme")

    def test_csv_rejects_bad_rows_before_returning_any_participants(self):
        for content in (
            b"login_id,display_name\nuser001,A,extra\n",
            b"login_id,display_name\nuser001\n",
            b"login_id,display_name\nuser001,A\n=HYPERLINK,B\n",
            b"login_id,display_name\nuser001,A\n,B\n",
            b"login_id,display_name\nacme-,A\n",
            b"email,display_name\na@example.com,A\n",
            b"login_id,display_name\n",
            b"login_id,display_name\nuser001,\xff\n",
        ):
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_participant_csv(content, "acme")

    def test_business_number_is_exact_ascii_text_and_keeps_leading_zero(self):
        self.assertEqual(_registration_number("0123456789"), "0123456789")
        for number in ("012345678", "01234567890", "012-34-56789", "０１２３４５６７８９", "٠١٢٣٤٥٦٧٨٩", " 0123456789", "0123456789 "):
            with self.subTest(number=number), self.assertRaisesRegex(ValueError, "사업자등록번호"):
                _registration_number(number)
        self.assertEqual(_company_registration_label({"slug": "acme"}), "미등록")
        self.assertEqual(_company_registration_label({"slug": "0123456789"}), "0123456789")
        ConflictError = type("ConflictError", (ValueError,), {})
        self.assertIn("사업자등록번호", _safe_error(ConflictError("internal detail")))
        self.assertNotIn("internal detail", _safe_error(ConflictError("internal detail")))

    def test_manager_id_is_plain_and_participant_prefix_is_added_only_once(self):
        self.assertEqual(_login_id(" Manager001 "), "manager001")
        self.assertEqual(_login_id("User", "0123456789"), "0123456789-user")
        self.assertEqual(_login_id("User001", "0123456789"), "0123456789-user001")
        for custom in ("Hong123", "NewUser", "user-team", "usr", "other-user001"):
            with self.subTest(custom=custom):
                self.assertEqual(_login_id(custom, "0123456789"), custom.lower())
        rows = parse_participant_csv(b"login_id,display_name\nNewUser,A\nuser,B\n0123456789-user001,C\n", "0123456789")
        self.assertEqual([row["login_id"] for row in rows], ["newuser", "0123456789-user", "0123456789-user001"])
        self.assertEqual(_login_id("0123456789-USER001", "0123456789"), "0123456789-user001")
        self.assertEqual(_login_id("acme-existing"), "acme-existing")
        for value in ("", " ", "0123456789-"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _login_id(value, "0123456789")

    def test_initial_password_is_limited_to_explicitly_authorized_roles(self):
        for role in ("company", "participant"):
            self.assertEqual(_temporary_password(role), "kma")
        for role in ("kma", "", "other"):
            with self.subTest(role=role), self.assertRaises(ValueError):
                _temporary_password(role)

    def test_csv_accepts_optional_profile_columns_and_legacy_two_columns(self):
        empty = parse_participant_csv(b"login_id,display_name\nuser001,A\n", "0123456789")[0]
        self.assertEqual([empty[key] for key in ("department", "job_title", "email", "phone")], [""] * 4)
        payload = "login_id,display_name,phone,email,department,job_title\nuser002,참여자,010-1234-5678,user@example.com, 교육팀 , 대리 \n"
        row = parse_participant_csv(payload.encode(), "0123456789")[0]
        self.assertEqual(row, {"login_id": "0123456789-user002", "display_name": "참여자", "department": "교육팀", "job_title": "대리", "email": "user@example.com", "phone": "010-1234-5678"})
        partial = parse_participant_csv("login_id,display_name,department\nuser003,참여자,교육팀\n".encode(), "0123456789")[0]
        self.assertEqual(partial["department"], "교육팀")
        self.assertEqual(partial["email"], "")

    def test_csv_rejects_invalid_profile_before_any_account_is_created(self):
        for header, value in (
            ("department", "a" * 101), ("job_title", "a" * 81), ("email", "missing-at"),
            ("email", "a" * 250 + "@example.com"), ("phone", "1234"), ("phone", "０１０１２３４５６７８"),
            ("phone", "12345 ext 1"), ("phone", "1" * 21), ("department", '"before\nafter"'),
            ("department", "\x85team"), ("unknown", "value"), ("email,email", "a@b.com,a@b.com"),
        ):
            payload = f"login_id,display_name,{header}\nuser001,A,{value}\n".encode()
            with self.subTest(header=header, value=value), self.assertRaises(ValueError):
                parse_participant_csv(payload, "0123456789")

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

    def test_project_accepts_equal_dates_at_each_schedule_boundary(self):
        same_day = date(2026, 10, 8)
        for changes in (
            {"pre_end": same_day}, {"post_start": same_day},
            {"pre_start": same_day, "pre_end": same_day, "post_start": same_day, "post_end": same_day},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.config(**changes)["training_date"], same_day.isoformat())

    def test_project_rejects_incompatible_factors_and_schedules(self):
        for changes in (
            {"optional_factors": ["STRAT_CORE"]},
            {"optional_factors": ["AI_USE", "PLAN_STR", "DATA_ANA", "DX_APPLY"]},
            {"pre_end": date(2026, 10, 9)},
            {"pre_start": date(2026, 10, 8)},
            {"post_end": date(2026, 12, 2)},
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
        return st.session_state.get("companies", [{"id":"co1", "name":"테스트 회원사", "slug":"acme", "active":True}])
    def list_users(self, token):
        return st.session_state.get("users", [])
    def list_projects(self, token):
        return []
    def create_company(self, token, name, slug):
        row = {"id":"co2", "name":name, "slug":slug, "registration_number":slug, "active":True}
        st.session_state["created_company"] = row
        st.session_state["companies"] = self.list_companies(token) + [row]
        return row
    def set_company_registration_number(self, token, company_id, registration_number):
        st.session_state["registration_update"] = {"company_id":company_id, "registration_number":registration_number}
        companies = [{**row, "slug":registration_number, "registration_number":registration_number} if row["id"] == company_id else row for row in self.list_companies(token)]
        st.session_state["companies"] = companies
        return next(row for row in companies if row["id"] == company_id)
    def create_user(self, token, login_id, display_name, role, company_id, temp_password, *, profile=None):
        issued = {"login_id":login_id, "display_name":display_name, "role":role, "company_id":company_id, "password":temp_password, "profile":profile}
        st.session_state["issued"] = issued
        st.session_state["all_issued"] = st.session_state.get("all_issued", []) + [issued]
        user = {"id":"u" + str(len(st.session_state["all_issued"]) + 1), "login_id":login_id, "display_name":display_name, "role":role, "company_id":company_id, "company_name":"테스트 회원사", "active":True, **(profile or {})}
        st.session_state["users"] = self.list_users(token) + [user]
        return user
    def create_users(self, token, role, company_id, rows, temp_password, *, project_id=None, existing_user_ids=None):
        st.session_state["batch_assignment"] = (project_id, existing_user_ids)
        return [self.create_user(token, row["login_id"], row["display_name"], role, company_id, temp_password,
                                 profile={key: value for key, value in row.items() if key not in {"login_id", "display_name"}}) for row in rows]
    def reset_password(self, token, user_id, temp_password):
        st.session_state["reset"] = {"user_id":user_id, "password":temp_password}
    def create_project(self, token, name, config):
        st.session_state["created_project"] = {"name":name, "config":config}
        return {"id":"p1"}
render_admin(Store(), "opaque-token", {"id":"u1", "role":ROLE, "company_id":"co1"})
'''


def picks(app: AppTest, key: str) -> list[str]:
    """Labels of the person checkboxes a bulk picker shows on the current page."""
    return [box.label for box in app.checkbox if box.key and box.key.startswith(key + "_pick_")]


def run_app(app: AppTest) -> AppTest:
    # Streamlit 1.61 AppTest treats tabs and expanders as Blocks, so its public
    # run() omits their widget values. Supply the same values a browser sends.
    states = app._tree.get_widget_states()
    for key in ("account_admin_kma_tabs", "account_admin_company_tabs", "account_admin_batch_expander_co1"):
        if key not in app.session_state.filtered_state:
            continue
        widget = states.widgets.add()
        widget.id = app.session_state._state._key_id_mapper.get_id_from_key(key)
        value = app.session_state[key]
        if isinstance(value, bool):
            widget.bool_value = value
        else:
            widget.string_value = value
    return app._run(states, timeout=30)


class ProgressBoardTests(unittest.TestCase):
    def test_status_follows_the_furthest_phase_and_inactive_wins(self):
        from tap.account_admin_ui import participant_status
        self.assertEqual(participant_status({}), ("미시작", ""))
        self.assertEqual(participant_status({"pre_answered": 12, "question_count": 24}), ("진행 중", "교육 전 12/24"))
        self.assertEqual(participant_status({"pre_completed": True, "pre_answered": 24}), ("교육 전 완료", ""))
        self.assertEqual(participant_status({"pre_completed": True, "post_answered": 3, "question_count": 24}), ("진행 중", "교육 후 3/24"))
        self.assertEqual(participant_status({"post_completed": True}), ("교육 후 완료", ""))
        self.assertEqual(participant_status({"active": False, "post_completed": True}), ("배정 해제", ""))

    def test_initial_ranges_are_balanced_and_cover_every_consonant(self):
        from tap.account_admin_ui import initial_ranges
        self.assertEqual([label for label, _ in initial_ranges([{"user_name": f"김{i}"} for i in range(10)])], [""])
        surnames = "김이박최정강조윤장임한오서신권황안송류홍"
        rows = [{"user_name": surnames[i % len(surnames)] + str(i)} for i in range(34)] + [{"user_name": "Alice"}]
        ranges = initial_ranges(rows)
        self.assertEqual(len(ranges), 4)
        self.assertEqual(sum(len(members) for _, members in ranges), len(rows))
        self.assertTrue(ranges[0][0].startswith("ㄱ"))
        self.assertIn("ㅎ·기타", ranges[-1][0])
        self.assertLessEqual(max(len(m) for _, m in ranges), len(rows) // 2)

    def test_incomplete_csv_lists_current_phase_only_and_blocks_formulas(self):
        from tap.account_admin_ui import incomplete_csv
        rows = [{"id": "a1", "user_name": "=cmd", "login_id": "x1", "department": "영업", "pre_answered": 3, "question_count": 24},
                {"id": "a2", "user_name": "끝냄", "login_id": "x2", "pre_completed": True},
                {"id": "a3", "user_name": "해제", "login_id": "x3", "active": False}]
        label, content, count = incomplete_csv({"config": {"post_start_date": "2999-01-01"}}, rows)
        self.assertEqual((label, count), ("교육 전 미완료자 명단 CSV (1명)", 1))
        text = content.decode("utf-8-sig")
        self.assertIn("'=cmd,x1,영업,,진행 중,교육 전 3/24", text)
        self.assertNotIn("끝냄", text)
        label, _, count = incomplete_csv({"config": {"post_start_date": "2000-01-01"}}, rows)
        self.assertEqual((label, count), ("교육 후 미완료자 명단 CSV (2명)", 2))

    def test_board_filters_by_status_groups_departments_and_pages(self):
        app = AppTest.from_string('''
import streamlit as st
from tap.account_admin_ui import _render_assignments
rows = []
for i in range(23):
    rows.append({"id": f"s{i}", "user_id": f"s{i}", "user_name": "가나다라마바사아자차카타파하"[i % 14] + "영업" + str(i),
                 "login_id": f"sales{i}", "active": True, "question_count": 24,
                 "pre_completed": i < 10, "pre_answered": 24 if i < 10 else (5 if i < 15 else 0)})
rows.append({"id": "h1", "user_id": "h1", "user_name": "인사담당", "login_id": "hr1", "active": True, "question_count": 24})
users = [{"id": row["user_id"], "role": "participant", "company_id": "co1", "active": True,
          "department": "영업본부" if row["id"].startswith("s") else ""} for row in rows]
class Store:
    def list_assignments(self, token, project_id):
        return rows
_render_assignments(Store(), "token", {"id": "p1", "company_id": "co1", "config": {"post_start_date": "2999-01-01"}}, users)
''').run(timeout=30)
        self.assertEqual(list(app.exception), [])
        expanders = [item.label for item in app.expander if "완료" in item.label]
        self.assertEqual(expanders, ["영업본부 · 교육 전 완료 10/23명", "부서 미등록 · 교육 전 완료 0/1명"])
        range_key = "account_admin_board_range_p1_" + __import__("hashlib").sha256("영업본부".encode()).hexdigest()[:10]
        ranges = app.segmented_control(key=range_key)
        # LXP people list: '전체' first, then up to four initial ranges, ten people per page.
        self.assertEqual(len(ranges.options), 4)
        self.assertEqual(ranges.value, "전체 23")
        self.assertEqual(len(app.dataframe[0].value), 10)
        self.assertEqual(sum(int(option.rsplit(" ", 1)[1]) for option in ranges.options[1:]), 23)
        ranges.set_value(ranges.options[1])
        run_app(app)
        first = app.segmented_control(key=range_key).options[1]
        self.assertEqual(len(app.dataframe[0].value), min(10, int(first.rsplit(" ", 1)[1])))
        app.session_state["account_admin_board_status_p1"] = "미시작"
        run_app(app)
        self.assertEqual(list(app.exception), [])
        statuses = {status for frame in app.dataframe for status in frame.value["상태"]}
        self.assertEqual(statuses, {"미시작"})
        self.assertEqual(sum(len(frame.value) for frame in app.dataframe), 9)

class BulkActionTests(unittest.TestCase):
    def test_people_list_pages_by_ten_with_initial_ranges_and_keeps_picks(self):
        app = AppTest.from_string('''
import streamlit as st
from tap.account_admin_ui import _render_assignments
names = "가나다라마바사아자차카타파하"
users = [{"id": f"u{i:02d}", "display_name": names[i % 14] + str(i), "login_id": f"user{i}", "department": "영업"} for i in range(25)]
users = [{"role": "participant", "company_id": "co1", "active": True, **row} for row in users]
class Store:
    def list_assignments(self, token, project_id):
        return []
    def assign_participants(self, token, project_id, user_ids):
        st.session_state["calls"] = list(user_ids)
        return len(user_ids)
_render_assignments(Store(), "token", {"id": "p1", "company_id": "co1"}, users)
''').run(timeout=30)
        self.assertEqual(list(app.exception), [])
        first = picks(app, "account_admin_assign_p1")
        self.assertEqual(len(first), 10)
        self.assertEqual(first, sorted(first))
        ranges = app.segmented_control(key="account_admin_assign_p1_range")
        self.assertEqual(ranges.value, "전체 25")
        self.assertEqual(len(ranges.options), 4)
        app.button(key="account_admin_assign_p1_page_all").click()
        run_app(app)
        self.assertEqual(len(app.session_state["account_admin_assign_p1"]), 10)
        app.button(key="account_admin_assign_p1_page_next").click()
        run_app(app)
        second = picks(app, "account_admin_assign_p1")
        self.assertEqual(len(second), 10)
        self.assertFalse(set(first) & set(second))
        box = next(item for item in app.checkbox if item.key.startswith("account_admin_assign_p1_pick_"))
        box.check()
        run_app(app)
        # Picks on page 1 stay picked while page 2 is open.
        self.assertEqual(len(app.session_state["account_admin_assign_p1"]), 11)
        app.segmented_control(key="account_admin_assign_p1_range").set_value(app.segmented_control(key="account_admin_assign_p1_range").options[-1])
        run_app(app)
        self.assertEqual(app.session_state["account_admin_assign_p1_page"], 0)
        app.button(key="account_admin_assign_save_p1").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(len(app.session_state["calls"]), 11)

    def test_department_chip_assigns_everyone_in_one_call(self):
        app = AppTest.from_string('''
import streamlit as st
from tap.account_admin_ui import _render_assignments
users = [{"id": f"s{i}", "display_name": f"영업{i}", "login_id": f"sales{i}", "department": "영업본부"} for i in range(12)]
users += [{"id": "h1", "display_name": "인사", "login_id": "hr1", "department": ""}]
users = [{"role": "participant", "company_id": "co1", "active": True, **row} for row in users]
class Store:
    def list_assignments(self, token, project_id):
        return []
    def assign_participants(self, token, project_id, user_ids):
        st.session_state["calls"] = st.session_state.get("calls", []) + [list(user_ids)]
        return len(user_ids)
_render_assignments(Store(), "token", {"id": "p1", "company_id": "co1"}, users)
''').run(timeout=30)
        chips = app.button_group(key="account_admin_assign_p1_groups")
        self.assertEqual(chips.options, ["영업본부 12", "부서 미등록 1"])
        chips.set_value(["영업본부"])
        run_app(app)
        # Department members leave the individual list, so nobody is counted twice.
        self.assertEqual(picks(app, "account_admin_assign_p1"), ["인사 · hr1"])
        app.checkbox(key="account_admin_assign_p1_pick_h1").check()
        run_app(app)
        self.assertEqual(len(app.dataframe[-1].value), 13)
        app.button(key="account_admin_assign_save_p1").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["calls"], [[f"s{i}" for i in range(12)] + ["h1"]])

    def test_csv_can_issue_and_assign_existing_and_new_people_together(self):
        app = AppTest.from_string(APP.replace("ROLE", repr("company")).replace(
            "    def list_projects(self, token):\n        return []",
            "    def list_projects(self, token):\n        return [{\"id\":\"p1\", \"name\":\"리더 과정\", \"company_id\":\"co1\", \"config\":{}}]")).run(timeout=30)
        app.session_state["users"] = [{"id":"old", "login_id":"acme-user001", "display_name":"기존", "role":"participant", "company_id":"co1", "active":True}]
        app.session_state["account_admin_company_tabs"] = "참여자 계정"
        app.session_state["account_admin_batch_expander_co1"] = True
        run_app(app)
        app.get("file_uploader")[0].upload("p.csv", "아이디,이름\nuser001,기존\nuser002,새사람\n".encode(), "text/csv")
        run_app(app)
        app.selectbox(key="account_admin_batch_project").set_value("p1")
        run_app(app)
        next(item for item in app.button if item.label == "새 참여자 1명 등록 후 2명 배정").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual([item["login_id"] for item in app.session_state["all_issued"]], ["acme-user002"])
        self.assertEqual(app.session_state["batch_assignment"], ("p1", ["old"]))
        self.assertTrue(any("2명을 프로젝트에 배정" in item.value for item in app.success))

    def test_bulk_accounts_reset_a_department_and_remember_credentials(self):
        app = AppTest.from_string('''
import streamlit as st
from tap.account_admin_ui import _render_bulk_accounts
users = [{"id": f"u{i}", "display_name": f"사람{i}", "login_id": f"acme-u{i}", "role": "participant", "company_id": "co1",
          "department": "영업" if i < 3 else "기획", "active": i != 4} for i in range(5)]
class Store:
    def reset_passwords(self, token, user_ids, password):
        st.session_state["reset"] = (list(user_ids), password)
        return len(user_ids)
    def set_users_active(self, token, user_ids, active):
        st.session_state["active"] = (list(user_ids), active)
        return len(user_ids)
_render_bulk_accounts(Store(), "token", {"id": "m", "role": "company", "company_id": "co1"}, users)
''').run(timeout=30)
        app.button_group(key="account_admin_bulk_reset_groups").set_value(["영업"])
        run_app(app)
        app.button(key="account_admin_bulk_save").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["reset"], (["u0", "u1", "u2"], "kma"))
        self.assertEqual(len(app.session_state["account_admin_credentials"]["rows"]), 3)
        app.button_group(key="account_admin_bulk_action").set_value("activate")
        run_app(app)
        self.assertEqual(app.button_group(key="account_admin_bulk_activate_groups").options, ["기획 1"])


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
        self.assertFalse(any(item.label == "프로젝트 배정 해제" for item in app.button))
        app.selectbox(key="account_admin_assignment_change_p1").set_value("a1")
        run_app(app)
        next(item for item in app.button if item.label == "프로젝트 배정 해제").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertFalse(app.session_state["assignment_active"])
        self.assertEqual(app.session_state["changed_assignment"], "a1")
        next(item for item in app.button if item.label == "프로젝트 다시 배정").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(app.session_state["assignment_active"])

    def test_assignment_search_filters_profiles_and_clears_hidden_action_targets(self):
        app = AppTest.from_string('''
import streamlit as st
from tap.account_admin_ui import _render_assignments
class Store:
    def list_assignments(self, token, project_id):
        return [
            {"id":"a1", "user_id":"u1", "user_name":"홍길동", "login_id":"alpha-hong", "active":True},
            {"id":"a2", "user_id":"u2", "user_name":"김다른", "login_id":"beta-other", "active":False},
        ]
    def set_assignment_active(self, token, assignment_id, active):
        st.session_state["changed_assignment"] = (assignment_id, active)
    def assign_participants(self, token, project_id, user_ids):
        st.session_state["new_assignment"] = (project_id, user_ids)
        return len(user_ids)
users = [
    {"id":"u1", "display_name":"홍길동", "login_id":"alpha-hong", "department":"교육Team", "job_title":"대리"},
    {"id":"u2", "display_name":"김다른", "login_id":"beta-other", "department":"기획", "job_title":"차장"},
    {"id":"n1", "display_name":"박새봄", "login_id":"new-one", "department":"개발Team", "job_title":"과장"},
    {"id":"n2", "display_name":"정하나", "login_id":"new-two", "department":"지원", "job_title":"사원"},
]
users = [{"role":"participant", "company_id":"co1", "active":True, **row} for row in users]
users += [
    {"id":"foreign", "display_name":"박새봄", "login_id":"new-foreign", "department":"개발Team", "job_title":"과장", "role":"participant", "company_id":"co2", "active":True},
    {"id":"manager", "display_name":"박새봄", "login_id":"new-manager", "role":"company", "company_id":"co1", "active":True},
    {"id":"inactive", "display_name":"박새봄", "login_id":"new-inactive", "role":"participant", "company_id":"co1", "active":False},
]
_render_assignments(Store(), "token", {"id":"p1", "company_id":"co1"}, users)
''').run(timeout=30)
        self.assertEqual(list(app.exception), [])
        self.assertIsNone(app.selectbox(key="account_admin_assignment_change_p1").value)
        for query in ("길동", "PHA-HO", "육tEaM", "대리"):
            app.text_input(key="account_admin_assignment_search_p1").input(query)
            run_app(app)
            self.assertEqual(app.selectbox(key="account_admin_assignment_change_p1").options, ["홍길동 · alpha-hong"])
            self.assertEqual(list(app.dataframe[0].value["이름"]), ["홍길동"])
        app.selectbox(key="account_admin_assignment_change_p1").set_value("a1")
        run_app(app)
        app.text_input(key="account_admin_assignment_search_p1").input("beta")
        app.button(key="account_admin_assignment_toggle_p1").click()
        run_app(app)
        self.assertIsNone(app.selectbox(key="account_admin_assignment_change_p1").value)
        self.assertNotIn("changed_assignment", app.session_state.filtered_state)
        self.assertFalse(any(button.key == "account_admin_assignment_toggle_p1" for button in app.button))
        for query in ("새봄", "NEW-ONE", "발tEaM", "과장"):
            app.text_input(key="account_admin_assign_search_p1").input(query)
            run_app(app)
            self.assertEqual(picks(app, "account_admin_assign_p1"), ["박새봄 · new-one · 개발Team · 과장"])
        app.checkbox(key="account_admin_assign_p1_pick_n1").check()
        run_app(app)
        app.text_input(key="account_admin_assign_search_p1").input("new-two")
        app.button(key="account_admin_assign_save_p1").click()
        run_app(app)
        self.assertEqual(app.session_state["account_admin_assign_p1"], [])
        self.assertNotIn("new_assignment", app.session_state.filtered_state)
        app.checkbox(key="account_admin_assign_p1_pick_n2").check()
        run_app(app)
        app.button(key="account_admin_assign_save_p1").click()
        run_app(app)
        self.assertEqual(app.session_state["new_assignment"], ("p1", ["n2"]))
        for key in ("account_admin_assignment_search_p1", "account_admin_assign_search_p1"):
            app.text_input(key=key).input("검색 결과 없음")
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertFalse(app.selectbox)
        self.assertEqual(picks(app, "account_admin_assign_p1"), [])
        self.assertIsNone(app.session_state["account_admin_assignment_change_p1"])
        self.assertEqual(app.session_state["account_admin_assign_p1"], [])

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
        run_app(app)
        self.assertEqual(list(app.exception), [])
        issued = app.session_state["issued"]
        self.assertEqual(issued["login_id"], "acme-user001")
        self.assertEqual(issued["role"], "participant")
        self.assertEqual(issued["company_id"], "co1")
        self.assertEqual(issued["password"], "kma")
        self.assertTrue(any(item.label == "전달 완료 · 발급 정보 닫기" for item in app.button))
        next(item for item in app.button if item.label == "전달 완료 · 발급 정보 닫기").click()
        run_app(app)
        self.assertNotIn("account_admin_credentials", app.session_state.filtered_state)

    def test_company_creation_preserves_leading_zero_and_invalid_lengths_are_rejected(self):
        app = AppTest.from_string(APP.replace("ROLE", repr("kma"))).run(timeout=30)
        next(item for item in app.text_input if item.label == "회사명").input("새 회원사")
        next(item for item in app.text_input if item.label == "사업자등록번호").input("01234567890")
        next(item for item in app.button if item.label == "회사 등록").click()
        run_app(app)
        self.assertNotIn("created_company", app.session_state.filtered_state)
        self.assertTrue(any("10자리" in item.value for item in app.error))
        next(item for item in app.text_input if item.label == "회사명").input("새 회원사")
        next(item for item in app.text_input if item.label == "사업자등록번호").input("0123456789")
        next(item for item in app.button if item.label == "회사 등록").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["created_company"]["slug"], "0123456789")
        table = next(item.value for item in app.dataframe if "사업자등록번호" in item.value.columns)
        self.assertIn("0123456789", list(table["사업자등록번호"]))

    def test_legacy_company_number_can_be_completed_without_renaming_existing_id(self):
        app = AppTest.from_string(APP.replace("ROLE", repr("kma"))).run(timeout=30)
        table = next(item.value for item in app.dataframe if "사업자등록번호" in item.value.columns)
        self.assertEqual(table.iloc[0]["사업자등록번호"], "미등록")
        app.session_state["users"] = [{"id":"u2", "login_id":"acme-old", "display_name":"기존 담당자", "role":"company", "company_id":"co1", "active":True}]
        run_app(app)
        # The company is found by search, then picked from the result list.
        app.text_input(key="account_admin_registration_company_pick_search").input("테스트")
        run_app(app)
        app.radio(key="account_admin_registration_company_pick").set_value("co1")
        run_app(app)
        next(item for item in app.text_input if item.label == "등록할 사업자등록번호").input("0123456789")
        next(item for item in app.button if item.label == "사업자등록번호 저장").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["registration_update"], {"company_id":"co1", "registration_number":"0123456789"})
        self.assertEqual(app.session_state["users"][0]["login_id"], "acme-old")
        self.assertNotIn("issued", app.session_state.filtered_state)

    def test_kma_issues_manager_plain_id_with_kma_and_no_participant_profile(self):
        app = AppTest.from_string(APP.replace("ROLE", repr("kma"))).run(timeout=30)
        app.session_state["account_admin_kma_tabs"] = "교육담당자·계정"
        run_app(app)
        self.assertFalse(any(item.label == "아이디" for item in app.text_input))
        app.radio(key="account_admin_issue_company_pick").set_value("co1")
        run_app(app)
        self.assertFalse(any(item.label in {"부서", "직급", "이메일", "연락처"} for item in app.text_input))
        next(item for item in app.text_input if item.label == "아이디").input("Manager001")
        next(item for item in app.text_input if item.label == "이름").input("교육담당자")
        next(item for item in app.button if item.label == "교육담당자 계정 발급").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["issued"]["login_id"], "manager001")
        self.assertEqual(app.session_state["issued"]["password"], "kma")
        self.assertIsNone(app.session_state["issued"]["profile"])
        self.assertEqual(app.session_state["account_admin_kma_tabs"], "교육담당자·계정")
        self.assertEqual(app.get("tab_container")[0].proto.tab_container.default_tab_index, 1)
        self.assertTrue(any("첫 로그인" in item.value and "변경" in item.value for item in app.info))

    def test_participant_profile_is_passed_and_shown_without_changing_selected_tab(self):
        app = AppTest.from_string(APP.replace("ROLE", repr("company"))).run(timeout=30)
        app.session_state["companies"] = [{"id":"co1", "name":"테스트 회원사", "slug":"0123456789", "active":True}]
        app.session_state["account_admin_company_tabs"] = "참여자 계정"
        run_app(app)
        values = {"아이디":"user001", "이름":"참여자", "부서":"교육팀", "직급":"대리", "이메일":"user@example.com", "연락처":"010-1234-5678"}
        for item in app.text_input:
            if item.label in values:
                item.input(values[item.label])
        next(item for item in app.button if item.label == "참여자 계정 발급").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["issued"]["login_id"], "0123456789-user001")
        self.assertEqual(app.session_state["issued"]["password"], "kma")
        self.assertEqual(app.session_state["issued"]["profile"], {"department":"교육팀", "job_title":"대리", "email":"user@example.com", "phone":"010-1234-5678"})
        self.assertEqual(app.session_state["account_admin_company_tabs"], "참여자 계정")
        table = next(item.value for item in app.dataframe if "부서" in item.value.columns)
        self.assertEqual([table.iloc[0][name] for name in ("부서", "직급", "이메일", "연락처")], ["교육팀", "대리", "user@example.com", "010-1234-5678"])
        self.assertEqual(set(app.session_state["account_admin_credentials"]["rows"][0]), {"login_id", "display_name", "temp_password"})
        next(item for item in app.button if item.label == "전달 완료 · 발급 정보 닫기").click()
        run_app(app)
        self.assertEqual(app.session_state["account_admin_company_tabs"], "참여자 계정")
        self.assertEqual(app.get("tab_container")[0].proto.tab_container.default_tab_index, 2)

    def test_reset_uses_kma_for_manager_and_participant_but_excludes_kma_admin(self):
        for role in ("company", "participant"):
            with self.subTest(role=role):
                app = AppTest.from_string(APP.replace("ROLE", repr("kma"))).run(timeout=30)
                app.session_state["users"] = [
                    {"id":"u2", "login_id":"existing-login", "display_name":"사용자", "role":role, "company_id":"co1", "active":True},
                    {"id":"admin2", "login_id":"another-admin", "display_name":"별도 KMA 관리자", "role":"kma", "active":True},
                ]
                run_app(app)
                selector = next(item for item in app.selectbox if item.label == "관리할 계정")
                self.assertEqual(len(selector.options), 1)
                selector.select("u2")
                run_app(app)
                next(item for item in app.button if item.label == "임시 비밀번호 재발급").click()
                run_app(app)
                self.assertEqual(list(app.exception), [])
                self.assertEqual(app.session_state["reset"], {"user_id":"u2", "password":"kma"})
                self.assertEqual(app.session_state["account_admin_credentials"]["rows"][0]["login_id"], "existing-login")

    def test_project_creation_retains_selected_tab_after_success_notice(self):
        app = AppTest.from_string(APP.replace("ROLE", repr("company"))).run(timeout=30)
        app.session_state["account_admin_company_tabs"] = "프로젝트 만들기"
        run_app(app)
        next(item for item in app.text_input if item.label == "프로젝트명").input("교육평가")
        next(item for item in app.text_input if item.label == "교육과정명").input("협업 과정")
        next(item for item in app.button if item.label == "프로젝트 등록").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["created_project"]["name"], "교육평가")
        self.assertEqual(app.session_state["account_admin_company_tabs"], "프로젝트 만들기")
        self.assertEqual(app.get("tab_container")[0].proto.tab_container.default_tab_index, 1)

    def test_csv_upload_preview_and_issue_keep_tab_and_expander_open(self):
        app = AppTest.from_string(APP.replace("ROLE", repr("company"))).run(timeout=30)
        app.session_state["companies"] = [{"id":"co1", "name":"테스트 회원사", "slug":"0123456789", "active":True}]
        app.session_state["account_admin_company_tabs"] = "참여자 계정"
        app.session_state["account_admin_batch_expander_co1"] = True
        run_app(app)
        original_tab_id = app.get("tab_container")[0].proto.tab_container.id
        payload = "login_id,display_name,department,job_title,email,phone\nuser001,참여자1,교육팀,대리,user@example.com,010-1234-5678\n0123456789-user002,참여자2,,,,\n".encode()
        app.get("file_uploader")[0].upload("participants.csv", payload, "text/csv")
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["account_admin_company_tabs"], "참여자 계정")
        self.assertTrue(app.session_state["account_admin_batch_expander_co1"])
        self.assertTrue(next(item for item in app.expander if item.label == "CSV로 참여자 일괄 등록").proto.expanded)
        next(item for item in app.button if item.label == "새 참여자 2명 등록").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual([item["login_id"] for item in app.session_state["all_issued"]], ["0123456789-user001", "0123456789-user002"])
        self.assertEqual([item["password"] for item in app.session_state["all_issued"]], ["kma", "kma"])
        self.assertEqual(app.session_state["all_issued"][0]["profile"]["department"], "교육팀")
        self.assertEqual(app.get("tab_container")[0].proto.tab_container.id, original_tab_id)
        self.assertEqual(app.get("tab_container")[0].proto.tab_container.default_tab_index, 2)
        self.assertEqual(app.session_state["account_admin_company_tabs"], "참여자 계정")
        self.assertTrue(app.session_state["account_admin_batch_expander_co1"])
        self.assertTrue(next(item for item in app.expander if item.label == "CSV로 참여자 일괄 등록").proto.expanded)

    def test_invalid_csv_row_prevents_partial_batch_creation(self):
        app = AppTest.from_string(APP.replace("ROLE", repr("company"))).run(timeout=30)
        payload = b"login_id,display_name\nuser001,A\n,B\n"
        app.get("file_uploader")[0].upload("invalid.csv", payload, "text/csv")
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(any("3행" in item.value for item in app.error))
        self.assertFalse(any(item.label.startswith("새 참여자") for item in app.button))
        self.assertNotIn("issued", app.session_state.filtered_state)


MANAGE_USERS_APP = '''
import streamlit as st
from tap.account_admin_ui import _render_manage_users
class Store:
    def reset_password(self, token, user_id, temp_password):
        st.session_state["resets"] = st.session_state.get("resets", []) + [{"user_id":user_id, "password":temp_password}]
    def set_user_active(self, token, user_id, active):
        st.session_state["toggles"] = st.session_state.get("toggles", []) + [{"user_id":user_id, "active":active}]
        st.session_state["users"] = [{**row, "active":active} if row["id"] == user_id else row for row in st.session_state["users"]]
_render_manage_users(Store(), "opaque-token", st.session_state["principal"], st.session_state["users"])
'''


class AccountManagementSearchTests(unittest.TestCase):
    def app(self, role="kma"):
        app = AppTest.from_string(MANAGE_USERS_APP)
        app.session_state["principal"] = {"id":"admin1", "role":role, "company_id":"co1"}
        app.session_state["users"] = [
            {"id":"u1", "login_id":"alpha-hong", "display_name":"홍길동", "role":"participant", "company_id":"co1", "company_name":"알파 교육", "active":True},
            {"id":"u2", "login_id":"beta-hong", "display_name":"홍길동", "role":"participant", "company_id":"co2", "company_name":"Beta Academy", "active":True},
            {"id":"u3", "login_id":"alpha-manager", "display_name":"김담당", "role":"company", "company_id":"co1", "company_name":"알파 교육", "active":False},
            {"id":"admin2", "login_id":"system-admin", "display_name":"KMA 관리자", "role":"kma", "active":True},
        ]
        return app.run(timeout=30)

    def search(self, app, value):
        app.text_input(key="account_admin_manage_user_search").input(value)
        run_app(app)
        self.assertEqual(list(app.exception), [])

    def assert_accounts(self, app, login_ids):
        self.assertEqual(list(app.exception), [])
        table = next(item.value for item in app.dataframe if "로그인 아이디" in item.value.columns)
        self.assertEqual(list(table["로그인 아이디"]), login_ids)
        options = app.selectbox(key="account_admin_manage_user").options
        self.assertEqual([label.split(" · ")[1] for label in options], login_ids)
        self.assertTrue(all(len(label.split(" · ")) == 3 for label in options))

    def assert_no_account_actions(self, app):
        self.assertFalse(any(item.label in {"임시 비밀번호 재발급", "계정 사용 중지", "계정 다시 활성화"} for item in app.button))

    def test_search_matches_name_id_or_company_and_keeps_table_and_options_consistent(self):
        app = self.app()
        self.assert_accounts(app, ["alpha-hong", "beta-hong", "alpha-manager"])
        self.assertIsNone(app.selectbox(key="account_admin_manage_user").value)
        self.assert_no_account_actions(app)
        for query, expected in (
            ("  홍길동  ", ["alpha-hong", "beta-hong"]),
            ("ALPHA-HO", ["alpha-hong"]),
            ("bEtA aCaDeMy", ["beta-hong"]),
            ("알파 교육", ["alpha-hong", "alpha-manager"]),
            ("   ", ["alpha-hong", "beta-hong", "alpha-manager"]),
        ):
            with self.subTest(query=query):
                self.search(app, query)
                self.assert_accounts(app, expected)
        self.search(app, "없는 회사")
        self.assertTrue(any(item.value.startswith("검색 결과가 없습니다.") for item in app.info))
        self.assertFalse(any(item.label == "관리할 계정" for item in app.selectbox))
        self.assert_no_account_actions(app)
        self.search(app, "")
        self.assert_accounts(app, ["alpha-hong", "beta-hong", "alpha-manager"])
        self.assertIsNone(app.selectbox(key="account_admin_manage_user").value)
        self.assert_no_account_actions(app)

    def test_search_preserves_matching_selection_and_clears_stale_action_target(self):
        app = self.app()
        app.selectbox(key="account_admin_manage_user").select("u1")
        run_app(app)
        self.search(app, "홍길동")
        self.assertEqual(app.selectbox(key="account_admin_manage_user").value, "u1")
        self.search(app, "알파 교육")
        self.assertEqual(app.selectbox(key="account_admin_manage_user").value, "u1")
        # A changed query and a click from the previous rendered account must
        # never reset that old account or silently select the next result.
        app.text_input(key="account_admin_manage_user_search").input("Beta Academy")
        app.button(key="account_admin_password_reset").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assert_accounts(app, ["beta-hong"])
        self.assertIsNone(app.selectbox(key="account_admin_manage_user").value)
        self.assert_no_account_actions(app)
        self.assertNotIn("resets", app.session_state.filtered_state)
        app.selectbox(key="account_admin_manage_user").select("u2")
        run_app(app)
        app.button(key="account_admin_password_reset").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["resets"], [{"user_id":"u2", "password":"kma"}])
        self.assertEqual(app.session_state["account_admin_credentials"]["rows"][0]["login_id"], "beta-hong")
        app.button(key="account_admin_toggle_active").click()
        run_app(app)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.session_state["toggles"], [{"user_id":"u2", "active":False}])
        self.search(app, "검색 결과 없음")
        self.assert_no_account_actions(app)
        self.search(app, "")
        self.assertIsNone(app.selectbox(key="account_admin_manage_user").value)
        self.assert_no_account_actions(app)

    def test_company_manager_search_cannot_expose_other_companies_or_managers(self):
        app = self.app(role="company")
        self.assert_accounts(app, ["alpha-hong"])
        self.search(app, "홍길동")
        self.assert_accounts(app, ["alpha-hong"])
        self.search(app, "알파 교육")
        self.assert_accounts(app, ["alpha-hong"])
        for query in ("Beta Academy", "beta-hong", "김담당", "KMA 관리자"):
            with self.subTest(query=query):
                self.search(app, query)
                self.assertTrue(any(item.value.startswith("검색 결과가 없습니다.") for item in app.info))
                self.assertFalse(any(item.label == "관리할 계정" for item in app.selectbox))
                self.assert_no_account_actions(app)


if __name__ == "__main__":
    unittest.main()
