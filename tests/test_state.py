import unittest

from tap.state import (
    DEMO_STORE_ACCESS_CODE_KEY,
    DEMO_STORE_ACCESS_CODE_WIDGET_KEY,
    DEMO_STORE_REPORT_PREVIEW_CODE_KEY,
    DEMO_STORE_REPORT_PREVIEW_CODE_WIDGET_KEY,
    PARTICIPANT_ID_WIDGET_KEY,
    activate_company_scope,
    activate_assessment_phase,
    ensure_state,
    load_demo_store_access_code_widget,
    load_demo_store_report_preview_code_widget,
    load_participant_id_widget,
    reset_all_assessments,
    reset_assessment,
    save_demo_store_access_code_widget,
    save_demo_store_report_preview_code_widget,
    save_participant_id_widget,
    sync_assessment_phase,
)


class StateTests(unittest.TestCase):
    def test_fresh_state_requires_participant_id_and_neutralizes_legacy_cause(self):
        state = {"training_cause": "system_only"}
        ensure_state(state)
        self.assertEqual("", state["participant_id"])
        self.assertEqual("mixed_or_unknown", state["training_cause"])
        self.assertEqual("", state["company_id"])
        self.assertFalse(state["company_scope_verified"])

    def test_company_scope_keeps_only_safe_identity_fields(self):
        state = {}
        ensure_state(state)
        activate_company_scope(
            state,
            company_id="co_" + "a" * 64,
            company_name="한국능률협회",
            identity_source="kma_assigned_code",
            access_digest="cad_" + "b" * 64,
        )

        self.assertEqual("co_" + "a" * 64, state["company_id"])
        self.assertEqual("한국능률협회", state["company_name"])
        self.assertTrue(state["company_scope_verified"])
        self.assertNotIn("business_registration_number", state)
        self.assertNotIn("company_admin_access_code", state)

    def test_company_switch_clears_project_and_assessment_scope(self):
        state = {
            "company_id": "co_" + "a" * 64,
            "company_name": "A사",
            "company_identity_source": "kma_assigned_code",
            "company_scope_verified": True,
            "project_id": "TAP-OLD",
            "participant_id": "P001",
            "selected_factors": ["CORE-CO"],
            "responses_by_phase": {"pre": {"Q1": 4}, "post": {"Q1": 5}},
            "assessment_completed_by_phase": {"pre": True, "post": True},
            "organization_report_project_choice": "store:TAP-OLD",
        }
        ensure_state(state)
        activate_company_scope(
            state,
            company_id="co_" + "c" * 64,
            company_name="B사",
            identity_source="business_registration_number",
            access_digest="cad_" + "d" * 64,
        )

        self.assertEqual("", state["project_id"])
        self.assertEqual("", state["participant_id"])
        self.assertEqual([], state["selected_factors"])
        self.assertEqual({"pre": {}, "post": {}}, state["responses_by_phase"])
        self.assertNotIn("organization_report_project_choice", state)

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

    def test_participant_id_survives_widget_cleanup_between_phases(self):
        state = {}
        ensure_state(state)
        load_participant_id_widget(state)
        state[PARTICIPANT_ID_WIDGET_KEY] = "  EDU-P001  "
        save_participant_id_widget(state)

        # Streamlit removes widget-owned state on page navigation. The durable
        # value must still be available when the post assessment is opened.
        del state[PARTICIPANT_ID_WIDGET_KEY]
        activate_assessment_phase(state, "post")

        self.assertEqual("EDU-P001", state["participant_id"])
        self.assertEqual("EDU-P001", load_participant_id_widget(state))
        self.assertEqual("EDU-P001", state[PARTICIPANT_ID_WIDGET_KEY])

    def test_demo_access_code_survives_widget_cleanup_between_pages(self):
        state = {}
        ensure_state(state)
        load_demo_store_access_code_widget(state)
        state[DEMO_STORE_ACCESS_CODE_WIDGET_KEY] = "  demo-code  "
        save_demo_store_access_code_widget(state)

        # Dedicated pre/post pages own separate Streamlit widgets. Simulate
        # leaving one page by removing only the disposable widget key.
        del state[DEMO_STORE_ACCESS_CODE_WIDGET_KEY]
        activate_assessment_phase(state, "post")

        self.assertEqual("demo-code", state[DEMO_STORE_ACCESS_CODE_KEY])
        self.assertEqual("demo-code", load_demo_store_access_code_widget(state))
        self.assertEqual("demo-code", state[DEMO_STORE_ACCESS_CODE_WIDGET_KEY])

    def test_report_preview_code_has_separate_durable_widget_state(self):
        state = {}
        ensure_state(state)
        load_demo_store_report_preview_code_widget(state)
        state[DEMO_STORE_REPORT_PREVIEW_CODE_WIDGET_KEY] = "  report-only-code  "
        save_demo_store_report_preview_code_widget(state)

        del state[DEMO_STORE_REPORT_PREVIEW_CODE_WIDGET_KEY]
        activate_assessment_phase(state, "post")

        self.assertEqual("", state[DEMO_STORE_ACCESS_CODE_KEY])
        self.assertEqual(
            "report-only-code", state[DEMO_STORE_REPORT_PREVIEW_CODE_KEY]
        )
        self.assertEqual(
            "report-only-code", load_demo_store_report_preview_code_widget(state)
        )
        self.assertEqual(
            "report-only-code", state[DEMO_STORE_REPORT_PREVIEW_CODE_WIDGET_KEY]
        )


if __name__ == "__main__":
    unittest.main()
