from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from tap.company_scope_ui import CompanyScopeView
from tap.github_demo_store import DemoStoreConfig
from tap.tenant import derive_company_identity, hash_company_access_code


ROOT = Path(__file__).resolve().parents[1]


class CompanyScopeUiTests(unittest.TestCase):
    def setUp(self) -> None:
        st.cache_data.clear()
        self.business_number = "123-45-67890"
        self.business_proof = "1234567890"
        self.config = DemoStoreConfig(
            enabled=True,
            owner="example",
            repo="tap-demo",
            token="test-token",
            salt="tenant-test-salt",
            participant_access_code="participant-test-code",
        )
        self.identity = derive_company_identity(
            salt=self.config.salt,
            company_name="테스트 기업",
            business_registration_number=self.business_number,
        )
        self.digest = hash_company_access_code(
            self.identity.company_id,
            self.business_proof,
            self.config.salt,
        )
        self.registry = {
            "company_id": self.identity.company_id,
            "company_name": self.identity.company_name,
            "company_identity_source": self.identity.identity_source,
            "company_access_digest": self.digest,
            "approval_status": "approved",
        }
        self.store = MagicMock()
        self.store.status.return_value = {
            "read_enabled": True,
            "project_write_enabled": True,
        }
        self.store.load_company.return_value = self.registry
        self.store.list_projects.return_value = []
        self.store.list_submissions.return_value = []
        self.config_patch = patch(
            "tap.github_demo_store.DemoStoreConfig.from_sources",
            return_value=self.config,
        )
        self.store_patch = patch(
            "tap.github_demo_store.GitHubDemoStore", return_value=self.store
        )
        self.scope_store_patch = patch(
            "tap.company_scope_ui.GitHubDemoStore", return_value=self.store
        )
        self.config_patch.start()
        self.store_class = self.store_patch.start()
        self.scope_store_class = self.scope_store_patch.start()

    def tearDown(self) -> None:
        self.scope_store_patch.stop()
        self.store_patch.stop()
        self.config_patch.stop()
        st.cache_data.clear()

    def _manager_app(self) -> AppTest:
        return AppTest.from_file(
            str(ROOT / "pages" / "9_manager_dashboard.py"), default_timeout=30
        ).run()

    def _report_app(self) -> AppTest:
        return AppTest.from_file(
            str(ROOT / "pages" / "4_organization_report.py"), default_timeout=30
        ).run()

    @staticmethod
    def _fill_scope(
        app: AppTest,
        *,
        company_name: str = "테스트 기업",
        business_number: str = "123-45-67890",
    ) -> None:
        next(item for item in app.text_input if item.label == "회사명").set_value(
            company_name
        )
        next(
            item for item in app.text_input if item.label == "사업자등록번호"
        ).set_value(business_number)
        next(
            item for item in app.button if item.label == "회사 확인·참여 요청"
        ).click()

    def test_scope_repr_never_exposes_raw_business_number(self) -> None:
        scope = CompanyScopeView(
            verified=True,
            company_id=self.identity.company_id,
            company_name=self.identity.company_name,
            identity_source=self.identity.identity_source,
            access_digest=self.digest,
            approval_status="approved",
            access_code=self.business_proof,
        )
        self.assertNotIn(self.business_proof, repr(scope))

    def test_manager_gate_uses_only_company_name_and_business_number(self) -> None:
        app = self._manager_app()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertEqual(
            {"회사명", "사업자등록번호"},
            {item.label for item in app.text_input},
        )
        self.assertTrue(
            any(item.label == "회사 확인·참여 요청" for item in app.button)
        )
        old_labels = {
            "KMA 부여 기업코드",
            "기업 관리자 확인코드",
            "KMA 신규기업 등록 승인코드",
            "프로젝트 저장용 기업 관리자 확인코드",
        }
        self.assertTrue(old_labels.isdisjoint({item.label for item in app.text_input}))

    def test_manager_page_does_not_list_before_company_verification(self) -> None:
        app = self._manager_app()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.store.load_company.assert_not_called()
        self.store.request_company_registration.assert_not_called()
        self.store.list_projects.assert_not_called()
        self.store.list_submissions.assert_not_called()

    def test_unregistered_company_requests_pending_without_listing_data(self) -> None:
        self.store.load_company.return_value = None
        self.store.request_company_registration.return_value = {
            **self.registry,
            "approval_status": "pending",
        }
        app = self._manager_app()
        self._fill_scope(app)
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertFalse(bool(app.session_state["company_scope_verified"]))
        self.store.load_company.assert_called_once_with(self.identity.company_id)
        self.store.request_company_registration.assert_called_once_with(
            self.identity.to_payload(), self.digest
        )
        self.scope_store_class.assert_any_call(
            self.config, company_access_code=self.business_proof
        )
        self.store.list_projects.assert_not_called()
        self.store.list_submissions.assert_not_called()
        self.assertTrue(
            any("승인 후 다시 확인" in str(item.value) for item in app.success)
        )
        request_args = repr(self.store.request_company_registration.call_args)
        self.assertNotIn(self.business_number, request_args)
        self.assertNotIn(self.business_proof, request_args)

    def test_pending_company_stays_locked_without_repeating_request(self) -> None:
        self.store.load_company.return_value = {
            **self.registry,
            "approval_status": "pending",
        }
        app = self._manager_app()
        self._fill_scope(app)
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertFalse(bool(app.session_state["company_scope_verified"]))
        self.store.request_company_registration.assert_not_called()
        self.store.list_projects.assert_not_called()
        self.store.list_submissions.assert_not_called()
        self.assertTrue(any("승인 대기" in str(item.value) for item in app.info))

    def test_rejected_company_stays_locked_and_shows_review_note(self) -> None:
        self.store.load_company.return_value = {
            **self.registry,
            "approval_status": "rejected",
            "review_note": "사업자 정보 재확인",
        }
        app = self._manager_app()
        self._fill_scope(app)
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertFalse(bool(app.session_state["company_scope_verified"]))
        self.store.request_company_registration.assert_not_called()
        self.store.list_projects.assert_not_called()
        self.store.list_submissions.assert_not_called()
        self.assertTrue(
            any("사업자 정보 재확인" in str(item.value) for item in app.error)
        )

    def test_approved_company_uses_only_company_scoped_store_lists(self) -> None:
        app = self._manager_app()
        self._fill_scope(app)
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertTrue(app.session_state["company_scope_verified"])
        self.assertEqual(self.identity.company_id, app.session_state["company_id"])
        self.assertEqual(
            "business_registration",
            app.session_state["company_identity_source"],
        )
        self.assertEqual(self.digest, app.session_state["company_access_digest"])
        self.assertNotIn("business_registration_number", app.session_state)
        self.assertNotIn("company_admin_access_code", app.session_state)
        self.store.request_company_registration.assert_not_called()
        self.store.list_projects.assert_called_with(company_id=self.identity.company_id)
        self.store.list_submissions.assert_called_with(company_id=self.identity.company_id)

    def test_different_business_number_cannot_open_approved_company(self) -> None:
        app = self._manager_app()
        self._fill_scope(app, business_number="999-88-77777")
        app.run()

        wrong_identity = derive_company_identity(
            salt=self.config.salt,
            company_name=self.identity.company_name,
            business_registration_number="9998877777",
        )
        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertFalse(bool(app.session_state["company_scope_verified"]))
        self.store.load_company.assert_called_once_with(wrong_identity.company_id)
        self.store.list_projects.assert_not_called()
        self.store.list_submissions.assert_not_called()
        self.assertTrue(
            any("기존 기업 확인방식과 일치하지 않습니다" in str(item.value) for item in app.error)
        )

    def test_verified_scope_is_revoked_when_company_is_no_longer_approved(self) -> None:
        app = self._manager_app()
        app.session_state["company_id"] = self.identity.company_id
        app.session_state["company_name"] = self.identity.company_name
        app.session_state["company_identity_source"] = self.identity.identity_source
        app.session_state["company_access_digest"] = self.digest
        app.session_state["company_scope_verified"] = True
        self.store.load_company.return_value = {
            **self.registry,
            "approval_status": "pending",
        }
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertFalse(bool(app.session_state["company_scope_verified"]))
        self.assertEqual("", app.session_state["company_access_digest"])
        self.store.list_projects.assert_not_called()
        self.store.list_submissions.assert_not_called()
        self.assertTrue(
            any("승인 상태가 변경" in str(item.value) for item in app.warning)
        )

    def test_report_page_queries_only_after_approved_company_scope(self) -> None:
        app = self._report_app()
        self.store.list_projects.assert_not_called()
        self.store.list_submissions.assert_not_called()

        app.session_state["company_id"] = self.identity.company_id
        app.session_state["company_name"] = self.identity.company_name
        app.session_state["company_identity_source"] = self.identity.identity_source
        app.session_state["company_access_digest"] = self.digest
        app.session_state["company_scope_verified"] = True
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.store.load_company.assert_called_with(self.identity.company_id)
        self.store.list_projects.assert_called_with(company_id=self.identity.company_id)
        self.store.list_submissions.assert_called_with(company_id=self.identity.company_id)


if __name__ == "__main__":
    unittest.main()
