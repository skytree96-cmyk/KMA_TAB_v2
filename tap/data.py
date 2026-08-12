from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from tap.config import DATA_DIR


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


@lru_cache(maxsize=1)
def load_questions() -> list[dict[str, Any]]:
    rows = _read_csv(DATA_DIR / "question_bank.csv")
    for row in rows:
        row["difficulty"] = int(row["difficulty"])
        row["original_reverse"] = row["original_reverse"].lower() == "true"
        row["active"] = row["active"].lower() == "true"
        row["validity_score"] = int(row["validity_score"])
    return rows


@lru_cache(maxsize=1)
def load_competencies() -> list[dict[str, Any]]:
    rows = _read_csv(DATA_DIR / "competencies.csv")
    for row in rows:
        row["default_selected"] = row["default_selected"].lower() == "true"
        row["active_for_scoring"] = row["active_for_scoring"].lower() == "true"
        row["display_order"] = int(row["display_order"])
    return rows


@lru_cache(maxsize=1)
def load_pilot_item_candidates() -> list[dict[str, Any]]:
    """Return non-scoring competency/item candidates awaiting expert validation."""
    rows = _read_csv(DATA_DIR / "pilot_item_candidates.csv")
    for row in rows:
        row["active_for_scoring"] = row["active_for_scoring"].lower() == "true"
    return rows


@lru_cache(maxsize=1)
def load_courses() -> list[dict[str, Any]]:
    rows = _read_csv(DATA_DIR / "courses.csv")
    for row in rows:
        row["active"] = row["active"].lower() == "true"
    return rows


@lru_cache(maxsize=1)
def load_course_map() -> list[dict[str, Any]]:
    rows = _read_csv(DATA_DIR / "competency_course_map.csv")
    for row in rows:
        row["content_fit"] = float(row["content_fit"])
    return rows


@lru_cache(maxsize=1)
def load_scoring_rules() -> dict[str, Any]:
    with (DATA_DIR / "scoring_rules.json").open("r", encoding="utf-8") as fh:
        return json.load(fh)


def questions_for_factors(factor_codes: list[str]) -> list[dict[str, Any]]:
    selected = set(factor_codes)
    rows = [q for q in load_questions() if q["active"] and q["factor_code"] in selected]
    return sorted(rows, key=lambda q: (int(q["factor_order"]), int(q["item_order"])))


def integrity_report() -> dict[str, Any]:
    questions = load_questions()
    competencies = load_competencies()
    q_codes = [q["question_code"] for q in questions]
    factor_codes = {c["factor_code"] for c in competencies}
    active_factor_codes = {c["factor_code"] for c in competencies if c["active_for_scoring"]}
    q_factor_codes = {q["factor_code"] for q in questions}
    per_factor: dict[str, int] = {}
    for q in questions:
        per_factor[q["factor_code"]] = per_factor.get(q["factor_code"], 0) + 1
    return {
        "question_count": len(questions),
        "competency_count": len(competencies),
        "unique_question_codes": len(q_codes) == len(set(q_codes)),
        "unmapped_question_factors": sorted(q_factor_codes - factor_codes),
        "retired_competencies": sorted(factor_codes - active_factor_codes),
        "unexpected_empty_competencies": sorted(active_factor_codes - q_factor_codes),
        "factors_not_four_items": {k: v for k, v in per_factor.items() if v != 4},
    }
