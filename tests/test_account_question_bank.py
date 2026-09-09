from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest

from tap.account_question_bank import _updated_time


APP = '''
import streamlit as st
from tap.account_question_bank import render_question_bank
class ConflictError(ValueError):
    pass
class Store:
    def list_question_bank(self, token):
        st.session_state["reads"] = st.session_state.get("reads", 0) + 1
        return st.session_state.setdefault("rows", [
            {"question_code":"Q1", "module_group":"공통기반", "factor_code":"CORE", "factor_name_ko":"고객지향", "revised_text":"고객의 요구를 확인했다.", "original_text":"원문1", "scoring_direction":"direct", "revision":0, "updated_at":None, "updated_by":None},
            {"question_code":"Q2", "module_group":"공통기반", "factor_code":"COMM", "factor_name_ko":"의사소통", "revised_text":"동료의 의견을 들었다.", "revision":2, "updated_at":0, "updated_by":"kma.editor"},
            {"question_code":"Q3", "module_group":"리더십", "factor_code":"LEAD", "factor_name_ko":"팀 리딩", "revised_text":"팀의 목표를 설명했다.", "revision":0, "updated_at":None, "updated_by":None},
            {"question_code":"Q4", "module_group":"삭제된 모듈", "factor_code":"OLD", "factor_name_ko":"삭제된 역량", "revised_text":"운영하지 않는 문구", "active":False, "revision":0, "updated_at":None, "updated_by":None},
        ])
    def save_question_text(self, token, question_code, text, *, expected_revision):
        st.session_state["save_calls"] = st.session_state.get("save_calls", []) + [(question_code, text, expected_revision)]
        row = next(row for row in st.session_state["rows"] if row["question_code"] == question_code)
        if row["revision"] != expected_revision:
            raise ConflictError("internal-conflict-details")
        row.update(revised_text=text, revision=expected_revision + 1, updated_at=1788912000, updated_by="kma.me")
        return row
render_question_bank(Store(), "token", {"id":"kma1", "role":st.session_state.get("role", "kma")})
'''


def rerun(app):
    app.run(timeout=30)
    if app.exception:
        raise AssertionError([item.value for item in app.exception])
    return app


def save(app):
    next(button for button in app.button if button.label == "운영 문구 저장").click()
    return rerun(app)


class AccountQuestionBankTests(unittest.TestCase):
    def app(self):
        app = AppTest.from_string(APP).run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def test_only_kma_can_read_editor_and_timestamps_use_kst(self):
        for role in ("company", "participant", ""):
            app = AppTest.from_string(APP)
            app.session_state["role"] = role
            rerun(app)
            self.assertTrue(app.error)
            self.assertNotIn("reads", app.session_state.filtered_state)
        self.assertEqual(_updated_time(None), "미수정")
        self.assertEqual(_updated_time(0), "1970-01-01 09:00:00")

    def test_module_and_factor_filters_clear_hidden_selection_and_refresh_discards_editor(self):
        app = self.app()
        self.assertIsNone(app.selectbox(key="question_bank_select").value)
        self.assertEqual(set(app.dataframe[0].value["문항 코드"]), {"Q1", "Q2", "Q3"})
        self.assertNotIn("삭제된 모듈", app.selectbox(key="question_bank_module").options)
        self.assertTrue(any("운영 문항 3개" in item.value for item in app.caption))
        self.assertEqual(app.dataframe[0].value.iloc[1]["최종 수정 시각"], "1970-01-01 09:00:00")
        self.assertEqual([field.label for field in app.selectbox], ["모듈", "역량", "편집할 문항"])
        app.selectbox(key="question_bank_factor").set_value("CORE")
        rerun(app)
        self.assertEqual(list(app.dataframe[0].value["문항 코드"]), ["Q1"])
        app.selectbox(key="question_bank_select").set_value("Q1")
        rerun(app)
        app.text_area(key="question_bank_text").input("작성 중인 초안")
        rerun(app)
        app.selectbox(key="question_bank_module").set_value("리더십")
        rerun(app)
        self.assertIsNone(app.selectbox(key="question_bank_factor").value)
        self.assertIsNone(app.selectbox(key="question_bank_select").value)
        self.assertEqual(list(app.dataframe[0].value["문항 코드"]), ["Q3"])
        self.assertFalse(app.text_area)
        self.assertNotIn("question_bank_draft", app.session_state.filtered_state)
        app.selectbox(key="question_bank_select").set_value("Q3")
        rerun(app)
        self.assertEqual(app.text_area(key="question_bank_text").value, "팀의 목표를 설명했다.")
        app.button(key="question_bank_refresh").click()
        rerun(app)
        self.assertIsNone(app.selectbox(key="question_bank_select").value)
        self.assertNotIn("question_bank_draft", app.session_state.filtered_state)
        self.assertNotIn("question_bank_text", app.session_state.filtered_state)

    def test_save_validates_length_and_only_changes_operational_text(self):
        app = self.app()
        app.selectbox(key="question_bank_select").set_value("Q1")
        rerun(app)
        for text in ("   ", "가" * 2001):
            app.text_area(key="question_bank_text").input(text)
            save(app)
            self.assertTrue(app.error)
            self.assertNotIn("save_calls", app.session_state.filtered_state)
        app.text_area(key="question_bank_text").input(" 새 운영 문구를 사용했다. ")
        save(app)
        self.assertEqual(app.session_state["save_calls"], [("Q1", "새 운영 문구를 사용했다.", 0)])
        self.assertEqual(app.session_state["question_bank_draft"]["base_revision"], 1)
        self.assertEqual(app.text_area(key="question_bank_text").value, "새 운영 문구를 사용했다.")
        self.assertFalse(app.session_state["question_bank_draft"]["conflict"])
        self.assertTrue(app.success)
        row = app.session_state["rows"][0]
        self.assertEqual((row["original_text"], row["scoring_direction"]), ("원문1", "direct"))

    def test_concurrent_edit_keeps_original_revision_and_draft_until_explicit_reload(self):
        app = self.app()
        app.selectbox(key="question_bank_select").set_value("Q1")
        rerun(app)
        app.session_state["rows"][0].update(revised_text="다른 관리자가 수정한 문구", revision=1, updated_at=1788912000, updated_by="kma.other")
        app.text_area(key="question_bank_text").input("내가 작성 중인 문구")
        save(app)
        self.assertEqual(app.session_state["save_calls"], [("Q1", "내가 작성 중인 문구", 0)])
        self.assertEqual(app.session_state["question_bank_draft"]["base_revision"], 0)
        self.assertEqual(app.text_area(key="question_bank_text").value, "내가 작성 중인 문구")
        self.assertTrue(app.error)
        self.assertFalse(any("internal-conflict-details" in item.value for item in app.error))
        rerun(app)
        self.assertEqual(app.session_state["question_bank_draft"]["base_revision"], 0)
        self.assertEqual(app.text_area(key="question_bank_text").value, "내가 작성 중인 문구")
        app.button(key="question_bank_load_latest").click()
        rerun(app)
        self.assertEqual(app.session_state["question_bank_draft"]["base_revision"], 1)
        self.assertEqual(app.text_area(key="question_bank_text").value, "다른 관리자가 수정한 문구")
        self.assertFalse(app.warning)
        app.text_area(key="question_bank_text").input("최신 문구에 내 수정을 반영했다.")
        save(app)
        self.assertEqual(app.session_state["save_calls"][-1], ("Q1", "최신 문구에 내 수정을 반영했다.", 1))
        self.assertEqual(app.session_state["question_bank_draft"]["base_revision"], 2)


if __name__ == "__main__":
    unittest.main()
