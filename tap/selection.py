from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


MAX_SPECIALTY = 3
MAX_JOB_FUNCTION = 1
MAX_OPTIONAL = 4


def applicable_to_level(row: Mapping[str, Any], target_level: str) -> bool:
    levels = {part for part in str(row.get("target_levels", "")).split("|") if part}
    return "all" in levels or target_level in levels


def selection_errors(
    selected_codes: Iterable[str], competency_rows: Iterable[Mapping[str, Any]]
) -> list[str]:
    rows = {str(row["factor_code"]): row for row in competency_rows}
    codes = list(dict.fromkeys(str(code) for code in selected_codes))
    errors: list[str] = []
    missing = [code for code in codes if code not in rows]
    if missing:
        errors.append(f"unknown competency codes: {missing}")
    counts = Counter(
        str(rows[code].get("library_type")) for code in codes if code in rows
    )
    if counts["specialty"] > MAX_SPECIALTY:
        errors.append(f"전문·미래역량은 최대 {MAX_SPECIALTY}개입니다.")
    if counts["job_function"] > MAX_JOB_FUNCTION:
        errors.append(f"직무역량은 최대 {MAX_JOB_FUNCTION}개입니다.")
    optional_count = counts["specialty"] + counts["job_function"]
    if optional_count > MAX_OPTIONAL:
        errors.append(f"선택역량은 총 {MAX_OPTIONAL}개를 넘을 수 없습니다.")
    return errors


def sanitize_selection(
    selected_codes: Iterable[str],
    competency_rows: Iterable[Mapping[str, Any]],
    target_level: str,
) -> list[str]:
    rows = {str(row["factor_code"]): row for row in competency_rows}
    kept: list[str] = []
    counts = Counter()
    for code in dict.fromkeys(str(code) for code in selected_codes):
        row = rows.get(code)
        if not row or not row.get("active_for_scoring") or not applicable_to_level(row, target_level):
            continue
        library_type = str(row.get("library_type"))
        if library_type == "specialty" and counts[library_type] >= MAX_SPECIALTY:
            continue
        if library_type == "job_function" and counts[library_type] >= MAX_JOB_FUNCTION:
            continue
        if library_type in {"specialty", "job_function"} and (
            counts["specialty"] + counts["job_function"] >= MAX_OPTIONAL
        ):
            continue
        kept.append(code)
        counts[library_type] += 1
    return kept
