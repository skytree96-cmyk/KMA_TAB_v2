from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tap.account_store import AccountStore
from tap.report_commentary import (FEATURE, PROJECT_MONTHLY_LIMIT, build_payload, cache_key, commentary_state,
                                   make_commentary, valid_commentary)
from tap.report_commentary_ui import commentary_html

ON = {"TAP_AI_ENABLED": "1", "ANTHROPIC_API_KEY": "test-key"}
PROJECT = {"id": "proj-1", "name": "리더십 과정", "config": {"target_means": {"LEAD-PD": 3.8, "JOB-ST": 3.8}}}
SUMMARIES = [
    {"factor_code": "LEAD-PD", "factor_name_ko": "성과 관리", "paired_n": 42, "pre_mean": 3.12, "post_mean": 3.58},
    {"factor_code": "JOB-ST", "factor_name_ko": "전략적 사고", "paired_n": 41, "pre_mean": 2.98, "post_mean": 3.21},
    {"factor_code": "CORE-CO", "factor_name_ko": "고객 지향", "paired_n": 4, "pre_mean": 3.9, "post_mean": 3.95},
]
GRID = {"factors": [{"factor_code": "LEAD-PD", "factor_name_ko": "성과 관리"}, {"factor_code": "JOB-ST", "factor_name_ko": "전략적 사고"}],
        "rows": [
            {"team": "생산본부", "paired_n": 15, "cells": [{"factor_code": "LEAD-PD", "shown": True, "change": 0.58},
                                                         {"factor_code": "JOB-ST", "shown": True, "change": 0.12}]},
            {"team": "영업본부", "paired_n": 12, "cells": [{"factor_code": "LEAD-PD", "shown": True, "change": 0.41},
                                                         {"factor_code": "JOB-ST", "shown": False, "change": None}]},
            {"team": "연구소", "paired_n": 3, "cells": [{"factor_code": "LEAD-PD", "shown": False, "change": None},
                                                      {"factor_code": "JOB-ST", "shown": False, "change": None}]},
        ]}
TRANSFER = {"n": 40, "disclosed": True,
            "factors": [{"label": "상사·리더 지원", "mean": 2.7}, {"label": "시간·프로세스", "mean": 2.6}],
            "barriers": [{"label": "시간·프로세스 제약", "count": 18, "rate": 45}]}
COURSES = [{"factor_name_ko": "전략적 사고", "source": "public_edu_center", "title": "전략적 사고와 기획력", "next_start": "20261215"},
           {"factor_name_ko": "전략적 사고", "source": "studio_elearning", "title": "전략적 사고 기초"}]
GOOD = {"headline": "전략적 사고 보완과 현업 여건을 함께 챙길 때입니다",
        "findings": [{"title": "남은 격차", "body": "성과 관리는 +0.46점 올랐습니다. 목표 3.80점에는 못 미칩니다."},
                     {"title": "부서 차이", "body": "성과 관리 변화는 생산본부가 0.58점입니다."},
                     {"title": "적용 여건", "body": "시간·프로세스는 2.60점입니다. 장애요인으로 45%가 골랐습니다."}],
        "actions": ["[공개교육] 전략적 사고와 기획력 (12월 15일 개강) 대상자를 정하세요.", "상사와 적용 방안을 정하세요."]}


def payload():
    return build_payload(PROJECT, SUMMARIES, 42, GRID, TRANSFER, COURSES)


class PayloadTests(unittest.TestCase):
    def test_only_disclosed_numbers_go_out(self):
        data = payload()
        self.assertEqual([row["역량"] for row in data["역량별 결과"]], ["성과 관리", "전략적 사고"])
        first = data["역량별 결과"][0]
        self.assertEqual((first["교육 전"], first["교육 후"], first["변화"], first["목표 대비"]), ("3.12", "3.58", "+0.46", "-0.22"))
        teams = data["부서별 교육 전후 변화(5명 이상만)"]
        self.assertEqual([team["부서"] for team in teams], ["생산본부", "영업본부"])
        self.assertEqual(teams[1]["변화"], {"성과 관리": "+0.41"})
        self.assertEqual(data["현업전이 환경(1~5)"]["평균"]["시간·프로세스"], "2.60")
        self.assertEqual(data["검토 과정(목표보다 0.2점 이상 낮은 역량)"][0]["과정"],
                         ["[공개교육] 전략적 사고와 기획력 (12월 15일 개강)", "[이러닝] 전략적 사고 기초"])
        self.assertNotIn("고객 지향", json.dumps(data, ensure_ascii=False))

    def test_hidden_parts_are_left_out(self):
        data = build_payload(PROJECT, SUMMARIES, 42, {"factors": GRID["factors"], "rows": GRID["rows"][:1]},
                             {"n": 3, "disclosed": False}, [])
        self.assertNotIn("부서별 교육 전후 변화(5명 이상만)", data)
        self.assertNotIn("현업전이 환경(1~5)", data)
        self.assertNotIn("검토 과정(목표보다 0.2점 이상 낮은 역량)", data)
        self.assertIsNone(build_payload(PROJECT, SUMMARIES[2:], 4, None, None, []))

    def test_cache_key_follows_the_numbers(self):
        changed = build_payload(PROJECT, [{**SUMMARIES[0], "post_mean": 3.6}, SUMMARIES[1]], 42, GRID, TRANSFER, COURSES)
        self.assertEqual(cache_key("proj-1", payload()), cache_key("proj-1", payload()))
        self.assertNotEqual(cache_key("proj-1", payload()), cache_key("proj-1", changed))
        self.assertTrue(cache_key("proj-1", payload()).startswith("proj-1:"))

    def test_validation_rejects_invented_numbers_and_bad_shapes(self):
        self.assertTrue(valid_commentary(GOOD, payload()))
        invented = {**GOOD, "headline": "성과 관리가 0.51점 올랐습니다"}
        self.assertFalse(valid_commentary(invented, payload()))
        rounded = {**GOOD, "headline": "목표 3.8점과 차이가 있습니다"}
        self.assertFalse(valid_commentary(rounded, payload()))
        self.assertFalse(valid_commentary({**GOOD, "findings": GOOD["findings"][:1]}, payload()))
        self.assertFalse(valid_commentary({**GOOD, "actions": []}, payload()))
        self.assertFalse(valid_commentary("text", payload()))

    def test_html_escapes_model_text(self):
        stored = {"result": {**GOOD, "headline": "<script>alert(1)</script>"}, "created_at": "2026-11-23 14:20"}
        html = commentary_html(stored)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("자동 작성한 해설", html)
        self.assertEqual(html.count('class="tap-cm__find"'), 3)


def reply(result):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(result, ensure_ascii=False))], stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=13_000, output_tokens=1_800, cache_creation_input_tokens=0, cache_read_input_tokens=0))


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = datetime(2026, 11, 23, 5, 20, tzinfo=timezone.utc).timestamp()
        self.store = AccountStore("sqlite:///" + str(Path(self.tmp.name) / "c.sqlite"),
                                  allow_sqlite_for_tests=True, clock=lambda: self.now)
        self.store.initialize()
        self.calls = []

    def client(self, result):
        def create(**kwargs):
            self.calls.append(kwargs)
            return reply(result)
        return SimpleNamespace(messages=SimpleNamespace(create=create))

    def make(self, result=GOOD, data=None):
        with mock.patch("tap.ai_client._default_client", lambda: self.client(result)):
            return make_commentary(self.store, "proj-1", data or payload())

    def test_off_means_no_block_and_no_call(self):
        with mock.patch.dict(os.environ, {"TAP_AI_ENABLED": "", "ANTHROPIC_API_KEY": ""}):
            state = commentary_state(self.store, "proj-1", payload())
            self.assertFalse(state["can_make"])
            self.assertIsNone(self.make())
        self.assertIsNone(state["current"])
        self.assertEqual(self.calls, [])

    def test_made_once_then_served_from_storage(self):
        with mock.patch.dict(os.environ, ON):
            self.assertTrue(commentary_state(self.store, "proj-1", payload())["can_make"])
            made = self.make()
            state = commentary_state(self.store, "proj-1", payload())
        self.assertEqual(made["result"]["headline"], GOOD["headline"])
        self.assertEqual(made["created_at"], "2026-11-23 14:20")
        self.assertEqual(state["current"]["result"], GOOD)
        self.assertEqual(state["remaining"], PROJECT_MONTHLY_LIMIT - 1)
        call = self.calls[0]
        self.assertEqual(call["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("user_id", call["messages"][0]["content"])
        # Credit gone: the stored commentary still shows.
        with mock.patch.dict(os.environ, {"TAP_AI_ENABLED": "", "ANTHROPIC_API_KEY": ""}):
            self.assertEqual(commentary_state(self.store, "proj-1", payload())["current"]["result"], GOOD)

    def test_invented_numbers_are_not_stored(self):
        with mock.patch.dict(os.environ, ON):
            self.assertIsNone(self.make({**GOOD, "headline": "0.99점 올랐습니다"}))
            state = commentary_state(self.store, "proj-1", payload())
        self.assertIsNone(state["current"])
        self.assertEqual(state["remaining"], PROJECT_MONTHLY_LIMIT - 1)  # the call still counts

    def test_new_numbers_show_the_older_commentary(self):
        with mock.patch.dict(os.environ, ON):
            self.make()
            changed = build_payload(PROJECT, [{**SUMMARIES[0], "post_mean": 3.6}, SUMMARIES[1]], 43, GRID, TRANSFER, COURSES)
            state = commentary_state(self.store, "proj-1", changed)
        self.assertIsNone(state["current"])
        self.assertEqual(state["older"]["result"], GOOD)
        self.assertIsNone(commentary_state(self.store, "proj-2", changed)["older"])

    def test_project_limit(self):
        for _ in range(PROJECT_MONTHLY_LIMIT):
            self.store.ai_reserve(FEATURE, 1, 10**9, 10**9, "proj-1")
        with mock.patch.dict(os.environ, ON):
            self.assertFalse(commentary_state(self.store, "proj-1", payload())["can_make"])
            self.assertIsNone(self.make())
            self.assertTrue(commentary_state(self.store, "proj-2", payload())["can_make"])
        self.assertEqual(self.calls, [])

    def test_like_prefix_is_escaped(self):
        self.store.ai_store_result(FEATURE, "p_1:abc", json.dumps({"result": GOOD, "created_at": "x"}))
        self.assertIsNone(self.store.ai_latest_result(FEATURE, "pX1:"))
        self.assertIsNotNone(self.store.ai_latest_result(FEATURE, "p_1:"))


if __name__ == "__main__":
    unittest.main()
