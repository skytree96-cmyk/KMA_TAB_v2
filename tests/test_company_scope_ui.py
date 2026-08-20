from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from tap.company_scope_ui import CompanyScopeView
from tap.github_demo_store import DemoStoreConfig
from tap.tenant import (
    derive_company_identity,
    hash_company_access_code,
    verify_company_access_code,
)


ROOT = Path(__file__).resolve().parents[1]


class CompanyScopeUiTests(unittest.TestCase):
    def setUp(self) -> None:
        st.cache_data.clear()
        self.admin_code = "company-admin-2026"
        self.config = DemoStoreConfig(
            enabled=True,
            owner="example",
            repo="tap-demo",
            token="test-token",
            salt="tenant-test-salt",
            participant_access_code="participant-test-code",
            company_access_code="kma-bootstrap-code",
        )
        self.identity = derive_company_identity(
            salt=self.config.salt,
            company_name="테스트 기업",
            kma_assigned_code="KMAA001",
        )
        self.digest = hash_company_access_code(
            self.identity.company_id,
            self.admin_code,
            self.config.salt,
        )
        self.registry = {
            "company_id": self.identity.company_id,
            "company_name": self.identity.company_name,
            "company_identity_source": self.identity.identity_source,
            "company_access_digest": self.digest,
        }
        self.store = MagicMock()
        self.store.status.return_value = {
            "read_enabled": True,
            "project_write_enabled": True,
        }
        self.store.load_company.return_value = self.registry
        self.store.list_projects.return_value = []
        self.store.list_submissions.return_value = []
        self.patches = (
            patch(
                "tap.github_demo_store.DemoStoreConfig.from_sources",
                return_value=self.config,
            ),
            patch("tap.github_demo_store.GitHubDemoStore", return_value=self.store),
            patch("tap.company_scope_ui.GitHubDemoStore", return_value=self.store),
        )
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
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
    def _fill_scope(app: AppTest, admin_code: str) -> None:
        next(item for item in app.text_input if item.label == "회사명").set_value(
            "테스트 기업"
        )
        next(
            item
            for item in app.text_input
            if item.label == "KMA 부여 기업코드"
        ).set_value("KMAA001")
        next(
            item
            for item in app.text_input
            if item.label == "기업 관리자 확인코드"
        ).set_value(admin_code)
        next(item for item in app.button if item.label == "기업 범위 확인").click()

    def test_scope_repr_never_exposes_raw_admin_code(self) -> None:
        scope = CompanyScopeView(
            verified=True,
            company_id=self.identity.company_id,
            company_name=self.identity.company_name,
            identity_source=self.identity.identity_source,
            access_digest=self.digest,
            access_code="DO-NOT-EXPOSE",
        )
        self.assertNotIn("DO-NOT-EXPOSE", repr(scope))

    def test_same_kma_bootstrap_does_not_become_every_company_admin_code(self) -> None:
        other_identity = derive_company_identity(
            salt=self.config.salt,
            company_name="다른 기업",
            kma_assigned_code="KMAB002",
        )
        other_admin_code = "other-company-admin-2026"
        other_digest = hash_company_access_code(
            other_identity.company_id,
            other_admin_code,
            self.config.salt,
        )

        self.assertFalse(
            verify_company_access_code(
                other_identity.company_id,
                self.config.company_code,
                other_digest,
                self.config.salt,
            )
        )
        self.assertFalse(
            verify_company_access_code(
                other_identity.company_id,
                self.admin_code,
                other_digest,
                self.config.salt,
            )
        )
        self.assertTrue(
            verify_company_access_code(
                other_identity.company_id,
                other_admin_code,
                other_digest,
                self.config.salt,
            )
        )

    def test_participant_code_cannot_be_reused_as_company_admin_code(self) -> None:
        digest = hash_company_access_code(
            self.identity.company_id,
            self.config.participant_code,
            self.config.salt,
        )
        self.assertTrue(
            verify_company_access_code(
                self.identity.company_id,
                self.config.participant_code,
                digest,
                self.config.salt,
            )
        )
        # The cryptographic primitive accepts any valid code; the UI gate must
        # additionally reject this role collision before consulting registry
        # data. The source assertion keeps that separation explicit.
        source = (ROOT / "tap" / "company_scope_ui.py").read_text(encoding="utf-8")
        self.assertIn("config.participant_code", source)
        self.assertIn(
            "기업 관리자 확인코드는 참여자 접속코드와 다르게",
            source,
        )

        self.store.load_company.return_value = {
            **self.registry,
            "company_access_digest": digest,
        }
        app = self._manager_app()
        self._fill_scope(app, self.config.participant_code)
        app.run()
        self.assertFalse(app.session_state["company_scope_verified"])
        self.store.list_projects.assert_not_called()
        self.assertTrue(
            any(
                "참여자 접속코드와 다르게" in item.value
                for item in app.error
            )
        )

    def test_unicode_equivalent_participant_code_is_rejected_without_page_error(self) -> None:
        fullwidth_participant_code = "ｐａｒｔｉｃｉｐａｎｔ－ｔｅｓｔ－ｃｏｄｅ"
        app = self._manager_app()
        self._fill_scope(app, fullwidth_participant_code)
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertFalse(app.session_state["company_scope_verified"])
        self.store.load_company.assert_not_called()
        self.store.list_projects.assert_not_called()
        self.assertTrue(
            any("참여자 접속코드와 다르게" in item.value for item in app.error)
        )

    def test_non_ascii_company_admin_code_verifies_without_type_error(self) -> None:
        korean_admin_code = "기업관리코드"
        self.store.load_company.return_value = {
            **self.registry,
            "company_access_digest": hash_company_access_code(
                self.identity.company_id,
                korean_admin_code,
                self.config.salt,
            ),
        }
        app = self._manager_app()
        self._fill_scope(app, korean_admin_code)
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertTrue(app.session_state["company_scope_verified"])
        self.store.list_projects.assert_called_with(company_id=self.identity.company_id)
        self.store.list_submissions.assert_called_with(company_id=self.identity.company_id)

    def test_manager_page_does_not_list_projects_before_company_verification(self) -> None:
        app = self._manager_app()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.store.load_company.assert_not_called()
        self.store.list_projects.assert_not_called()
        self.store.list_submissions.assert_not_called()
        self.assertTrue(any(item.label == "기업 범위 확인" for item in app.button))

    def test_report_page_queries_only_after_verified_company_scope(self) -> None:
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
        self.store.list_projects.assert_called_with(company_id=self.identity.company_id)
        self.store.list_submissions.assert_called_with(company_id=self.identity.company_id)

    def test_wrong_company_admin_code_keeps_project_data_hidden(self) -> None:
        app = self._manager_app()
        self._fill_scope(app, "wrong-company-code")
        app.run()

        self.assertFalse(bool(app.session_state["company_scope_verified"]))
        self.store.load_company.assert_called_once_with(self.identity.company_id)
        self.store.list_projects.assert_not_called()
        self.store.list_submissions.assert_not_called()
        self.assertTrue(
            any("기업 관리자 확인코드가 일치하지 않습니다" in item.value for item in app.error)
        )

    def test_verified_company_uses_only_company_scoped_store_lists(self) -> None:
        app = self._manager_app()
        self._fill_scope(app, self.admin_code)
        app.run()

        self.assertEqual([], [str(item.value) for item in app.exception])
        self.assertTrue(app.session_state["company_scope_verified"])
        self.assertEqual(self.identity.company_id, app.session_state["company_id"])
        self.store.list_projects.assert_called_with(company_id=self.identity.company_id)
        self.store.list_submissions.assert_called_with(company_id=self.identity.company_id)
        self.assertNotEqual(
            self.admin_code, app.session_state["company_access_digest"]
        )


if __name__ == "__main__":
    unittest.main()
