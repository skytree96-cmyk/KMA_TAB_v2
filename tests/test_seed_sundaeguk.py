from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.seed_sundaeguk import COMPANY, FACTORS, MANAGER, PARTICIPANTS, seed_company
from tap.account_reports import export_report_pdf, summarize_project
from tap.account_store import AccountStore, ConflictError, hash_password


class SundaegukSeedTests(unittest.TestCase):
    def setUp(self):
        self.fast_hash = patch("tap.account_store._SCRYPT_N", 16)
        self.fast_hash.start()
        self.addCleanup(self.fast_hash.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "seed.sqlite")
        now = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc).timestamp()
        self.store = AccountStore("sqlite:///" + self.path, allow_sqlite_for_tests=True, clock=lambda: now)
        self.store.initialize()
        self.store.bootstrap_admin("seed.admin", hash_password("initial"))
        self.admin = self.store.change_password(self.store.login("seed.admin", "initial"), "initial", "changed")

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as conn:
            return list(conn.iterdump())

    def test_counts_full_paired_reports_scope_and_temporary_passwords(self):
        seeded = seed_company(self.store)
        self.assertTrue(seeded["created"])
        self.assertEqual((seeded["total"], seeded["pre_completed"], seeded["post_completed"], seeded["nonparticipants"]), (15, 5, 5, 10))
        project = next(p for p in self.store.list_projects(self.admin) if p["id"] == seeded["project_id"])
        results = self.store.project_results(self.admin, project["id"])
        summaries = summarize_project(project, results)
        self.assertEqual({row["factor_code"] for row in summaries}, set(FACTORS))
        self.assertTrue(all(row["paired_n"] == 5 and row["pre_mean"] is not None and row["post_mean"] is not None for row in summaries))
        self.assertTrue(export_report_pdf(self.store, self.admin, project).startswith(b"%PDF"))
        summary = self.store.dashboard_summary(self.admin)
        company = next(c for c in summary["company_participation"] if c["company_name"] == COMPANY)
        self.assertEqual((company["total"], company["participating"], company["pre_completed"], company["post_completed"]), (15, 5, 5, 5))
        initial = self.store.login(MANAGER, "kma")
        self.assertTrue(self.store.principal(initial)["must_change_password"])
        manager = self.store.change_password(initial, "kma", "testing")
        self.assertEqual([p["id"] for p in self.store.list_projects(manager)], [project["id"]])
        self.assertEqual(len(self.store.project_results(manager, project["id"])), 15)
        users = [u for u in self.store.list_users(self.admin) if u["role"] == "participant"]
        self.assertEqual({u["login_id"] for u in users}, set(PARTICIPANTS))
        self.assertTrue(all(u["must_change_password"] for u in users))

    def test_rerun_preserves_every_record_and_existing_sessions(self):
        with closing(sqlite3.connect(self.path)) as conn:
            before_sessions = conn.execute("SELECT * FROM tap_sessions").fetchall()
        first = seed_company(self.store)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT * FROM tap_sessions").fetchall(), before_sessions)
        before = self.snapshot()
        second = seed_company(self.store)
        self.assertFalse(second["created"])
        self.assertEqual(first["project_id"], second["project_id"])
        self.assertEqual(before, self.snapshot())

    def test_foreign_company_or_login_collision_never_overwrites(self):
        company = self.store.create_company(self.admin, "기존 회사", "1234567890")
        self.store.create_user(self.admin, PARTICIPANTS[0], "기존 사용자", "participant", company["id"], "original")
        before = self.snapshot()
        with self.assertRaises(ConflictError):
            seed_company(self.store)
        self.assertEqual(before, self.snapshot())

    def test_same_name_unmarked_company_is_not_adopted(self):
        self.store.create_company(self.admin, COMPANY, "0000000001")
        before = self.snapshot()
        with self.assertRaises(ConflictError):
            seed_company(self.store)
        self.assertEqual(before, self.snapshot())

    def test_mid_seed_failure_rolls_back_company_users_sessions_and_answers(self):
        original = AccountStore.save_assessment
        calls = 0
        def fail_on_second(store, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Injected validation failure")
            return original(store, *args, **kwargs)
        before = self.snapshot()
        with patch.object(AccountStore, "save_assessment", fail_on_second):
            with self.assertRaises(RuntimeError):
                seed_company(self.store)
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
