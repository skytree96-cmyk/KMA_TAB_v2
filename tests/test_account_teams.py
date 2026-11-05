import csv
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from tap.account_teams import BATCH, apply_changes, plan_roster, roster_csv, team_counts


def person(number, department="", job_title="", role="participant", company="c"):
    return {"id": f"u{number}", "login_id": f"0123456789-user{number:03d}", "display_name": f"참여자{number:02d}", "role": role,
            "company_id": company, "department": department, "job_title": job_title}


USERS = [person(1, "영업팀", "대리"), person(2, "영업팀"), person(3), person(4, "기획팀", "과장"),
         person(9, "담당부서", role="company")]


def filled(rows, headers=("아이디", "이름", "상태", "부서", "직급")):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


class TeamRosterTests(unittest.TestCase):
    def test_counts_leave_out_people_without_a_group_and_non_participants(self):
        self.assertEqual(team_counts(USERS), [("영업팀", 2), ("기획팀", 1)])
        self.assertEqual(team_counts(USERS, "job_title"), [("과장", 1), ("대리", 1)])

    def test_roster_lists_unassigned_people_first_and_keeps_formula_cells_as_text(self):
        users = [*USERS, {**person(5, "=SUM(A1)"), "display_name": "@위험"}]
        rows = list(csv.reader(io.StringIO(roster_csv(users).decode("utf-8-sig"))))
        self.assertEqual(rows[0], ["아이디", "이름", "상태", "부서", "직급"])
        self.assertEqual(rows[1][:3], ["0123456789-user003", "참여자03", "부서 미지정"])
        self.assertEqual(len(rows), 6)  # the training manager's own account is not a participant
        risky = next(row for row in rows if row[1].endswith("위험"))
        self.assertEqual((risky[1], risky[3]), ("'@위험", "'=SUM(A1)"))

    def test_plan_names_every_change_and_sets_aside_rows_it_cannot_apply(self):
        plan = plan_roster(filled([
            ["0123456789-USER003", "참여자03", "부서 미지정", "해외영업팀", "사원"],   # assign, a new department and title
            ["0123456789-user002", "참여자02", "지정됨", "기획팀", ""],               # move
            ["0123456789-user001", "참여자01", "지정됨", "", "대리"],                 # cleared department
            ["0123456789-user004", "참여자04", "지정됨", "기획팀", "과장"],            # unchanged
            ["0123456789-user004", "참여자04", "지정됨", "영업팀", "과장"],            # the same ID twice
            ["0123456789-user777", "없는 사람", "", "영업팀", ""],
            ["", "", "", "", ""],
        ]), USERS)
        self.assertEqual(plan["changes"], [{"user_id": "u3", "department": "해외영업팀", "job_title": "사원"},
                                           {"user_id": "u2", "department": "기획팀"}, {"user_id": "u1", "department": ""}])
        self.assertEqual(plan["counts"], {"new": 2, "assign": 2, "move": 1, "clear": 1, "excluded": 2})
        self.assertEqual(plan["new"], ["해외영업팀", "사원"])
        self.assertEqual([(row["이름"], row["구분"], row["지금"], row["바뀜"], row["처리"]) for row in plan["rows"]],
                         [("참여자03", "부서", "부서 미지정", "해외영업팀", "지정"), ("참여자03", "직급", "직급 미지정", "사원", "지정"),
                          ("참여자02", "부서", "영업팀", "기획팀", "옮김"), ("참여자01", "부서", "영업팀", "부서 미지정", "빠짐")])
        self.assertEqual([reason for _, reason in plan["excluded"]], ["같은 아이디가 두 번 있습니다", "등록된 참여자가 아닙니다"])

    def test_one_person_cannot_be_put_in_two_departments(self):
        plan = plan_roster(filled([["0123456789-user001", "참여자01", "", "영업팀, 기획팀", "대리"],
                                   ["0123456789-user002", "참여자02", "", "가" * 101, ""]]), USERS)
        self.assertEqual(plan["changes"], [])
        self.assertIn("두 개", plan["excluded"][0][1])
        self.assertIn("100자", plan["excluded"][1][1])

    def test_a_file_with_only_one_of_the_two_columns_leaves_the_other_alone(self):
        plan = plan_roster(filled([["0123456789-user001", "기획팀"]], headers=("아이디", "부서")), USERS)
        self.assertEqual(plan["changes"], [{"user_id": "u1", "department": "기획팀"}])

    def test_unreadable_files_are_refused_whole(self):
        for content in (b"\xff\xfe\x00bad", filled([["x", "y"]], headers=("이름", "부서")), filled([], headers=("아이디", "이름")),
                        b"x" * (256 * 1024 + 1)):
            with self.assertRaises(ValueError):
                plan_roster(content, USERS)

    def test_changes_go_to_the_store_in_batches(self):
        store = SimpleNamespace(set_profiles=Mock(side_effect=lambda token, rows: len(rows)))
        changes = [{"user_id": f"u{i}", "department": "영업팀"} for i in range(BATCH + 3)]
        self.assertEqual(apply_changes(store, "token", changes), BATCH + 3)
        self.assertEqual([len(call.args[1]) for call in store.set_profiles.call_args_list], [BATCH, 3])


class TeamScreenTests(unittest.TestCase):
    SCRIPT = ("import streamlit as st\nfrom tap.account_teams import render_teams\n"
              "render_teams(st.session_state['store'], 'token', {'role': 'company', 'company_id': 'c'}, st.session_state['users'])")

    def run_screen(self, users):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string(self.SCRIPT, default_timeout=30)
        app.session_state["store"] = SimpleNamespace(set_profiles=Mock(return_value=1))
        app.session_state["users"] = users
        app.run()
        self.assertFalse(app.exception)
        return app

    def test_screen_lists_unassigned_people_and_saves_the_department_picked_for_them(self):
        app = self.run_screen([*USERS, person(6, company="other")])
        self.assertIn("부서 미지정 1명", [item.value for item in app.subheader])   # another company's person is not counted
        self.assertEqual(len(app.dataframe), 1)
        pick = next(box for box in app.selectbox if box.key == "account_teams_unassigned_pick_u3")
        pick.set_value("기획팀").run()
        next(button for button in app.button if button.key == "account_teams_unassigned_save").click().run()
        app.session_state["store"].set_profiles.assert_called_once_with("token", [{"user_id": "u3", "department": "기획팀"}])

    def test_screen_without_participants_points_to_account_issuing(self):
        app = self.run_screen([person(9, role="company")])
        self.assertTrue(any("참여자 계정" in item.value for item in app.info))


if __name__ == "__main__":
    unittest.main()
