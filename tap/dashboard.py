from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Iterable, Mapping

from tap.config import DATA_DIR


@lru_cache(maxsize=1)
def load_dashboard_demo() -> dict[str, Any]:
    with (DATA_DIR / "dashboard_demo.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)


def completion_rate(projects: Iterable[Mapping[str, Any]]) -> float:
    invited = sum(int(row["invited"]) for row in projects)
    completed = sum(int(row["completed"]) for row in projects)
    return round(completed / invited * 100, 1) if invited else 0.0


def validate_dashboard_demo(data: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(data) != {"company", "kma"}:
        errors.append("dashboard roles must be company and kma")

    company = data.get("company", {})
    projects = company.get("projects", [])
    if len(company.get("metrics", [])) != 4:
        errors.append("company dashboard must have four metrics")
    for project in projects:
        invited = int(project.get("invited", 0))
        completed = int(project.get("completed", 0))
        pct = int(project.get("completion_pct", -1))
        if invited < completed:
            errors.append(f"completed exceeds invited: {project.get('name')}")
        expected = round(completed / invited * 100) if invited else 0
        if pct != expected:
            errors.append(f"completion rate mismatch: {project.get('name')}")

    kma = data.get("kma", {})
    if len(kma.get("metrics", [])) != 4:
        errors.append("KMA dashboard must have four metrics")
    forbidden_fragments = ("score", "점수", "gap", "격차", "individual", "개인결과")
    for row in kma.get("organizations", []):
        for key in row:
            if any(fragment in str(key).lower() for fragment in forbidden_fragments):
                errors.append(f"KMA organization row exposes forbidden field: {key}")
    return errors
