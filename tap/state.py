from __future__ import annotations

from time import time
from typing import Any, MutableMapping


DEFAULTS: dict[str, Any] = {
    "active_role": "company",
    "project_name": "2026 하반기 공통역량 진단",
    "project_start_date": "2026-08-17",
    "project_end_date": "2026-08-28",
    "target_level": "manager",
    "selected_factors": [],
    "responses": {},
    "current_question": 0,
    "assessment_started_at": None,
    "assessment_completed": False,
    "target_means": {},
    "organization_priorities": [],
    "learner_interests": [],
    "training_cause": "mixed_or_unknown",
    "delivery_preference": "all",
}


def ensure_state(state: MutableMapping[str, Any]) -> None:
    for key, value in DEFAULTS.items():
        if key not in state:
            state[key] = value.copy() if isinstance(value, (dict, list)) else value


def reset_assessment(state: MutableMapping[str, Any]) -> None:
    state["responses"] = {}
    state["current_question"] = 0
    state["assessment_started_at"] = time()
    state["assessment_completed"] = False
