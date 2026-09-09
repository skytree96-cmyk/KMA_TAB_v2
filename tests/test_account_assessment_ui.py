from __future__ import annotations

import copy
import hashlib
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tap.account_assessment_ui import PREFIX, TRANSFER_ITEMS, _checked_record, _project_questions, _reset_scope
from tap.data import questions_for_factors
import tap.account_assessment_ui as assessment_ui


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
        self.reads = []

    def list_assignments(self, token):
        self.reads.append(("assignments", token))
        rows = copy.deepcopy(self.assignments)
        for row in rows:
            for phase in ("pre", "post"):
                row[phase + "_completed"] = bool(self.records.get((row["id"], phase), {}).get("completed"))
        return rows

    def load_assessment(self, token, assignment_id, phase):
        self.reads.append(("assessment", assignment_id, phase))
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
        state = {"auth": "keep", PREFIX + "owner": "old", PREFIX + "selector": "a", PREFIX + "pre_response_Q": 4,
                 PREFIX + "saved_record": {"owner": "old", "record": {"payload": {"responses": {"Q": 4}}}}}
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

    def test_next_renders_only_the_new_question_with_three_store_calls(self):
        store = MemoryStore()
        app = participant_app(store)
        questions = _project_questions(store.config)
        question_texts = {q["revised_text"] for q in questions}
        before_reads = len(store.reads)
        with patch.object(assessment_ui.st, "subheader", wraps=assessment_ui.st.subheader) as titles:
            answer(app, 4)
        # This observes intermediate reruns, not just AppTest's final DOM. The
        # old handler rendered [old question, new question] on every click.
        rendered = [call.args[0] for call in titles.call_args_list if call.args and call.args[0] in question_texts]
        self.assertEqual(rendered, [questions[1]["revised_text"]])
        self.assertEqual(store.reads[before_reads:], [("assessment", "a", "pre"), ("assignments", "session-token")])
        self.assertEqual(len(store.calls), 1)
        self.assertNotIn(PREFIX + "saved_record", app.session_state)
        # A receipt is single-use. An independent rerun reauthorizes the
        # assignment and reloads the active draft; no persistent data cache.
        before_reads = len(store.reads)
        app.run()
        self.assertEqual(store.reads[before_reads:], [("assignments", "session-token"), ("assessment", "a", "pre")])

    def test_failed_question_save_preserves_position_choice_and_retry(self):
        store = MemoryStore()
        app = participant_app(store)
        store.fail_next = True
        answer(app, 5)
        self.assertTrue(app.error)
        self.assertNotIn(("a", "pre"), store.records)
        self.assertEqual(app.session_state[PREFIX + "pre_cursor"], 0)
        self.assertEqual(next(r for r in app.radio if r.label == "응답").value, 5)
        self.assertNotIn(PREFIX + "saved_record", app.session_state)
        self.assertTrue(any("문항 1/" in caption.value for caption in app.caption))
        click(app, "저장하고 다음 문항 →")
        self.assertEqual(app.session_state[PREFIX + "pre_cursor"], 1)
        self.assertEqual(store.records["a", "pre"]["payload"]["responses"][store.config["question_snapshot_codes"][0]], 5)

    def test_mismatched_saved_position_does_not_advance(self):
        store = MemoryStore()
        app = participant_app(store)
        save = store.save_assessment

        def wrong_receipt(*args):
            receipt = save(*args)
            receipt["payload"]["current_question"] = 0
            return receipt

        with patch.object(store, "save_assessment", side_effect=wrong_receipt):
            answer(app, 3)
        self.assertTrue(app.error)
        self.assertEqual(app.session_state[PREFIX + "pre_cursor"], 0)
        self.assertEqual(next(r for r in app.radio if r.label == "응답").value, 3)
        self.assertNotIn(PREFIX + "saved_record", app.session_state)

    def test_submission_merges_latest_draft_instead_of_overwriting_other_answers(self):
        store = MemoryStore()
        app = participant_app(store)
        codes = store.config["question_snapshot_codes"]
        # Simulate another browser saving after this form was first rendered.
        store.records["a", "pre"] = {"assignment_id": "a", "phase": "pre", "completed": False,
                                     "payload": {"responses": {codes[2]: 2}, "current_question": 0}}
        answer(app, 4)
        self.assertEqual(store.records["a", "pre"]["payload"]["responses"], {codes[0]: 4, codes[2]: 2})

    def test_phase_and_assignment_switch_do_not_use_an_unrelated_receipt(self):
        store = MemoryStore(multiple=True)
        app = participant_app(store)
        answer(app, 4)
        old_receipt = {"owner": app.session_state[PREFIX + "owner"], "record": copy.deepcopy(store.records["a", "pre"])}
        app.session_state[PREFIX + "saved_record"] = old_receipt
        before_reads = len(store.reads)
        next(r for r in app.radio if r.label == "검사 단계").set_value("post").run()
        self.assertIn(("assessment", "a", "post"), store.reads[before_reads:])
        self.assertNotIn(PREFIX + "saved_record", app.session_state)
        app.session_state[PREFIX + "saved_record"] = old_receipt
        before_reads = len(store.reads)
        app.selectbox[0].set_value("b").run()
        self.assertIn(("assessment", "b", "pre"), store.reads[before_reads:])
        self.assertIsNone(next(r for r in app.radio if r.label == "응답").value)
        self.assertNotIn(PREFIX + "saved_record", app.session_state)

    def test_concurrent_final_submission_invalidates_the_draft_receipt(self):
        store = MemoryStore()
        app = participant_app(store)
        save = store.save_assessment

        def save_then_other_browser_submits(*args):
            receipt = save(*args)
            # The draft commit succeeded, then another browser completed the
            # same assessment before the callback's following assignment read.
            record = store.records["a", "pre"]
            record["payload"]["responses"] = {code: 4 for code in store.config["question_snapshot_codes"]}
            record["completed"] = True
            record["completed_at"] = 2
            return receipt

        before_reads = len(store.reads)
        with patch.object(store, "save_assessment", side_effect=save_then_other_browser_submits):
            answer(app, 4)
        self.assertEqual(store.reads[before_reads:], [
            ("assessment", "a", "pre"), ("assignments", "session-token"), ("assessment", "a", "pre"),
        ])
        self.assertTrue(app.dataframe)
        self.assertIn("나의 교육 전 검사 결과", [title.value for title in app.subheader])
        self.assertFalse(any(r.label == "응답" for r in app.radio))
        self.assertNotIn(PREFIX + "saved_record", app.session_state)

    def test_snapshot_order_and_previous_navigation_keep_question_identity(self):
        store = MemoryStore()
        store.config["question_snapshot_codes"].reverse()
        app = participant_app(store)
        questions = _project_questions(store.config)
        for index in range(3):
            self.assertIn(questions[index]["revised_text"], [title.value for title in app.subheader])
            answer(app, index)
        click(app, "← 이전 문항")
        self.assertIn(questions[2]["revised_text"], [title.value for title in app.subheader])
        self.assertEqual(next(r for r in app.radio if r.label == "응답").value, 2)
        answer(app, 5)
        self.assertIn(questions[3]["revised_text"], [title.value for title in app.subheader])
        responses = store.records["a", "pre"]["payload"]["responses"]
        self.assertEqual(responses, {questions[0]["question_code"]: 0, questions[1]["question_code"]: 1, questions[2]["question_code"]: 5})


if __name__ == "__main__":
    unittest.main()


class FrozenQuestionTextTests(unittest.TestCase):
    def test_assigned_edited_text_is_used_and_tampering_rejected(self):
        from copy import deepcopy
        config = project_config()
        questions = deepcopy(questions_for_factors(config["selected_factors"]))
        questions[0]["revised_text"] = "새 프로젝트에 확정된 운영 문구입니다."
        config["question_snapshot"] = questions
        snapshot = sorted((q["question_code"], q["revised_text"], q.get("scoring_direction", "direct")) for q in questions)
        digest = hashlib.sha256("\n".join("|".join(row) for row in snapshot).encode()).hexdigest()
        config["question_snapshot_hash"] = digest
        config["assessment_version"] = "TAP-1.0+" + digest[:12]
        self.assertEqual(_project_questions(config)[0]["revised_text"], questions[0]["revised_text"])
        questions[0]["revised_text"] = "해시와 다른 문구"
        with self.assertRaises(ValueError):
            _project_questions(config)
