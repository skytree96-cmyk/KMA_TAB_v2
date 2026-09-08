from __future__ import annotations

import copy
import hashlib
import unittest

from streamlit.testing.v1 import AppTest

from tap.account_assessment_ui import PREFIX, TRANSFER_ITEMS, _checked_record, _project_questions, _reset_scope
from tap.data import questions_for_factors


def project_config():
    factor = questions_for_factors(["F01"])
    if not factor:
        from tap.data import load_questions
        factor = questions_for_factors([load_questions()[0]["factor_code"]])
    snapshot = sorted((q["question_code"], q["revised_text"], q.get("scoring_direction", "direct")) for q in factor)
    digest = hashlib.sha256("\n".join("|".join(row) for row in snapshot).encode("utf-8")).hexdigest()
    return {
        "selected_factors": [factor[0]["factor_code"]],
        "question_snapshot_codes": [q["question_code"] for q in factor],
        "question_snapshot_hash": digest, "assessment_version": "TAP-1.0+" + digest[:12],
        "course_name": "리더십 교육", "training_date": "2026-01-01",
        "pre_start_date": "2000-01-01", "pre_end_date": "2099-12-31",
        "post_start_date": "2000-01-01", "post_end_date": "2099-12-31",
        "target_means": {},
    }


class MemoryStore:
    """Transport fake; production authorization is tested by the store suite."""
    def __init__(self, multiple=False):
        self.config = project_config()
        self.assignments = [
            {"id": "a", "user_id": "u", "project_id": "p", "project_name": "내 프로젝트", "config": self.config, "active": True}
        ]
        if multiple:
            self.assignments.append({"id": "b", "user_id": "u", "project_id": "p2", "project_name": "다른 프로젝트", "config": self.config, "active": True})
        self.records = {}
        self.fail_next = False
        self.calls = []

    def list_assignments(self, token):
        return copy.deepcopy(self.assignments)

    def load_assessment(self, token, assignment_id, phase):
        return copy.deepcopy(self.records.get((assignment_id, phase)))

    def save_assessment(self, token, assignment_id, phase, payload, completed):
        self.calls.append((assignment_id, phase, copy.deepcopy(payload), completed))
        if self.fail_next:
            self.fail_next = False
            raise ValueError("저장 연결을 다시 확인해 주세요.")
        prior = self.records.get((assignment_id, phase))
        if prior and prior["completed"]:
            raise ValueError("이미 제출된 응답입니다.")
        record = {"assignment_id": assignment_id, "phase": phase, "payload": copy.deepcopy(payload), "completed": completed, "completed_at": 1 if completed else None}
        self.records[assignment_id, phase] = record
        return copy.deepcopy(record)


def participant_app(store):
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from tap.account_assessment_ui import render_participant\n"
        "render_participant(st.session_state['store'], 'session-token', "
        "{'id': 'u', 'display_name': '테스트 참여자', 'role': 'participant'})\n",
        default_timeout=30,
    )
    app.session_state["store"] = store
    return app.run()


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    if app.exception:
        raise AssertionError(str(app.exception))


def answer(app, value):
    next(radio for radio in app.radio if radio.label == "응답").set_value(value)
    next(button for button in app.button if button.label.startswith("저장하고")).click().run()
    if app.exception:
        raise AssertionError(str(app.exception))


class AccountAssessmentTests(unittest.TestCase):
    def test_scope_change_drops_old_widgets(self):
        state = {"auth": "keep", PREFIX + "owner": "old", PREFIX + "selector": "a", PREFIX + "pre_response_Q": 4}
        _reset_scope(state, "new")
        self.assertEqual(state, {"auth": "keep", PREFIX + "owner": "new"})
        state[PREFIX + "selector"] = "b"
        state[PREFIX + "phase"] = "post"
        _reset_scope(state, "new", "b")
        self.assertNotIn(PREFIX + "phase", state)
        self.assertEqual(state[PREFIX + "selector"], "b")

    def test_snapshot_and_cross_assignment_record_rejected(self):
        config = project_config()
        self.assertEqual([q["question_code"] for q in _project_questions(config)], config["question_snapshot_codes"])
        config["question_snapshot_hash"] = "changed"
        with self.assertRaises(ValueError):
            _project_questions(config)
        with self.assertRaises(ValueError):
            _checked_record({"assignment_id": "another", "phase": "pre", "payload": {}, "completed": False}, "a", "pre", {"Q1"})

    def test_db_resume_zero_option_and_failed_final_submit(self):
        store = MemoryStore()
        app = participant_app(store)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.selectbox), 0)
        self.assertEqual(len(app.text_input), 0)
        answer(app, 0)
        first = store.config["question_snapshot_codes"][0]
        self.assertEqual(store.records["a", "pre"]["payload"]["responses"][first], 0)
        app = participant_app(store)
        self.assertTrue(any("문항 2/" in caption.value for caption in app.caption))
        for _ in range(len(store.config["question_snapshot_codes"]) - 1):
            answer(app, 4)
        self.assertFalse(store.records["a", "pre"]["completed"])
        store.fail_next = True
        click(app, "교육 전 검사 최종 제출")
        self.assertFalse(store.records["a", "pre"]["completed"])
        self.assertTrue(app.error)
        click(app, "교육 전 검사 최종 제출")
        self.assertTrue(store.records["a", "pre"]["completed"])
        self.assertTrue(app.dataframe)
        self.assertFalse(any(r.label == "응답" for r in app.radio))

    def test_post_prelinked_transfer_draft_resume_and_comparison(self):
        store = MemoryStore()
        store.records["a", "pre"] = {
            "assignment_id": "a", "phase": "pre", "completed": True,
            "payload": {"responses": {code: 3 for code in store.config["question_snapshot_codes"]}},
        }
        app = participant_app(store)
        self.assertEqual(next(r for r in app.radio if r.label == "검사 단계").value, "post")
        for _ in store.config["question_snapshot_codes"]:
            answer(app, 4)
        click(app, "교육 후 검사 최종 제출")
        self.assertFalse(store.records["a", "post"]["completed"])
        self.assertTrue(app.error)
        for key, label in TRANSFER_ITEMS:
            next(r for r in app.radio if r.label == label).set_value(5)
        click(app, "현업전이 응답 임시저장")
        self.assertFalse(store.records["a", "post"]["completed"])
        app = participant_app(store)
        for key, label in TRANSFER_ITEMS:
            self.assertEqual(next(r for r in app.radio if r.label == label).value, 5)
        click(app, "교육 후 검사 최종 제출")
        self.assertTrue(store.records["a", "post"]["completed"])
        comparison = app.dataframe[0].value
        self.assertEqual(float(comparison.iloc[0]["관찰 변화"]), 1.0)

    def test_assignment_switch_cannot_reuse_response_widgets(self):
        store = MemoryStore(multiple=True)
        app = participant_app(store)
        answer(app, 2)
        app.selectbox[0].set_value("b").run()
        self.assertFalse(app.exception)
        self.assertIsNone(next(r for r in app.radio if r.label == "응답").value)
        answer(app, 5)
        app.selectbox[0].set_value("a").run()
        self.assertFalse(app.exception)
        self.assertTrue(any("문항 2/" in caption.value for caption in app.caption))
        first = store.config["question_snapshot_codes"][0]
        self.assertEqual(store.records["a", "pre"]["payload"]["responses"][first], 2)
        self.assertEqual(store.records["b", "pre"]["payload"]["responses"][first], 5)


if __name__ == "__main__":
    unittest.main()
