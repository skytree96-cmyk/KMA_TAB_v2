import unittest

from tap.state import (
    activate_assessment_phase,
    ensure_state,
    reset_all_assessments,
    reset_assessment,
    sync_assessment_phase,
)


class StateTests(unittest.TestCase):
    def test_legacy_flat_responses_migrate_to_pre(self):
        state = {
            "responses": {"Q1": 4},
            "current_question": 1,
            "assessment_completed": True,
            "assessment_started_at": 10.0,
            "duration_seconds": 20.0,
        }
        ensure_state(state)
        self.assertEqual(state["responses_by_phase"]["pre"], {"Q1": 4})
        self.assertEqual(state["current_question_by_phase"]["pre"], 1)
        self.assertTrue(state["assessment_completed_by_phase"]["pre"])
        self.assertIs(state["responses"], state["responses_by_phase"]["pre"])

    def test_phase_switch_preserves_independent_progress(self):
        state = {}
        ensure_state(state)
        state["responses"]["Q1"] = 3
        state["current_question"] = 2
        state["assessment_completed"] = True
        sync_assessment_phase(state)

        activate_assessment_phase(state, "post")
        self.assertEqual(state["responses"], {})
        state["responses"]["Q1"] = 5
        state["current_question"] = 1
        sync_assessment_phase(state)

        activate_assessment_phase(state, "pre")
        self.assertEqual(state["responses"], {"Q1": 3})
        self.assertEqual(state["current_question"], 2)
        self.assertTrue(state["assessment_completed"])
        activate_assessment_phase(state, "post")
        self.assertEqual(state["responses"], {"Q1": 5})
        self.assertEqual(state["current_question"], 1)

    def test_sync_preserves_new_progress_after_timer_has_started(self):
        state = {}
        ensure_state(state)
        state["assessment_started_at"] = 10.0
        sync_assessment_phase(state)

        # A populated phase map previously caused ensure_state() inside sync
        # to restore question 0 before the new cursor could be saved.
        state["responses"]["Q1"] = 3
        state["current_question"] = 1
        sync_assessment_phase(state)

        self.assertEqual(state["current_question"], 1)
        self.assertEqual(state["current_question_by_phase"]["pre"], 1)
        self.assertEqual(state["responses_by_phase"]["pre"], {"Q1": 3})

    def test_reset_current_phase_does_not_clear_other_phase(self):
        state = {}
        ensure_state(state)
        state["responses_by_phase"]["pre"] = {"Q1": 3}
        state["responses_by_phase"]["post"] = {"Q1": 5}
        activate_assessment_phase(state, "post")
        reset_assessment(state)
        self.assertEqual(state["responses_by_phase"]["pre"], {"Q1": 3})
        self.assertEqual(state["responses_by_phase"]["post"], {})

    def test_reset_all_returns_to_pre_and_clears_transfer(self):
        state = {}
        ensure_state(state)
        state["responses_by_phase"]["pre"] = {"Q1": 3}
        state["responses_by_phase"]["post"] = {"Q1": 5}
        state["post_transfer_responses"] = {"opportunity": 4}
        reset_all_assessments(state)
        self.assertEqual(state["assessment_phase"], "pre")
        self.assertEqual(state["responses_by_phase"], {"pre": {}, "post": {}})
        self.assertEqual(state["post_transfer_responses"], {})

    def test_map_only_restore_keeps_phase_progress(self):
        state = {
            "assessment_phase": "post",
            "responses_by_phase": {"pre": {"Q1": 3}, "post": {"Q1": 5}},
            "current_question_by_phase": {"pre": 1, "post": 2},
            "assessment_started_at_by_phase": {"pre": 10.0, "post": 20.0},
            "assessment_completed_by_phase": {"pre": True, "post": True},
            "duration_seconds_by_phase": {"pre": 30.0, "post": 40.0},
        }
        ensure_state(state)
        self.assertEqual(state["current_question"], 2)
        self.assertTrue(state["assessment_completed"])
        self.assertEqual(state["assessment_started_at"], 20.0)
        self.assertEqual(state["duration_seconds"], 40.0)

    def test_reset_does_not_start_future_phase_timer(self):
        state = {}
        ensure_state(state)
        reset_all_assessments(state)
        self.assertIsNone(state["assessment_started_at_by_phase"]["pre"])
        self.assertIsNone(state["assessment_started_at_by_phase"]["post"])


if __name__ == "__main__":
    unittest.main()
