from __future__ import annotations

import unittest

from tap.account_consent import CONSENT_SECTIONS, consent_html, has_consent
from tap.account_store import (ACCESS_LOG_RETENTION_DAYS, PRIVACY_CONSENT_ITEMS, PRIVACY_CONSENT_VERSION,
                               AuthorizationError, ValidationError, hash_password)
from tests import test_account_assessment_ui as ui_tests
from tests import test_account_store as store_tests


class ConsentStoreTests(unittest.TestCase):
    setUp = store_tests.AccountStoreTests.setUp
    user = store_tests.AccountStoreTests.user
    project = store_tests.AccountStoreTests.project
    payload = store_tests.AccountStoreTests.payload

    @classmethod
    def setUpClass(cls):
        cls.seed_hash = hash_password(store_tests.INITIAL)

    def test_no_answer_is_stored_before_both_agreements(self):
        record, token = self.user(consent=False)
        project = self.project()
        assignment = self.store.assign_participant(self.admin, project["id"], record["id"])
        self.assertEqual(self.store.principal(token)["privacy_consent_version"], "")
        with self.assertRaises(AuthorizationError):
            self.store.save_assessment(token, assignment["id"], "pre", self.payload(project), False)
        self.assertIsNone(self.store.load_assessment(token, assignment["id"], "pre"))
        for version, items in ((PRIVACY_CONSENT_VERSION, PRIVACY_CONSENT_ITEMS[:1]), ("2025-01", PRIVACY_CONSENT_ITEMS),
                               (PRIVACY_CONSENT_VERSION, ())):
            with self.assertRaises(ValidationError):
                self.store.record_privacy_consent(token, version, items)

        self.now += 60
        agreed = self.store.record_privacy_consent(token, PRIVACY_CONSENT_VERSION, PRIVACY_CONSENT_ITEMS, client="203.0.113.7")
        principal = self.store.principal(token)
        self.assertEqual(principal["privacy_consent_version"], PRIVACY_CONSENT_VERSION)
        self.assertEqual(principal["privacy_consent_at"], agreed["privacy_consent_at"])
        self.assertTrue(agreed["privacy_consent_at"].startswith("2026-09-08T09:01"))  # KST
        saved = self.store.save_assessment(token, assignment["id"], "pre", self.payload(project), True)
        self.assertTrue(saved["completed"])
        events = self.store.access_events(self.admin, 0, self.now + 1)
        consent = next(event for event in events if event["event"] == "privacy_consent")
        self.assertEqual((consent["actor_login"], consent["ip"]), (record["login_id"], "203.0.113.7"))

    def test_only_a_participant_agrees_for_themself(self):
        _, manager = self.user("company", suffix="mgr")
        with self.assertRaises(AuthorizationError):
            self.store.record_privacy_consent(manager, PRIVACY_CONSENT_VERSION, PRIVACY_CONSENT_ITEMS)
        with self.assertRaises(AuthorizationError):
            self.store.record_privacy_consent(self.admin, PRIVACY_CONSENT_VERSION, PRIVACY_CONSENT_ITEMS)

    def test_access_records_older_than_two_years_are_deleted(self):
        _, manager = self.user("company", suffix="mgr")
        self.store.login("mgr", store_tests.CHANGED, client="198.51.100.1")
        self.now += (ACCESS_LOG_RETENTION_DAYS - 1) * 86_400
        self.assertEqual(self.store.purge_expired_access_logs(), 0)
        self.store.login("mgr", store_tests.CHANGED, client="198.51.100.2")
        self.now += 2 * 86_400
        removed = self.store.purge_expired_access_logs()
        self.assertGreater(removed, 0)
        admin = self.store.login("kma-admin", store_tests.CHANGED)  # the setUp session expired long ago
        left = self.store.access_events(admin, 0, self.now + 1)
        self.assertEqual([event["ip"] for event in left if event["event"] == "login" and event["actor_login"] == "mgr"],
                         ["198.51.100.2"])
        self.assertEqual(self.store.purge_expired_access_logs(), 0)


class ConsentScreenTests(unittest.TestCase):
    def test_notice_names_each_agreement_and_the_policy_but_not_the_storage_abroad(self):
        page = consent_html()
        self.assertEqual(page.count('class="tap-consent__box"'), 2)
        for _, title, rows in CONSENT_SECTIONS:
            self.assertIn(title, page)
            self.assertTrue(any(label == "보유 기간" or "보유 기간" in label for label, _ in rows))
        for hidden in ("국외", "일본", "Google"):
            self.assertNotIn(hidden, page)  # disclosed in the privacy policy, not asked on screen
        self.assertIn("https://membership.kma.or.kr/privacy.html", page)
        self.assertIn("동의하지 않으면 TAP 검사를 할 수 없습니다", page)
        self.assertFalse(has_consent({"privacy_consent_version": "2025-01"}))
        self.assertTrue(has_consent({"privacy_consent_version": PRIVACY_CONSENT_VERSION}))

    def test_first_test_starts_with_the_consent_and_no_question(self):
        store = ui_tests.MemoryStore()
        store.consent = {"privacy_consent_version": ""}
        app = ui_tests.participant_app(store)
        self.assertFalse(app.radio)  # no question yet
        agree = next(button for button in app.button if button.label == "동의하고 검사 시작")
        self.assertTrue(agree.disabled)
        boxes = list(app.checkbox)
        self.assertEqual(len(boxes), 2)
        boxes[0].check()
        app.run()
        self.assertTrue(next(button for button in app.button if button.label == "동의하고 검사 시작").disabled)
        app.checkbox[1].check()
        app.run()
        ui_tests.click(app, "동의하고 검사 시작")
        self.assertEqual(store.consents, [(PRIVACY_CONSENT_VERSION, PRIVACY_CONSENT_ITEMS)])
        self.assertTrue(app.radio)  # the first question follows at once
        self.assertEqual(store.calls, [])  # agreeing stores no answer


if __name__ == "__main__":
    unittest.main()
