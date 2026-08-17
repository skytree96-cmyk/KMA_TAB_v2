from __future__ import annotations

import base64
import json
import unittest
from copy import deepcopy
from urllib.parse import unquote, urlsplit

from tap.github_demo_store import (
    DemoStoreConfig,
    DemoStoreError,
    GitHubDemoStore,
    participant_key,
    project_payload_from_state,
    submission_payload_from_state,
)


class FakeTransport:
    """In-memory GitHub Contents API used by the tests; no network calls."""

    def __init__(self) -> None:
        self.files: dict[str, dict[str, object]] = {}
        self.requests: list[dict[str, object]] = []
        self.conflicts_remaining = 0
        self.conflict_replacement: tuple[str, dict[str, object]] | None = None
        self.sha_counter = 0

    @staticmethod
    def _path(url: str) -> str:
        api_path = urlsplit(url).path
        return unquote(api_path.split("/contents/", 1)[1]).strip("/")

    def seed(self, path: str, payload: dict[str, object]) -> None:
        self.sha_counter += 1
        self.files[path] = {"payload": deepcopy(payload), "sha": f"sha-{self.sha_counter}"}

    def request(self, method: str, url: str, *, headers, body=None):
        path = self._path(url)
        decoded_body = json.loads(body.decode("utf-8")) if body else None
        self.requests.append(
            {
                "method": method,
                "path": path,
                "url": url,
                "headers": dict(headers),
                "body": decoded_body,
            }
        )

        if method == "GET":
            if path in self.files:
                record = self.files[path]
                raw = json.dumps(record["payload"], ensure_ascii=False).encode("utf-8")
                return {
                    "status": 200,
                    "json": {
                        "type": "file",
                        "path": path,
                        "name": path.rsplit("/", 1)[-1],
                        "sha": record["sha"],
                        "encoding": "base64",
                        "content": base64.b64encode(raw).decode("ascii"),
                    },
                }
            prefix = path.rstrip("/") + "/"
            children: dict[str, dict[str, str]] = {}
            for file_path in self.files:
                if not file_path.startswith(prefix):
                    continue
                remainder = file_path[len(prefix) :]
                first, separator, _ = remainder.partition("/")
                child_path = prefix + first
                children[first] = {
                    "type": "dir" if separator else "file",
                    "name": first,
                    "path": child_path,
                }
            if children:
                return {"status": 200, "json": list(children.values())}
            return {"status": 404, "json": {"message": "Not Found"}}

        if method == "PUT":
            if self.conflicts_remaining:
                self.conflicts_remaining -= 1
                if self.conflict_replacement is not None:
                    replacement_path, replacement_payload = self.conflict_replacement
                    self.conflict_replacement = None
                    self.seed(replacement_path, replacement_payload)
                return {"status": 409, "json": {"message": "conflict"}}
            existing = self.files.get(path)
            if existing and decoded_body.get("sha") != existing["sha"]:
                return {"status": 409, "json": {"message": "sha mismatch"}}
            raw = base64.b64decode(decoded_body["content"])
            payload = json.loads(raw.decode("utf-8"))
            self.sha_counter += 1
            sha = f"sha-{self.sha_counter}"
            self.files[path] = {"payload": payload, "sha": sha}
            return {
                "status": 200 if existing else 201,
                "json": {"content": {"sha": sha}},
            }
        raise AssertionError(f"unexpected method: {method}")


def project_state() -> dict[str, object]:
    return {
        "project_id": "TAP-DEMO-001",
        "project_name": "합성 리더십 교육",
        "course_name": "공통역량 교육",
        "project_start_date": "2026-08-01",
        "project_end_date": "2026-11-30",
        "target_level": "manager",
        "training_date": "2026-09-01",
        "pre_start_date": "2026-08-17",
        "pre_end_date": "2026-08-28",
        "post_start_date": "2026-10-27",
        "post_end_date": "2026-11-10",
        "allow_schedule_override": True,
        "target_means": {"CORE-CO": 4.2},
        "organization_priorities": ["CORE-CO"],
        "learner_interests": ["CORE-PB"],
        "training_cause": "mixed_or_unknown",
        "delivery_preference": "all",
        "selected_factors": ["CORE-CO", "CORE-PB"],
        "assessment_version": "TAP-1.0",
        "question_snapshot_hash": "a" * 64,
        "question_snapshot_codes": ["Q1", "Q2"],
    }


def submission_state(*, post_complete: bool = False) -> dict[str, object]:
    state = project_state()
    state.update(
        {
            "participant_id": "TEST-EMPLOYEE-007",
            "responses_by_phase": {
                "pre": {"Q1": 2, "Q2": 3},
                "post": {"Q1": 4, "Q2": 5} if post_complete else {},
            },
            "assessment_started_at_by_phase": {
                "pre": "2026-08-20T01:00:00Z",
                "post": "2026-10-30T01:00:00Z" if post_complete else None,
            },
            "assessment_completed_by_phase": {"pre": True, "post": post_complete},
            "assessment_completed_at_by_phase": {
                "pre": "2026-08-20",
                "post": "2026-10-30" if post_complete else None,
            },
            "duration_seconds_by_phase": {"pre": 320, "post": 290 if post_complete else None},
            "post_transfer_responses": (
                {
                    "application_opportunity": 4,
                    "supervisor_support": 4,
                    "resources_authority": 3,
                    "time_process_support": 3,
                    "barriers": ["시간·프로세스 제약"],
                    "applied_content": "GitHub 저장에서 제외되는 합성 자유서술",
                }
                if post_complete
                else {}
            ),
        }
    )
    return state


class GitHubDemoStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = FakeTransport()
        self.config = DemoStoreConfig(
            enabled=True,
            owner="kma-demo",
            repo="tap-planning",
            token="fake-token",
            salt="test-only-salt",
            access_code="test-access-code",
        )
        self.store = GitHubDemoStore(
            self.config,
            transport=self.transport,
            access_code="test-access-code",
        )

    def test_config_sources_and_public_read_status(self) -> None:
        config = DemoStoreConfig.from_sources(
            secrets={
                "github_demo_store": {
                    "enabled": False,
                    "owner": "secret-owner",
                    "repo": "secret-repo",
                    "token": "secret-token",
                    "participant_hash_salt": "secret-salt",
                    "access_code": "secret-access-code",
                    "admin_preview_code": "secret-preview-code",
                }
            },
            environ={
                "GITHUB_DEMO_STORE_ENABLED": "true",
                "TAP_DEMO_GITHUB_OWNER": "env-owner",
                "TAP_DEMO_GITHUB_REPO": "env-repo",
                "TAP_DEMO_GITHUB_BRANCH": "demo-data",
            },
        )
        self.assertEqual("env-owner", config.owner)
        self.assertEqual("env-repo", config.repo)
        self.assertEqual("secret-token", config.token)
        self.assertEqual("secret-salt", config.salt)
        self.assertTrue(config.access_granted("secret-access-code"))
        self.assertTrue(config.report_preview_granted("secret-preview-code"))
        self.assertFalse(config.report_preview_granted("secret-access-code"))
        self.assertTrue(config.enabled)
        self.assertTrue(config.read_enabled)
        self.assertTrue(config.write_enabled)

        public = GitHubDemoStore(
            DemoStoreConfig(enabled=True, owner="public", repo="demo", salt="salt"),
            transport=self.transport,
        )
        self.assertTrue(public.status()["read_enabled"])
        self.assertFalse(public.status()["write_enabled"])
        self.assertEqual("tap-demo/v1", public.status()["root_path"])

    def test_config_accepts_repository_slug_and_rejects_partial_config(self) -> None:
        config = DemoStoreConfig.from_sources(
            secrets=None,
            environ={
                "GITHUB_DEMO_STORE_ENABLED": "true",
                "GITHUB_DEMO_STORE_REPOSITORY": "sample-owner/sample-repo",
                "GITHUB_DEMO_STORE_BRANCH": "demo-data",
                "GITHUB_DEMO_STORE_TOKEN": "token",
                "GITHUB_DEMO_STORE_PARTICIPANT_SALT": "salt",
                "GITHUB_DEMO_STORE_ACCESS_CODE": "access-code",
                "GITHUB_DEMO_STORE_REPORT_PREVIEW_CODE": "preview-code",
            },
        )
        self.assertEqual(("sample-owner", "sample-repo"), (config.owner, config.repo))
        self.assertEqual("demo-data", config.branch)
        self.assertEqual("token", config.token)
        self.assertEqual("salt", config.salt)
        self.assertTrue(config.access_granted("access-code"))
        self.assertTrue(config.report_preview_granted("preview-code"))
        with self.assertRaisesRegex(DemoStoreError, "enabled=true"):
            DemoStoreConfig(enabled=True)

    def test_disabled_config_never_calls_network_even_when_repository_is_present(self) -> None:
        disabled_config = DemoStoreConfig(
            enabled=False,
            owner="configured-owner",
            repo="configured-repo",
            token="unused-token",
        )
        store = GitHubDemoStore(disabled_config, transport=self.transport)
        self.assertTrue(store.status()["configured"])
        self.assertFalse(store.status()["enabled"])
        self.assertFalse(store.status()["read_enabled"])
        self.assertFalse(store.status()["write_enabled"])
        with self.assertRaisesRegex(DemoStoreError, "비활성화"):
            store.list_projects()
        self.assertEqual([], self.transport.requests)

    def test_enabled_secret_boolean_and_invalid_boolean_are_validated(self) -> None:
        disabled = DemoStoreConfig.from_sources(
            secrets={
                "github_demo_store": {
                    "enabled": False,
                    "owner": "owner",
                    "repo": "repo",
                }
            },
            environ={},
        )
        self.assertFalse(disabled.enabled)
        with self.assertRaisesRegex(DemoStoreError, "true/false"):
            DemoStoreConfig.from_sources(
                secrets=None,
                environ={"GITHUB_DEMO_STORE_ENABLED": "sometimes"},
            )

    def test_participant_key_is_stable_scoped_and_non_reversible(self) -> None:
        first = participant_key("TAP-DEMO-001", " EMP-007 ", "secret")
        second = participant_key("TAP-DEMO-001", "EMP-007", "secret")
        other_project = participant_key("TAP-DEMO-002", "EMP-007", "secret")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other_project)
        self.assertRegex(first, r"^p_[0-9a-f]{64}$")
        self.assertNotIn("EMP-007", first)
        with self.assertRaises(DemoStoreError):
            participant_key("TAP-DEMO-001", "EMP-007", "")

    def test_access_code_blocks_write_until_the_correct_code_is_supplied(self) -> None:
        project = project_payload_from_state(project_state())
        missing = GitHubDemoStore(self.config, transport=self.transport)
        self.assertFalse(missing.status()["write_enabled"])
        with self.assertRaisesRegex(DemoStoreError, "접속코드"):
            missing.save_project(project)

        wrong = GitHubDemoStore(
            self.config,
            transport=self.transport,
            access_code="wrong-code",
        )
        self.assertFalse(wrong.status()["write_enabled"])
        with self.assertRaisesRegex(DemoStoreError, "접속코드"):
            wrong.save_project(project)
        self.assertEqual([], [row for row in self.transport.requests if row["method"] == "PUT"])

        allowed = GitHubDemoStore(
            self.config,
            transport=self.transport,
            access_code="test-access-code",
        )
        self.assertTrue(allowed.status()["write_enabled"])
        allowed.save_project(project)
        self.assertEqual(1, len([row for row in self.transport.requests if row["method"] == "PUT"]))

    def test_report_preview_code_fallback_and_read_only_gate(self) -> None:
        fallback = DemoStoreConfig(
            enabled=True,
            owner="public",
            repo="demo",
            access_code="legacy-code",
        )
        self.assertFalse(fallback.write_enabled)
        self.assertTrue(fallback.report_preview_granted("legacy-code"))
        self.assertFalse(fallback.report_preview_granted("wrong-code"))

        separate = DemoStoreConfig(
            enabled=True,
            owner="public",
            repo="demo",
            token="private-token",
            salt="private-salt",
            access_code="legacy-code",
            report_preview_code="preview-only-code",
        )
        self.assertTrue(separate.report_preview_granted("preview-only-code"))
        self.assertFalse(separate.report_preview_granted("legacy-code"))
        self.assertNotIn("legacy-code", repr(separate))
        self.assertNotIn("preview-only-code", repr(separate))
        self.assertNotIn("private-token", repr(separate))
        self.assertNotIn("private-salt", repr(separate))

        disabled = DemoStoreConfig(
            enabled=False,
            owner="public",
            repo="demo",
            report_preview_code="preview-only-code",
        )
        self.assertFalse(disabled.report_preview_granted("preview-only-code"))

    def test_project_builder_is_allowlisted_and_restorable(self) -> None:
        state = project_state()
        state["participant_id"] = "MUST-NOT-LEAK"
        state["responses"] = {"Q1": 5}
        payload = project_payload_from_state(state)
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertTrue(payload["demo_only"])
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual("project", payload["record_type"])
        self.assertEqual(["CORE-CO", "CORE-PB"], payload["selected_factors"])
        self.assertEqual(["Q1", "Q2"], payload["question_snapshot_codes"])
        self.assertNotIn("MUST-NOT-LEAK", encoded)
        self.assertNotIn("responses", payload)

    def test_submission_builder_never_contains_raw_participant_id(self) -> None:
        state = submission_state(post_complete=True)
        payload = submission_payload_from_state(state, salt=self.config.salt)
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("TEST-EMPLOYEE-007", encoded)
        self.assertNotIn("participant_id", encoded)
        self.assertEqual({"pre", "post"}, set(payload["phases"]))
        self.assertEqual({"Q1": 2, "Q2": 3}, payload["phases"]["pre"]["responses"])
        self.assertEqual({"Q1": 4, "Q2": 5}, payload["phases"]["post"]["responses"])
        self.assertEqual(4, payload["transition_responses"]["application_opportunity"])
        self.assertNotIn("applied_content", payload["transition_responses"])
        self.assertEqual("a" * 64, payload["instrument"]["question_snapshot_hash"])

    def test_exact_paths_base64_branch_and_update_sha(self) -> None:
        project = project_payload_from_state(project_state())
        saved = self.store.save_project(project)
        project_path = "tap-demo/v1/projects/TAP-DEMO-001.json"
        self.assertEqual(project_path, self.transport.requests[-1]["path"])
        self.assertEqual("demo-data", self.transport.requests[-1]["body"]["branch"])
        self.assertNotIn("sha", self.transport.requests[-1]["body"])
        self.assertTrue(saved["demo_only"])

        project["project_name"] = "수정된 합성 프로젝트"
        self.store.save_project(project)
        self.assertEqual(project_path, self.transport.requests[-1]["path"])
        self.assertIn("sha", self.transport.requests[-1]["body"])
        decoded = json.loads(
            base64.b64decode(self.transport.requests[-1]["body"]["content"]).decode("utf-8")
        )
        self.assertEqual("수정된 합성 프로젝트", decoded["project_name"])

    def test_submission_upsert_merges_pre_and_post_in_one_file(self) -> None:
        pre_payload = submission_payload_from_state(
            submission_state(post_complete=False), salt=self.config.salt
        )
        first = self.store.save_submission(pre_payload)
        path = (
            "tap-demo/v1/submissions/TAP-DEMO-001/"
            f"{pre_payload['participant_key']}.json"
        )
        self.assertEqual(path, self.transport.requests[-1]["path"])
        self.assertTrue(first["phases"]["pre"]["completed"])
        self.assertFalse(first["phases"]["post"]["completed"])

        post_payload = submission_payload_from_state(
            submission_state(post_complete=True), salt=self.config.salt
        )
        merged = self.store.save_submission(post_payload)
        self.assertEqual({"Q1": 2, "Q2": 3}, merged["phases"]["pre"]["responses"])
        self.assertEqual({"Q1": 4, "Q2": 5}, merged["phases"]["post"]["responses"])
        self.assertTrue(merged["phases"]["pre"]["completed"])
        self.assertTrue(merged["phases"]["post"]["completed"])
        self.assertIn("sha", self.transport.requests[-1]["body"])
        self.assertEqual(4, merged["transition_responses"]["application_opportunity"])
        self.assertEqual(1, len(self.transport.files))

    def test_completed_phase_cannot_be_erased_by_incomplete_snapshot(self) -> None:
        complete = submission_payload_from_state(
            submission_state(post_complete=True), salt=self.config.salt
        )
        self.store.save_submission(complete)
        stale = submission_payload_from_state(
            submission_state(post_complete=False), salt=self.config.salt
        )
        merged = self.store.save_submission(stale)
        self.assertTrue(merged["phases"]["post"]["completed"])
        self.assertEqual({"Q1": 4, "Q2": 5}, merged["phases"]["post"]["responses"])

    def test_completed_pre_response_cannot_change_from_two_to_five(self) -> None:
        original = submission_payload_from_state(
            submission_state(post_complete=False), salt=self.config.salt
        )
        self.store.save_submission(original)

        changed = deepcopy(original)
        changed["phases"]["pre"]["responses"]["Q1"] = 5
        with self.assertRaisesRegex(DemoStoreError, "participant-ID collision"):
            self.store.save_submission(changed)

        stored = self.store.load_submission(
            original["project_id"], original["participant_key"]
        )
        self.assertEqual(2, stored["phases"]["pre"]["responses"]["Q1"])

    def test_identical_completed_retry_ignores_recreated_timing_metadata(self) -> None:
        original = submission_payload_from_state(
            submission_state(post_complete=True), salt=self.config.salt
        )
        first = self.store.save_submission(original)

        retry = deepcopy(original)
        retry["phases"]["pre"].update(
            {
                "started_at": "2099-01-01T00:00:00Z",
                "completed_at": "2099-01-01",
                "duration_seconds": 999,
            }
        )
        retry["phases"]["post"].update(
            {
                "started_at": "2099-02-01T00:00:00Z",
                "completed_at": "2099-02-01",
                "duration_seconds": 888,
            }
        )
        retry["updated_at"] = "2099-02-01T00:00:00Z"
        merged = self.store.save_submission(retry)

        self.assertEqual(first["phases"], merged["phases"])
        self.assertEqual(first["transition_responses"], merged["transition_responses"])

    def test_completed_post_transition_response_is_immutable(self) -> None:
        original = submission_payload_from_state(
            submission_state(post_complete=True), salt=self.config.salt
        )
        self.store.save_submission(original)

        changed = deepcopy(original)
        changed["transition_responses"]["supervisor_support"] = 1
        with self.assertRaisesRegex(DemoStoreError, "participant-ID collision"):
            self.store.save_submission(changed)

    def test_concurrent_409_refetch_rejects_conflicting_completion(self) -> None:
        incoming = submission_payload_from_state(
            submission_state(post_complete=False), salt=self.config.salt
        )
        competing = deepcopy(incoming)
        competing["phases"]["pre"]["responses"]["Q1"] = 5
        path = (
            "tap-demo/v1/submissions/TAP-DEMO-001/"
            f"{incoming['participant_key']}.json"
        )
        self.transport.conflicts_remaining = 1
        self.transport.conflict_replacement = (path, competing)

        with self.assertRaisesRegex(DemoStoreError, "participant-ID collision"):
            self.store.save_submission(incoming)

        puts = [row for row in self.transport.requests if row["method"] == "PUT"]
        gets = [row for row in self.transport.requests if row["method"] == "GET"]
        self.assertEqual(1, len(puts))
        self.assertEqual(2, len(gets))
        self.assertEqual(5, self.transport.files[path]["payload"]["phases"]["pre"]["responses"]["Q1"])

    def test_conflict_is_refetched_and_retried_at_most_three_times(self) -> None:
        self.transport.conflicts_remaining = 3
        payload = project_payload_from_state(project_state())
        self.store.save_project(payload)
        puts = [row for row in self.transport.requests if row["method"] == "PUT"]
        gets = [row for row in self.transport.requests if row["method"] == "GET"]
        self.assertEqual(4, len(puts))
        self.assertEqual(4, len(gets))

        exhausted_transport = FakeTransport()
        exhausted_transport.conflicts_remaining = 4
        exhausted_store = GitHubDemoStore(
            self.config,
            transport=exhausted_transport,
            access_code="test-access-code",
        )
        with self.assertRaisesRegex(DemoStoreError, "3회 재시도"):
            exhausted_store.save_project(payload)
        exhausted_puts = [
            row for row in exhausted_transport.requests if row["method"] == "PUT"
        ]
        self.assertEqual(4, len(exhausted_puts))

    def test_public_read_works_without_token_but_write_requires_token(self) -> None:
        project = project_payload_from_state(project_state())
        path = "tap-demo/v1/projects/TAP-DEMO-001.json"
        self.transport.seed(path, project)
        public = GitHubDemoStore(
            DemoStoreConfig(enabled=True, owner="public", repo="repo"),
            transport=self.transport,
        )
        loaded = public.load_project("TAP-DEMO-001")
        self.assertEqual("TAP-DEMO-001", loaded["project_id"])
        self.assertNotIn("Authorization", self.transport.requests[-1]["headers"])
        with self.assertRaisesRegex(DemoStoreError, "token"):
            public.save_project(project)

    def test_list_projects_and_submissions_load_valid_payloads(self) -> None:
        project = project_payload_from_state(project_state())
        submission = submission_payload_from_state(
            submission_state(post_complete=True), salt=self.config.salt
        )
        self.store.save_project(project)
        self.store.save_submission(submission)
        projects = self.store.list_projects()
        submissions = self.store.list_submissions("TAP-DEMO-001")
        all_submissions = self.store.list_submissions()
        self.assertEqual(["TAP-DEMO-001"], [row["project_id"] for row in projects])
        self.assertEqual([submission["participant_key"]], [row["participant_key"] for row in submissions])
        self.assertEqual(submissions, all_submissions)

    def test_validation_blocks_direct_identifier_and_per_question_write(self) -> None:
        payload = submission_payload_from_state(
            submission_state(post_complete=False), salt=self.config.salt
        )
        payload["participant_id"] = "RAW-ID"
        with self.assertRaisesRegex(DemoStoreError, "직접 식별자"):
            self.store.save_submission(payload)

        incomplete_state = submission_state(post_complete=False)
        incomplete_state["assessment_completed_by_phase"] = {"pre": False, "post": False}
        incomplete = submission_payload_from_state(incomplete_state, salt=self.config.salt)
        with self.assertRaisesRegex(DemoStoreError, "문항별 저장"):
            self.store.save_submission(incomplete)

    def test_validation_rejects_bad_response_and_bad_project_path(self) -> None:
        bad_state = submission_state()
        bad_state["responses_by_phase"] = {"pre": {"Q1": 9}, "post": {}}
        with self.assertRaisesRegex(DemoStoreError, "0~5"):
            submission_payload_from_state(bad_state, salt=self.config.salt)
        with self.assertRaises(DemoStoreError):
            project_payload_from_state({"project_id": "../../escape"})

        duplicate_factors = project_state()
        duplicate_factors["selected_factors"] = ["CORE-CO", "CORE-CO"]
        with self.assertRaisesRegex(DemoStoreError, "중복 없는"):
            project_payload_from_state(duplicate_factors)

    def test_completed_snapshot_requires_all_items_and_pre_before_post(self) -> None:
        partial = submission_state(post_complete=False)
        partial["responses_by_phase"] = {"pre": {"Q1": 3}, "post": {}}
        with self.assertRaisesRegex(DemoStoreError, "모든 문항"):
            submission_payload_from_state(partial, salt=self.config.salt)

        post_only = submission_state(post_complete=True)
        post_only["assessment_completed_by_phase"] = {"pre": False, "post": True}
        with self.assertRaisesRegex(DemoStoreError, "교육 전 결과"):
            submission_payload_from_state(post_only, salt=self.config.salt)

    def test_existing_submission_rejects_different_instrument(self) -> None:
        original = submission_payload_from_state(
            submission_state(post_complete=False), salt=self.config.salt
        )
        self.store.save_submission(original)
        changed = deepcopy(original)
        changed["instrument"]["assessment_version"] = "TAP-CHANGED"
        with self.assertRaisesRegex(DemoStoreError, "검사 버전"):
            self.store.save_submission(changed)


if __name__ == "__main__":
    unittest.main()
