from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tap.account_store import AccountStore
from tap.ai_budget import (FEATURES, MONTHLY_APP_LIMIT_USD, call_cost_micros, max_call_micros, to_micros,
                           usage_cost_micros)
from tap.ai_client import BILLING_PAUSE_SECONDS, generate

ON = {"TAP_AI_ENABLED": "1", "ANTHROPIC_API_KEY": "test-key"}


class FakeStatusError(Exception):
    def __init__(self, status_code, message="", error_type=""):
        super().__init__(message)
        self.status_code = status_code
        self.body = {"type": "error", "error": {"type": error_type, "message": message}}


class FakeClient:
    def __init__(self, *, response=None, error=None):
        self.calls = []
        self.response = response
        self.error = error
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def reply(text="해설 문장입니다.", *, stop="end_turn", input_tokens=15_000, output_tokens=2_000):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        stop_reason=stop,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                              cache_creation_input_tokens=0, cache_read_input_tokens=0),
    )


class BudgetPlanTests(unittest.TestCase):
    def test_plan_fits_one_hundred_dollars_with_vat(self):
        app = sum(feature.monthly_usd for feature in FEATURES.values())
        self.assertLessEqual(app, MONTHLY_APP_LIMIT_USD)
        development_key, reserve = 15.0, 25.0
        self.assertLessEqual((MONTHLY_APP_LIMIT_USD + development_key + reserve) * 1.10, 100.0)

    def test_worst_case_per_call(self):
        self.assertEqual(max_call_micros(FEATURES["report_commentary"]), to_micros(0.08))
        self.assertEqual(max_call_micros(FEATURES["course_tagging"]), to_micros(0.027))
        self.assertEqual(max_call_micros(FEATURES["question_review"]), to_micros(0.046))
        # 500 commentaries at the ceiling exactly use the allocation.
        self.assertEqual(500 * max_call_micros(FEATURES["report_commentary"]), to_micros(40.0))

    def test_usage_cost_never_understates_cache(self):
        usage = SimpleNamespace(input_tokens=1_000, cache_creation_input_tokens=10_000,
                                cache_read_input_tokens=0, output_tokens=0)
        cost, tokens, _ = usage_cost_micros("claude-sonnet-5-5", usage)
        self.assertEqual(cost, call_cost_micros("claude-sonnet-5-5", 21_000, 0))
        self.assertEqual(tokens, 11_000)


class GuardedCallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = datetime(2026, 11, 23, 3, 0, tzinfo=timezone.utc).timestamp()
        self.store = AccountStore("sqlite:///" + str(Path(self.tmp.name) / "ai.sqlite"),
                                  allow_sqlite_for_tests=True, clock=lambda: self.now)
        self.store.initialize()

    def call(self, client, **kwargs):
        options = {"system": "규칙", "prompt": "집계 수치", "project_id": "p1"} | kwargs
        return generate(self.store, kwargs.pop("feature", "report_commentary"), client_factory=lambda: client,
                        **{key: value for key, value in options.items() if key != "feature"})

    def test_off_by_default_and_without_key(self):
        client = FakeClient(response=reply())
        with mock.patch.dict(os.environ, {"TAP_AI_ENABLED": "", "ANTHROPIC_API_KEY": ""}):
            self.assertIsNone(self.call(client))
        with mock.patch.dict(os.environ, {"TAP_AI_ENABLED": "1", "ANTHROPIC_API_KEY": ""}):
            self.assertIsNone(self.call(client))
        self.assertEqual(client.calls, [])
        self.assertEqual(self.store.ai_month_usage(), {})

    def test_success_settles_actual_cost_and_reuses_stored_result(self):
        client = FakeClient(response=reply())
        with mock.patch.dict(os.environ, ON):
            first = self.call(client, cache_key="project-p1-v3")
            second = self.call(client, cache_key="project-p1-v3")
        self.assertEqual(first.text, "해설 문장입니다.")
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual((call["model"], call["max_tokens"]), ("claude-sonnet-5-5", 4_000))
        self.assertEqual(self.store.ai_month_usage(), {"report_commentary": call_cost_micros("claude-sonnet-5-5", 15_000, 2_000)})

    def test_stored_result_still_served_when_credit_is_gone(self):
        self.store.ai_store_result("report_commentary", "k", "저장된 해설")
        self.store.ai_pause(self.now + BILLING_PAUSE_SECONDS, "billing")
        with mock.patch.dict(os.environ, {"TAP_AI_ENABLED": "", "ANTHROPIC_API_KEY": ""}):
            self.assertEqual(self.call(FakeClient(), cache_key="k").text, "저장된 해설")

    def test_credit_exhausted_pauses_without_charging(self):
        for error in (FakeStatusError(400, "Your credit balance is too low to access the Anthropic API.", "invalid_request_error"),
                      FakeStatusError(402, "payment required", "billing_error")):
            with self.subTest(status=error.status_code):
                self.store.ai_pause(0, "")
                failing = FakeClient(error=error)
                with mock.patch.dict(os.environ, ON):
                    self.assertIsNone(self.call(failing))
                    healthy = FakeClient(response=reply())
                    self.assertIsNone(self.call(healthy))  # paused: no call at all
                self.assertEqual(healthy.calls, [])
                self.assertEqual(self.store.ai_paused_until(), self.now + BILLING_PAUSE_SECONDS)
        self.assertEqual(self.store.ai_month_usage(), {"report_commentary": 0})

    def test_pause_expires(self):
        self.store.ai_pause(self.now + 10, "billing")
        client = FakeClient(response=reply())
        with mock.patch.dict(os.environ, ON):
            self.assertIsNone(self.call(client))
            self.now += 11
            self.assertIsNotNone(self.call(client))

    def test_timeout_keeps_worst_case_charge(self):
        with mock.patch.dict(os.environ, ON):
            self.assertIsNone(self.call(FakeClient(error=TimeoutError("read timeout"))))
        self.assertEqual(self.store.ai_month_usage(), {"report_commentary": to_micros(0.08)})
        self.assertEqual(self.store.ai_paused_until(), 0.0)

    def test_server_error_is_not_charged_or_paused(self):
        with mock.patch.dict(os.environ, ON):
            self.assertIsNone(self.call(FakeClient(error=FakeStatusError(529, "overloaded", "overloaded_error"))))
        self.assertEqual(self.store.ai_month_usage(), {"report_commentary": 0})
        self.assertEqual(self.store.ai_paused_until(), 0.0)

    def test_truncated_or_refused_answer_falls_back_but_is_charged(self):
        for stop in ("max_tokens", "refusal"):
            with self.subTest(stop=stop), mock.patch.dict(os.environ, ON):
                self.assertIsNone(self.call(FakeClient(response=reply(stop=stop)), cache_key=stop))
                self.assertIsNone(self.store.ai_cached("report_commentary", stop))
        self.assertGreater(self.store.ai_month_usage()["report_commentary"], 0)

    def test_monthly_allocation_is_never_passed(self):
        feature = FEATURES["report_commentary"]
        worst = max_call_micros(feature)
        limit = to_micros(feature.monthly_usd)
        # Fill the month with reservations up to one call short of the limit.
        while self.store.ai_reserve(feature.key, worst, limit, to_micros(MONTHLY_APP_LIMIT_USD)):
            pass
        self.assertEqual(self.store.ai_month_usage()[feature.key], limit)
        client = FakeClient(response=reply())
        with mock.patch.dict(os.environ, ON):
            self.assertIsNone(self.call(client))
        self.assertEqual(client.calls, [])
        # Next month starts fresh.
        self.now = datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc).timestamp()
        with mock.patch.dict(os.environ, ON):
            self.assertIsNotNone(self.call(client))

    def test_app_wide_limit_applies_across_features(self):
        self.assertIsNotNone(self.store.ai_reserve("question_review", 30, 100, 50))
        self.assertIsNone(self.store.ai_reserve("report_commentary", 30, 100, 50))

    def test_over_ceiling_input_batch_and_unfunded_features_never_call(self):
        client = FakeClient(response=reply())
        with mock.patch.dict(os.environ, ON):
            self.assertIsNone(self.call(client, prompt="가" * 25_000))
            self.assertIsNone(self.call(client, feature="course_tagging"))
            self.assertIsNone(self.call(client, feature="open_answer_summary"))
            self.assertIsNone(self.call(client, feature="unknown"))
        self.assertEqual(client.calls, [])

    def test_database_failure_falls_back(self):
        broken = mock.Mock()
        broken.ai_cached.side_effect = RuntimeError("db down")
        with mock.patch.dict(os.environ, ON):
            self.assertIsNone(generate(broken, "report_commentary", system="s", prompt="p", cache_key="k",
                                       client_factory=lambda: FakeClient(response=reply())))

    def test_kma_only_usage_summary(self):
        from tap.account_store import AuthenticationError

        with self.assertRaises(AuthenticationError):
            self.store.ai_usage_summary("x" * 40)


if __name__ == "__main__":
    unittest.main()
