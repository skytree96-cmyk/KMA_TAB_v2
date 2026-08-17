from __future__ import annotations

import csv
import io
import math
from datetime import date
from html import escape
from statistics import mean
from textwrap import dedent
from typing import Any, Iterable, Mapping

import pandas as pd

from tap.scoring import score_pre_post_responses, score_responses


GROUP_REQUIRED_COLUMNS = ("participant_id", "factor_code", "score_1_to_5")
GROUP_METADATA_COLUMNS = ("project_id", "assessment_version", "target_level", "assessment_date")
GROUP_SESSION_COLUMN = "session_type"
GROUP_QUALITY_COLUMNS = ("valid_items", "na_items", "missing_items")
GROUP_TRANSFER_COLUMNS = (
    "opportunity_1_to_5",
    "manager_support_1_to_5",
    "resource_support_1_to_5",
    "time_process_support_1_to_5",
)
SESSION_TYPES = {"pre", "post"}


def read_group_results_csv(raw: bytes) -> pd.DataFrame:
    """Decode an uploaded group CSV without silently mangling duplicate headers."""

    if not raw:
        raise ValueError("CSV 파일이 비어 있습니다.")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        try:
            header = next(csv.reader(io.StringIO(text)))
        except (csv.Error, StopIteration) as exc:
            raise ValueError(f"CSV 헤더를 읽을 수 없습니다: {exc}") from exc
        normalized = [str(name).strip() for name in header]
        duplicates = sorted(
            {name for name in normalized if normalized.count(name) > 1}
        )
        if duplicates:
            raise ValueError(
                "CSV 열 이름이 중복되었습니다: " + ", ".join(duplicates)
            )
        try:
            # 모든 열을 문자열로 먼저 보존한다. 특히 참여자 ID의 선행 0을
            # pandas 숫자 추론으로 잃으면 서로 다른 참여자가 잘못 짝지어진다.
            # 점수·품질·전이 열은 아래 canonical validator가 명시적으로 숫자화한다.
            return pd.read_csv(io.StringIO(text), dtype="string")
        except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise ValueError(f"CSV 구조를 읽을 수 없습니다: {exc}") from exc
    raise ValueError("CSV는 UTF-8 또는 CP949 인코딩으로 저장해 주세요.")


def completed_session_factor_rows(
    question_rows: Iterable[Mapping[str, Any]],
    responses_by_phase: Mapping[str, Mapping[str, int]],
    completed_by_phase: Mapping[str, Any],
    *,
    participant_id: str,
    project_id: str,
    assessment_version: str,
    target_level: str,
    assessment_dates: Mapping[str, Any],
    target_means: Mapping[str, float] | None = None,
    post_transfer_responses: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Convert completed in-browser assessments to the canonical group CSV rows.

    Incomplete waves are deliberately omitted. This prevents a partially answered
    post-test from being presented as a real pre/post comparison and gives the
    organization report the exact same factor scores as the individual report.
    """
    clean_participant_id = str(participant_id or "").strip()
    if not clean_participant_id:
        return []

    questions = list(question_rows)
    transfer = dict(post_transfer_responses or {})
    transfer_columns = {
        "opportunity_1_to_5": transfer.get("application_opportunity"),
        "manager_support_1_to_5": transfer.get("supervisor_support"),
        "resource_support_1_to_5": transfer.get("resources_authority"),
        "time_process_support_1_to_5": transfer.get("time_process_support"),
    }
    paired_scores: dict[str, dict[str, Any]] = {}
    if bool(completed_by_phase.get("pre")) and bool(completed_by_phase.get("post")):
        paired_scores = {
            str(row["factor_code"]): row
            for row in score_pre_post_responses(
                questions,
                dict(responses_by_phase.get("pre") or {}),
                dict(responses_by_phase.get("post") or {}),
                target_means,
            )
        }
    output: list[dict[str, Any]] = []
    for phase in ("pre", "post"):
        if not bool(completed_by_phase.get(phase, False)):
            continue
        responses = dict(responses_by_phase.get(phase) or {})
        if not responses:
            continue
        for score in score_responses(
            questions,
            responses,
            target_means,
            assessment_phase=phase,
        ):
            paired = paired_scores.get(str(score["factor_code"]))
            if paired:
                paired_score = paired.get("pre_score" if phase == "pre" else "post_score")
                if paired_score is None:
                    continue
                score = dict(score)
                score["score_1_to_5"] = paired_score
            if score.get("score_1_to_5") is None:
                continue
            row = {
                "participant_id": clean_participant_id,
                "factor_code": score["factor_code"],
                "factor_name_ko": score["factor_name_ko"],
                "score_1_to_5": score["score_1_to_5"],
                "project_id": str(project_id or "TAP-PROJECT").strip() or "TAP-PROJECT",
                "assessment_version": str(assessment_version or "TAP-1.0").strip() or "TAP-1.0",
                "target_level": str(target_level or "staff").strip() or "staff",
                "assessment_date": str(assessment_dates.get(phase, "") or ""),
                "session_type": phase,
                "valid_items": score["valid_items"],
                "na_items": score["na_items"],
                "missing_items": score["missing_items"],
                "opportunity_1_to_5": None,
                "manager_support_1_to_5": None,
                "resource_support_1_to_5": None,
                "time_process_support_1_to_5": None,
            }
            if phase == "post":
                row.update(transfer_columns)
            output.append(row)
    return output


def prepare_group_results(
    frame: pd.DataFrame,
    competency_rows: Iterable[Mapping[str, Any]],
    *,
    require_metadata: bool = False,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Validate uploaded factor-level results and apply canonical Korean names."""
    errors: list[str] = []
    warnings: list[str] = []
    missing = [column for column in GROUP_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        return frame.copy(), ["필수 열이 없습니다: " + ", ".join(missing)], warnings
    if frame.empty:
        return frame.copy(), ["업로드 파일에 결과 행이 없습니다."], warnings

    work = frame.copy()
    work["participant_id"] = work["participant_id"].astype("string").fillna("").str.strip()
    work["factor_code"] = work["factor_code"].astype("string").fillna("").str.strip()
    blank_ids = work.index[work["participant_id"].eq("")].tolist()
    blank_codes = work.index[work["factor_code"].eq("")].tolist()
    if blank_ids:
        errors.append(f"참여자 식별자가 빈 행이 {len(blank_ids)}개 있습니다.")
    if blank_codes:
        errors.append(f"역량코드가 빈 행이 {len(blank_codes)}개 있습니다.")

    scores = pd.to_numeric(work["score_1_to_5"], errors="coerce")
    invalid_number = scores.isna() | ~scores.map(lambda value: math.isfinite(float(value)) if pd.notna(value) else False)
    if invalid_number.any():
        errors.append(f"점수가 숫자가 아니거나 유한하지 않은 행이 {int(invalid_number.sum())}개 있습니다.")
    outside = scores.notna() & ((scores < 1) | (scores > 5))
    if outside.any():
        errors.append(f"점수가 1~5 범위를 벗어난 행이 {int(outside.sum())}개 있습니다.")
    work["score_1_to_5"] = scores

    canonical = {
        str(row["factor_code"]): str(row["factor_name_ko"])
        for row in competency_rows
        if bool(row.get("active_for_scoring", True))
    }
    unknown = sorted(set(work["factor_code"].dropna()) - set(canonical))
    if unknown:
        errors.append("등록되지 않은 역량코드가 있습니다: " + ", ".join(unknown))

    if "factor_name_ko" in work.columns:
        supplied = work["factor_name_ko"].astype("string").fillna("").str.strip()
        mismatch_count = sum(
            bool(code in canonical and supplied_name and supplied_name != canonical[code])
            for code, supplied_name in zip(work["factor_code"], supplied, strict=False)
        )
        if mismatch_count:
            warnings.append(
                f"역량코드와 한글명이 다른 행 {mismatch_count}개는 공식 한글명으로 교체했습니다."
            )
    work["factor_name_ko"] = work["factor_code"].map(canonical).fillna("")

    duplicate_key = ["participant_id", "factor_code"]
    if GROUP_SESSION_COLUMN in work.columns:
        sessions = work[GROUP_SESSION_COLUMN].astype("string").fillna("").str.strip().str.lower()
        work[GROUP_SESSION_COLUMN] = sessions
        blank_sessions = int(sessions.eq("").sum())
        if blank_sessions:
            errors.append(f"session_type 값이 빈 행이 {blank_sessions}개 있습니다.")
        invalid_sessions = sorted(set(sessions) - SESSION_TYPES - {""})
        if invalid_sessions:
            errors.append("session_type 값은 pre 또는 post여야 합니다. 추적검사는 현재 버전에서 지원하지 않습니다.")
        duplicate_key.append(GROUP_SESSION_COLUMN)

    duplicate_count = int(work.duplicated(duplicate_key, keep=False).sum())
    if duplicate_count:
        message = f"같은 참여자·역량·검사시점의 중복 행이 {duplicate_count}개 있습니다."
        if require_metadata:
            errors.append(message + " 운영 업로드에서는 중복 행을 제거해 주세요.")
        else:
            warnings.append(message + " 참여자별 평균으로 먼저 축약합니다.")

    for column in GROUP_QUALITY_COLUMNS:
        if column not in work.columns:
            continue
        values = pd.to_numeric(work[column], errors="coerce")
        invalid = values.isna() | (values < 0) | ~values.map(
            lambda value: math.isfinite(float(value)) if pd.notna(value) else False
        )
        invalid |= values.notna() & (values % 1 != 0)
        if invalid.any():
            errors.append(f"{column} 값은 0 이상의 정수여야 합니다.")
        work[column] = values

    for column in GROUP_TRANSFER_COLUMNS:
        if column not in work.columns:
            continue
        values = pd.to_numeric(work[column], errors="coerce")
        raw_values = work[column].astype("string").fillna("").str.strip()
        nonnumeric = raw_values.ne("") & values.isna()
        if nonnumeric.any():
            errors.append(f"{column} 값이 숫자가 아닌 행이 {int(nonnumeric.sum())}개 있습니다.")
        invalid = values.notna() & ((values < 1) | (values > 5))
        if invalid.any():
            errors.append(f"{column} 값은 1~5 범위여야 합니다.")
        work[column] = values

    if require_metadata:
        missing_metadata = [column for column in GROUP_METADATA_COLUMNS if column not in work.columns]
        if missing_metadata:
            errors.append(
                "프로젝트·버전 혼합 방지를 위해 다음 메타데이터 열이 필요합니다: "
                + ", ".join(missing_metadata)
            )
        for column in GROUP_METADATA_COLUMNS:
            if column not in work.columns:
                continue
            values = work[column].astype("string").fillna("").str.strip()
            blank_count = int(values.eq("").sum())
            if blank_count:
                errors.append(f"{column} 값이 빈 행이 {blank_count}개 있습니다.")
            unique = sorted(value for value in values.unique().tolist() if value)
            if column != "assessment_date" and len(unique) > 1:
                errors.append(f"{column} 값이 둘 이상 섞여 있습니다: {', '.join(unique[:5])}")
            if column == "assessment_date":
                parsed_dates = pd.to_datetime(values.where(values.ne("")), errors="coerce")
                invalid_dates = int((values.ne("") & parsed_dates.isna()).sum())
                if invalid_dates:
                    errors.append(f"assessment_date 형식이 올바르지 않은 행이 {invalid_dates}개 있습니다.")
            if column == "target_level":
                invalid_levels = sorted(set(unique) - {"staff", "manager", "executive"})
                if invalid_levels:
                    errors.append("target_level 값은 staff, manager, executive 중 하나여야 합니다.")

        if GROUP_SESSION_COLUMN in work.columns:
            missing_quality = [column for column in GROUP_QUALITY_COLUMNS if column not in work.columns]
            if missing_quality:
                errors.append("사전·사후 품질 확인을 위해 다음 열이 필요합니다: " + ", ".join(missing_quality))
            elif not work.empty:
                quality_total = work[list(GROUP_QUALITY_COLUMNS)].sum(axis=1)
                inconsistent_total = quality_total.ne(4)
                if inconsistent_total.any():
                    errors.append(
                        "valid_items + na_items + missing_items 합계가 4가 아닌 행이 "
                        f"{int(inconsistent_total.sum())}개 있습니다."
                    )
                invalid_scored = work["score_1_to_5"].notna() & work["valid_items"].lt(3)
                if invalid_scored.any():
                    errors.append(
                        "점수가 있으나 유효문항이 3개 미만인 행이 "
                        f"{int(invalid_scored.sum())}개 있습니다."
                    )

            if "assessment_date" in work.columns and {"pre", "post"}.issubset(set(work[GROUP_SESSION_COLUMN])):
                dated = work.assign(
                    _assessment_date=pd.to_datetime(work["assessment_date"], errors="coerce")
                )
                for (_, _), group in dated.groupby(["participant_id", "factor_code"]):
                    pre_dates = group.loc[group[GROUP_SESSION_COLUMN].eq("pre"), "_assessment_date"].dropna()
                    post_dates = group.loc[group[GROUP_SESSION_COLUMN].eq("post"), "_assessment_date"].dropna()
                    if not pre_dates.empty and not post_dates.empty and pre_dates.max() >= post_dates.min():
                        errors.append("동일 참여자·역량의 사전검사일은 사후검사일보다 빨라야 합니다.")
                        break

    ordered = list(GROUP_REQUIRED_COLUMNS) + ["factor_name_ko"]
    ordered += [column for column in GROUP_METADATA_COLUMNS if column in work.columns]
    ordered += [column for column in (GROUP_SESSION_COLUMN, *GROUP_QUALITY_COLUMNS, *GROUP_TRANSFER_COLUMNS) if column in work.columns]
    return work[ordered], errors, warnings


def build_pre_post_group_summary(
    frame: pd.DataFrame,
    *,
    min_group_n: int = 5,
) -> dict[str, Any]:
    """Build paired organization changes without subtracting unmatched wave means."""
    empty = {
        "comparison_rows": [],
        "pre_participant_count": 0,
        "post_participant_count": 0,
        "paired_participant_count": 0,
        "attrition_count": 0,
        "attrition_rate": None,
        "pre_na_items": None,
        "post_na_items": None,
        "transfer_factors": {},
        "min_group_n": min_group_n,
    }
    if frame.empty or GROUP_SESSION_COLUMN not in frame.columns:
        return empty

    work = frame[frame[GROUP_SESSION_COLUMN].isin({"pre", "post"})].copy()
    if work.empty:
        return empty
    pre_people = set(work.loc[work[GROUP_SESSION_COLUMN].eq("pre"), "participant_id"].astype(str))
    post_people = set(work.loc[work[GROUP_SESSION_COLUMN].eq("post"), "participant_id"].astype(str))
    common_pairs = (
        work.groupby(["participant_id", "factor_code"])[GROUP_SESSION_COLUMN]
        .agg(lambda values: set(values))
    )
    paired_people = {
        str(participant_id)
        for (participant_id, _), phases in common_pairs.items()
        if {"pre", "post"}.issubset(phases)
    }

    collapsed = (
        work.groupby(["participant_id", "factor_code", GROUP_SESSION_COLUMN], as_index=False)
        .agg(score_1_to_5=("score_1_to_5", "mean"), factor_name_ko=("factor_name_ko", "first"))
    )
    names = dict(zip(collapsed["factor_code"].astype(str), collapsed["factor_name_ko"].astype(str), strict=False))
    comparison_rows: list[dict[str, Any]] = []
    for factor_code, factor_frame in collapsed.groupby("factor_code"):
        pivot = factor_frame.pivot(index="participant_id", columns=GROUP_SESSION_COLUMN, values="score_1_to_5")
        pre_n = int(pivot["pre"].notna().sum()) if "pre" in pivot else 0
        post_n = int(pivot["post"].notna().sum()) if "post" in pivot else 0
        if not {"pre", "post"}.issubset(pivot.columns):
            paired = pivot.iloc[0:0]
        else:
            paired = pivot.dropna(subset=["pre", "post"])
        paired_n = int(len(paired))
        is_public = paired_n >= min_group_n
        pre_mean = round(float(paired["pre"].mean()), 2) if is_public else None
        post_mean = round(float(paired["post"].mean()), 2) if is_public else None
        change = round(float((paired["post"] - paired["pre"]).mean()), 2) if is_public else None
        comparison_rows.append(
            {
                "factor_code": str(factor_code),
                "factor_name_ko": names.get(str(factor_code), str(factor_code)),
                "pre_n": pre_n,
                "post_n": post_n,
                "paired_n": paired_n,
                "pre_mean": pre_mean,
                "post_mean": post_mean,
                "change": change,
                "status": "공개" if is_public else f"비공개(N<{min_group_n})",
            }
        )

    def _quality_total(column: str, session: str) -> int | None:
        if column not in work.columns:
            return None
        values = pd.to_numeric(work.loc[work[GROUP_SESSION_COLUMN].eq(session), column], errors="coerce")
        return int(values.sum()) if values.notna().any() else None

    transfer_labels = {
        "opportunity_1_to_5": "업무 적용기회",
        "manager_support_1_to_5": "상사·동료 지원",
        "resource_support_1_to_5": "도구·권한 지원",
        "time_process_support_1_to_5": "시간·프로세스 지원",
    }
    transfer_factors: dict[str, dict[str, Any]] = {}
    post = work[work[GROUP_SESSION_COLUMN].eq("post")]
    for column, label in transfer_labels.items():
        if column not in post.columns:
            continue
        by_person = post[post["participant_id"].astype(str).isin(paired_people)].groupby("participant_id")[column].mean().dropna()
        n = int(by_person.shape[0])
        transfer_factors[label] = {
            "mean": round(float(by_person.mean()), 2) if n >= min_group_n else None,
            "n": n,
            "status": "공개" if n >= min_group_n else f"비공개(N<{min_group_n})",
        }

    attrition_count = max(0, len(pre_people) - len(paired_people))
    return {
        "comparison_rows": sorted(comparison_rows, key=lambda row: row["factor_name_ko"]),
        "pre_participant_count": len(pre_people),
        "post_participant_count": len(post_people),
        "paired_participant_count": len(paired_people),
        "attrition_count": attrition_count,
        "attrition_rate": round(attrition_count / len(pre_people) * 100, 1) if pre_people else None,
        "pre_na_items": _quality_total("na_items", "pre"),
        "post_na_items": _quality_total("na_items", "post"),
        "transfer_factors": transfer_factors,
        "min_group_n": min_group_n,
    }


def build_organization_report_model(
    aggregate_rows: Iterable[Mapping[str, Any]],
    *,
    participant_count: int,
    project_name: str,
    report_period: str,
    target_means: Mapping[str, float] | None = None,
    organization_priorities: set[str] | None = None,
    is_sample: bool = False,
    demo_target: float | None = None,
    pre_post_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    targets = {str(code): float(value) for code, value in (target_means or {}).items()}
    selected_priorities = organization_priorities or set()
    factors: list[dict[str, Any]] = []
    suppressed = 0
    for source in aggregate_rows:
        code = str(source["factor_code"])
        score = source.get("group_mean")
        if score is None:
            suppressed += 1
            continue
        target = targets.get(code)
        target_source = "프로젝트 설정"
        if target is None and is_sample and demo_target is not None:
            target = float(demo_target)
            target_source = "데모 임시값"
        gap = round(max(0.0, target - float(score)), 2) if target is not None else None
        factors.append(
            {
                "factor_code": code,
                "factor_name_ko": str(source["factor_name_ko"]),
                "n": int(source["n"]),
                "score": float(score),
                "target": target,
                "target_source": target_source if target is not None else None,
                "gap": gap,
                "organization_priority": code in selected_priorities,
            }
        )

    factors.sort(key=lambda row: (-row["score"], row["factor_name_ko"]))
    strength = factors[0] if factors else None
    development = factors[-1] if factors else None
    has_targets = any(row["target"] is not None for row in factors)
    if has_targets:
        priority_candidates = [row for row in factors if (row["gap"] or 0) > 0]
        priority_candidates.sort(
            key=lambda row: (
                not row["organization_priority"],
                -float(row["gap"] or 0),
                row["factor_name_ko"],
            )
        )
    else:
        priority_candidates = sorted(factors, key=lambda row: (row["score"], row["factor_name_ko"]))

    model = {
        "project_name": project_name,
        "report_period": report_period,
        "generated_on": date.today().isoformat(),
        "participant_count": int(participant_count),
        "published_factor_count": len(factors),
        "suppressed_factor_count": suppressed,
        "factors": factors,
        "strength": strength,
        "development": development,
        "priorities": priority_candidates[:3],
        "has_targets": has_targets,
        "is_sample": bool(is_sample),
        "demo_target_used": bool(is_sample and any(row["target_source"] == "데모 임시값" for row in factors)),
    }
    if pre_post_summary and pre_post_summary.get("comparison_rows"):
        comparison_rows = [dict(row) for row in pre_post_summary["comparison_rows"]]
        public_changes = [row for row in comparison_rows if row.get("change") is not None]
        model["pre_post"] = {
            "comparison_rows": comparison_rows,
            "pre_participant_count": int(pre_post_summary.get("pre_participant_count", 0)),
            "post_participant_count": int(pre_post_summary.get("post_participant_count", 0)),
            "paired_participant_count": int(pre_post_summary.get("paired_participant_count", 0)),
            "attrition_count": int(pre_post_summary.get("attrition_count", 0)),
            "attrition_rate": pre_post_summary.get("attrition_rate"),
            "pre_na_items": pre_post_summary.get("pre_na_items"),
            "post_na_items": pre_post_summary.get("post_na_items"),
            "transfer_factors": dict(pre_post_summary.get("transfer_factors", {})),
            "largest_change": max(public_changes, key=lambda row: abs(float(row["change"]))) if public_changes else None,
            "min_group_n": int(pre_post_summary.get("min_group_n", 5)),
        }
    return model


def _score_text(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


_PRE_POST_CSS = """
.tap-change-list{display:grid;gap:12px}.tap-change-row{display:grid;grid-template-columns:42mm 1fr 16mm;gap:10px;align-items:center;padding:10px 0;border-bottom:1px solid #edf2f1;break-inside:avoid;page-break-inside:avoid}.tap-change-row b,.tap-change-row small{display:block}.tap-change-row b{font-size:12px}.tap-change-row small{font-size:9px;color:#53696b;margin-top:2px}.tap-change-track{position:relative;height:18px}.tap-change-track:before{content:"";position:absolute;left:0;right:0;top:8px;height:2px;background:#dfe9e7}.tap-change-link{position:absolute;top:7px;height:4px;border-radius:9px;background:#7dcfc7}.tap-change-dot{position:absolute;top:3px;width:11px;height:11px;border-radius:50%;transform:translateX(-50%);border:2px solid #fff;box-shadow:0 0 0 1px #a8b8b6}.tap-change-dot.pre{background:#8a9998}.tap-change-dot.post{background:#087b76;box-shadow:0 0 0 1px #087b76}.tap-change-value{text-align:right;font-size:12px}.tap-change-value.positive{color:#087b76}.tap-change-value.negative{color:#963728}.tap-legend{display:flex;gap:14px;margin:8px 0 18px;color:#53696b;font-size:10px}.tap-legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}.tap-legend .pre{background:#8a9998}.tap-legend .post{background:#087b76}.tap-transfer-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.tap-transfer-card{border:1px solid #d8e4e2;border-radius:13px;padding:16px}.tap-transfer-card b,.tap-transfer-card span{display:block}.tap-transfer-card b{font-size:11px}.tap-transfer-card strong{display:block;font-size:23px;margin:8px 0 3px}.tap-transfer-card span{font-size:9px;color:#53696b;line-height:1.45}.tap-action-list{display:grid;gap:9px;margin-top:18px}.tap-action{display:grid;grid-template-columns:24px 1fr;gap:10px;padding:12px;border-radius:11px;background:#f7faf9}.tap-action>span{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;background:#087b76;color:#fff;font-size:10px;font-weight:900}.tap-action b,.tap-action small{display:block}.tap-action small{color:#53696b;margin-top:3px;font-size:9px}.tap-quality-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin:16px 0}.tap-quality-grid div{padding:12px;border:1px solid #d8e4e2;border-radius:11px}.tap-quality-grid b,.tap-quality-grid span{display:block}.tap-quality-grid b{font-size:18px}.tap-quality-grid span{font-size:9px;color:#53696b;margin-top:3px}
"""

_PRE_POST_CHANGE_ROWS_PER_PAGE = 10
_PRE_POST_DETAIL_ROWS_PER_PAGE = 12


def _page_chunks(rows: list[str], page_size: int) -> list[list[str]]:
    """Return at least one A4 page chunk, including for an empty result set."""
    if not rows:
        return [[]]
    return [rows[start : start + page_size] for start in range(0, len(rows), page_size)]


def _pre_post_report_body(model: Mapping[str, Any]) -> str:
    pre_post = dict(model["pre_post"])
    comparison_rows = list(pre_post["comparison_rows"])
    sample_badge = '<span class="tap-report-watermark">예시 데이터</span>' if model.get("is_sample") else ""
    largest = pre_post.get("largest_change")
    attrition_rate = pre_post.get("attrition_rate")
    attrition_text = "—" if attrition_rate is None else f"{float(attrition_rate):.1f}%"

    if largest:
        summary = (
            f"짝지어진 참여자 기준 가장 큰 관찰 변화는 <b>{escape(str(largest['factor_name_ko']))}</b> "
            f"{float(largest['change']):+.2f}점입니다. 비교집단이 없는 자기보고 변화는 교육의 인과효과로 확정하지 않습니다."
        )
    else:
        summary = "공개 가능한 짝지어진 결과가 없습니다. 사전·사후 완료자 수와 소표본 보호기준을 확인하세요."

    change_rows: list[str] = []
    detail_rows: list[str] = []
    for row in comparison_rows:
        pre_score = row.get("pre_mean")
        post_score = row.get("post_mean")
        change = row.get("change")
        if pre_score is not None and post_score is not None:
            pre_pos = max(0.0, min(100.0, (float(pre_score) - 1) / 4 * 100))
            post_pos = max(0.0, min(100.0, (float(post_score) - 1) / 4 * 100))
            link_left = min(pre_pos, post_pos)
            link_width = abs(post_pos - pre_pos)
            tone = "positive" if float(change or 0) >= 0 else "negative"
            change_rows.append(
                f"""
                <div class="tap-change-row">
                  <div><b>{escape(str(row['factor_name_ko']))}</b><small>교육 전 {float(pre_score):.2f} · 교육 후 {float(post_score):.2f} · 짝지어진 N={row['paired_n']}</small></div>
                  <div class="tap-change-track"><span class="tap-change-link" style="left:{link_left:.1f}%;width:{link_width:.1f}%"></span><i class="tap-change-dot pre" style="left:{pre_pos:.1f}%"></i><i class="tap-change-dot post" style="left:{post_pos:.1f}%"></i></div>
                  <strong class="tap-change-value {tone}">{float(change):+.2f}</strong>
                </div>
                """
            )
        detail_rows.append(
            "<tr>"
            f"<td>{escape(str(row['factor_name_ko']))}</td>"
            f"<td>{row['pre_n']}</td><td>{row['post_n']}</td><td>{row['paired_n']}</td>"
            f"<td>{_score_text(pre_score)}</td><td>{_score_text(post_score)}</td>"
            f"<td>{'—' if change is None else f'{float(change):+.2f}'}</td>"
            f"<td>{escape(str(row['status']))}</td></tr>"
        )

    transfer_factors = dict(pre_post.get("transfer_factors", {}))
    transfer_cards = []
    for label in ("업무 적용기회", "상사·동료 지원", "도구·권한 지원", "시간·프로세스 지원"):
        detail = transfer_factors.get(label)
        if isinstance(detail, Mapping):
            value = detail.get("mean")
            n = int(detail.get("n", 0))
            display = "비공개" if value is None else f"{float(value):.2f}"
            note = f"짝지어진 응답 N={n} · {detail.get('status', '')}"
        else:
            value = detail
            display = "미수집" if value is None else f"{float(value):.2f}"
            note = "사후 1~5점 평균" if value is not None else "후속 설문에서 확인 필요"
        transfer_cards.append(
            f'<div class="tap-transfer-card"><b>{label}</b><strong>{display}</strong><span>{note}</span></div>'
        )

    public_changes = [float(row["change"]) for row in comparison_rows if row.get("change") is not None]
    average_change = mean(public_changes) if public_changes else None
    action_rows = [
        ("1", "변화가 작거나 감소한 역량", "교육내용보다 적용기회·상사지원·도구·권한을 먼저 확인합니다."),
        ("2", "변화가 확인된 행동", "현업 과제와 피드백으로 반복해 유지 여부를 다음 추적검사에서 확인합니다."),
        ("3", "다음 측정", "같은 문항·척도·회상기간과 도구버전을 유지하고 짝지어진 참여자를 추적합니다."),
    ]
    actions = "".join(
        f'<div class="tap-action"><span>{number}</span><div><b>{title}</b><small>{detail}</small></div></div>'
        for number, title, detail in action_rows
    )
    average_change_text = "—" if average_change is None else f"{average_change:+.2f}"
    pre_na = "미수집" if pre_post.get("pre_na_items") is None else str(pre_post["pre_na_items"])
    post_na = "미수집" if pre_post.get("post_na_items") is None else str(pre_post["post_na_items"])

    change_chunks = _page_chunks(change_rows, _PRE_POST_CHANGE_ROWS_PER_PAGE)
    change_pages: list[str] = []
    for page_number, page_rows in enumerate(change_chunks, start=1):
        page_label = f" ({page_number}/{len(change_chunks)})" if len(change_chunks) > 1 else ""
        average_block = (
            f'<div class="tap-report-method"><b>관찰 변화 평균</b><span>{average_change_text}점 · '
            "역량별 차이와 적용 맥락을 함께 확인하세요.</span></div>"
            if page_number == len(change_chunks)
            else ""
        )
        change_pages.append(
            dedent(f"""
            <section class="tap-report-sheet tap-report-change-page">
              {sample_badge}
              <div class="tap-report-kicker">01 · 교육 전후 비교{page_label}</div>
              <h2>교육 전과 교육 후를 같은 1~5점 축에서 봅니다</h2>
              <p class="tap-report-desc">회색은 교육 전, 청록은 교육 후입니다. 변화량은 같은 참여자의 사후−사전 평균이며 작은 차이를 효과로 단정하지 않습니다.</p>
              <div class="tap-legend"><span><i class="pre"></i>교육 전</span><span><i class="post"></i>교육 후</span><span>공개 기준 짝지어진 참여자 N≥{pre_post.get('min_group_n', 5)}</span></div>
              <div class="tap-change-list">{''.join(page_rows) or '<p>공개 가능한 비교 결과 없음</p>'}</div>
              {average_block}
              <footer>서로 다른 참여자 집단의 평균을 단순 차감하지 않았습니다.</footer>
            </section>
            """).strip()
        )

    detail_chunks = _page_chunks(detail_rows, _PRE_POST_DETAIL_ROWS_PER_PAGE)
    detail_pages: list[str] = []
    for page_number, page_rows in enumerate(detail_chunks, start=1):
        page_label = f" ({page_number}/{len(detail_chunks)})" if len(detail_chunks) > 1 else ""
        quality_block = (
            f"""
            <div class="tap-quality-grid">
              <div><b>{pre_post['paired_participant_count']}명</b><span>짝지어진 참여자</span></div>
              <div><b>{pre_post['attrition_count']}명</b><span>사후 미완료</span></div>
              <div><b>{pre_na}</b><span>교육 전 수행기회 없음</span></div>
              <div><b>{post_na}</b><span>교육 후 수행기회 없음</span></div>
            </div>
            """
            if page_number == 1
            else ""
        )
        method_block = (
            f"""
            <div class="tap-report-method-grid">
              <div><b>비교 규칙</b><span>동일 교육 참여자 ID·동일 역량·교육 전/후가 모두 있는 참여자만 변화 산출</span></div>
              <div><b>집계 보호</b><span>짝지어진 참여자 N&lt;{pre_post.get('min_group_n', 5)} 비공개. 이 기준은 통계적 안정성을 보장하지 않음</span></div>
              <div><b>허용 표현</b><span>교육 전후 자기보고 행동빈도 변화</span></div>
              <div><b>금지 표현</b><span>비교집단 없는 결과를 교육의 인과효과로 확정</span></div>
            </div>
            """
            if page_number == len(detail_chunks)
            else ""
        )
        detail_pages.append(
            dedent(f"""
            <section class="tap-report-sheet tap-report-detail-page">
              {sample_badge}
              <div class="tap-report-kicker">03 · 데이터 품질 및 상세{page_label}</div>
              <h2>짝지어진 N과 수행기회 정보를 함께 공개합니다</h2>
              {quality_block}
              <table class="tap-report-table"><thead><tr><th>역량</th><th>전 N</th><th>후 N</th><th>짝지어진 N</th><th>교육 전</th><th>교육 후</th><th>변화</th><th>상태</th></tr></thead><tbody>{''.join(page_rows)}</tbody></table>
              {method_block}
              <footer>KMA TAP · 도구버전, 검사 간격, 회상기간을 동일하게 유지하세요.</footer>
            </section>
            """).strip()
        )

    return dedent(f"""
    <section class="tap-report-sheet tap-report-cover">
      {sample_badge}
      <header class="tap-report-brand"><span>TAP</span><div><b>KMA TAP</b><small>교육 전·후 업무행동 변화</small></div></header>
      <div class="tap-report-kicker">조직 리포트 · 짝지어진 비교</div>
      <h1>조직 교육 전·후 변화 리포트</h1>
      <p class="tap-report-lead">같은 참여자의 교육 전·후 응답을 연결해 관찰된 행동빈도 변화를 확인합니다.</p>
      <div class="tap-report-meta"><b>{escape(str(model['project_name']))}</b><span>{escape(str(model['report_period']))}</span><span>생성일 {model['generated_on']}</span></div>
      <div class="tap-report-kpis">
        <div><b>{pre_post['pre_participant_count']}명</b><span>교육 전 참여</span></div>
        <div><b>{pre_post['post_participant_count']}명</b><span>교육 후 참여</span></div>
        <div><b>{pre_post['paired_participant_count']}명</b><span>짝지어진 참여자</span></div>
        <div><b>{attrition_text}</b><span>사후 이탈률</span></div>
      </div>
      <div class="tap-report-summary">{summary}</div>
      <footer>자기보고 행동빈도 · 동일 참여자 짝지어진 비교 · 개인순위 미제공</footer>
    </section>

    {'\n'.join(change_pages)}

    <section class="tap-report-sheet">
      {sample_badge}
      <div class="tap-report-kicker">02 · 전이요인과 후속조치</div>
      <h2>점수보다 먼저 실제 적용 여건을 확인합니다</h2>
      <p class="tap-report-desc">교육 후 행동은 학습뿐 아니라 업무 적용기회, 주변의 지원, 도구와 권한의 영향을 받습니다.</p>
      <div class="tap-transfer-grid">{''.join(transfer_cards)}</div>
      <div class="tap-action-list">{actions}</div>
      <div class="tap-report-warning"><b>해석 주의</b><span>비교집단이 없으면 관찰 변화에 업무환경 변화·검사효과·평균회귀가 포함될 수 있습니다.</span></div>
      <footer>낮은 사후점수만으로 재교육을 결정하지 말고 전이 장애요인을 먼저 확인하세요.</footer>
    </section>

    {'\n'.join(detail_pages)}
    """).strip()


def _report_body(model: Mapping[str, Any]) -> str:
    if model.get("pre_post"):
        return _pre_post_report_body(model)
    factors = list(model["factors"])
    strength = model.get("strength")
    development = model.get("development")
    sample_badge = '<span class="tap-report-watermark">예시 데이터</span>' if model.get("is_sample") else ""
    target_note = (
        "데모 화면의 목표 3.50은 임시값이며 실제 의사결정에 사용할 수 없습니다."
        if model.get("demo_target_used")
        else "목표수준은 직무분석과 전문가 합의를 거쳐 역량·대상별로 설정해야 합니다."
    )

    bars = []
    for row in factors:
        width = max(0.0, min(100.0, (float(row["score"]) - 1) / 4 * 100))
        target_label = f" · 목표 {_score_text(row['target'])}" if row["target"] is not None else ""
        bars.append(
            f"""
            <div class="tap-report-score-row">
              <div><b>{escape(row['factor_name_ko'])}</b><small>유효 N={row['n']}{target_label}</small></div>
              <div class="tap-report-bar"><i style="width:{width:.1f}%"></i></div>
              <strong>{row['score']:.2f}</strong>
            </div>
            """
        )

    priority_rows = []
    for index, row in enumerate(model["priorities"], start=1):
        if model["has_targets"]:
            detail = (
                f"현재 {row['score']:.2f} · 목표 {_score_text(row['target'])} · "
                f"격차 {_score_text(row['gap'])}"
            )
            label = "교육 검토 우선순위"
        else:
            detail = f"조직 평균 {row['score']:.2f} · 목표수준 미설정"
            label = "개발 탐색 후보"
        priority_rows.append(
            f"""
            <div class="tap-report-priority">
              <span>{index}</span>
              <div><b>{escape(row['factor_name_ko'])}</b><small>{escape(detail)}</small></div>
              <em>{label}</em>
            </div>
            """
        )

    detail_rows = []
    for row in sorted(factors, key=lambda item: item["factor_name_ko"]):
        status = "목표 있음" if row["target"] is not None else "목표 미설정"
        detail_rows.append(
            "<tr>"
            f"<td>{escape(row['factor_name_ko'])}</td>"
            f"<td>{row['n']}</td>"
            f"<td>{row['score']:.2f}</td>"
            f"<td>{_score_text(row['target'])}</td>"
            f"<td>{_score_text(row['gap'])}</td>"
            f"<td>{status}</td>"
            "</tr>"
        )

    if strength and development:
        summary = (
            f"상대적으로 높은 응답 영역 후보는 <b>{escape(strength['factor_name_ko'])}</b> "
            f"({strength['score']:.2f}), 개발 맥락을 먼저 탐색할 영역은 "
            f"<b>{escape(development['factor_name_ko'])}</b> ({development['score']:.2f})입니다. "
            "작은 차이는 측정오차일 수 있으므로 순위로 해석하지 않습니다."
        )
    else:
        summary = "공개할 수 있는 역량 결과가 없습니다. 표본수와 데이터 품질을 먼저 확인하세요."

    return dedent(f"""
    <section class="tap-report-sheet tap-report-cover">
      {sample_badge}
      <header class="tap-report-brand"><span>TAP</span><div><b>KMA TAP</b><small>교육수요·업무행동 점검</small></div></header>
      <div class="tap-report-kicker">조직 리포트 · 탐색용</div>
      <h1>조직 교육수요 리포트</h1>
      <p class="tap-report-lead">개인의 순위를 매기지 않고, 조직의 공통 개발영역과 교육 검토 순서를 확인합니다.</p>
      <div class="tap-report-meta"><b>{escape(str(model['project_name']))}</b><span>{escape(str(model['report_period']))}</span><span>생성일 {model['generated_on']}</span></div>
      <div class="tap-report-kpis">
        <div><b>{model['participant_count']}명</b><span>익명 참여자</span></div>
        <div><b>{model['published_factor_count']}개</b><span>공개 역량</span></div>
        <div><b>{model['suppressed_factor_count']}개</b><span>소표본 보호</span></div>
        <div><b>1~5점</b><span>행동빈도 평균</span></div>
      </div>
      <div class="tap-report-summary">{summary}</div>
      <footer>최근 8주 자기보고 · 유효 N≥5만 공개 · 규준/백분위/개인순위 미제공</footer>
    </section>

    <section class="tap-report-sheet">
      {sample_badge}
      <div class="tap-report-kicker">01 · 조직 역량 프로필</div>
      <h2>조직 평균은 ‘얼마나 자주 했는가’를 보여줍니다</h2>
      <p class="tap-report-desc">1점은 전혀 없었다, 5점은 거의 항상 있었다입니다. 역량 간 작은 차이를 서열로 확정하지 마세요.</p>
      <div class="tap-report-score-list">{''.join(bars) or '<p>공개 결과 없음</p>'}</div>
      <div class="tap-report-method"><b>해석 원칙</b><span>평균과 N을 함께 보고, 수행기회·권한·도구·프로세스 맥락을 확인합니다.</span></div>
      <footer>조직 평균은 개인점수의 단순 순위표가 아닙니다.</footer>
    </section>

    <section class="tap-report-sheet">
      {sample_badge}
      <div class="tap-report-kicker">02 · 다음 행동</div>
      <h2>{'교육 검토 우선순위' if model['has_targets'] else '개발 탐색 후보'}</h2>
      <p class="tap-report-desc">낮은 평균만으로 교육을 확정하지 않습니다. 목표, 조직 중요도, 학습희망, 교육으로 해결 가능한 원인을 함께 확인합니다.</p>
      <div class="tap-report-priority-list">{''.join(priority_rows) or '<p>우선 검토 후보 없음</p>'}</div>
      <div class="tap-report-warning"><b>교육 전 확인</b><span>권한·도구·인력·시간·프로세스가 주원인이면 교육보다 조직개선을 먼저 실행합니다.</span></div>
      <div class="tap-report-method"><b>목표수준 주의</b><span>{escape(target_note)}</span></div>
      <footer>추천점수는 검토 순서를 돕는 휴리스틱이며 교육효과를 보장하지 않습니다.</footer>
    </section>

    <section class="tap-report-sheet">
      {sample_badge}
      <div class="tap-report-kicker">03 · 상세 및 방법</div>
      <h2>공개 가능한 결과만 상세표에 포함했습니다</h2>
      <table class="tap-report-table"><thead><tr><th>역량</th><th>유효 N</th><th>평균</th><th>목표</th><th>격차</th><th>상태</th></tr></thead><tbody>{''.join(detail_rows)}</tbody></table>
      <div class="tap-report-method-grid">
        <div><b>도구 상태</b><span>전문가 예비검토·인지면접 전 탐색용</span></div>
        <div><b>집계 보호</b><span>N&lt;5 비공개. 개인정보 기준과 통계적 안정성 기준은 별도 검토</span></div>
        <div><b>허용 목적</b><span>교육수요 탐색과 개발 대화</span></div>
        <div><b>금지 목적</b><span>채용·승진·보상·성과평가의 단독 판단</span></div>
      </div>
      <footer>KMA TAP · 진단 버전과 검증 상태를 확인한 뒤 사용하세요.</footer>
    </section>
    """).strip()


def organization_report_fragment(model: Mapping[str, Any]) -> str:
    # Streamlit/Markdown은 여러 raw-HTML 블록 사이의 들여쓰기·공백을 코드블록으로
    # 재해석할 수 있다. 화면 삽입본만 한 줄로 압축하고, 인쇄 HTML은 원형을 유지한다.
    compact_body = "".join(line.strip() for line in _report_body(model).splitlines())
    extra_style = ""
    if model.get("pre_post"):
        extra_style = "<style>" + "".join(line.strip() for line in _PRE_POST_CSS.splitlines()) + "</style>"
    return f'{extra_style}<div class="tap-report-document">{compact_body}</div>'


def printable_organization_report_html(model: Mapping[str, Any]) -> str:
    css = """
    @page { size:A4; margin:0; }
    * { box-sizing:border-box; }
    body { margin:0; background:#e9efee; color:#102a2d; font-family:Pretendard,"Noto Sans KR","Malgun Gothic",sans-serif; }
    .tap-report-document { padding:18px 0; }
    .tap-report-sheet { position:relative; width:210mm; min-height:297mm; margin:0 auto 14px; padding:17mm 16mm 16mm; background:#fff; page-break-after:always; overflow:hidden; }
    .tap-report-sheet:last-child { page-break-after:auto; }
    .tap-report-brand { display:flex; align-items:center; gap:10px; margin-bottom:36mm; }
    .tap-report-brand>span { width:38px; height:38px; border-radius:11px; display:grid; place-items:center; background:#087b76; color:#fff; font-weight:900; }
    .tap-report-brand b,.tap-report-brand small { display:block; }.tap-report-brand small{color:#53696b;font-size:10px}
    .tap-report-kicker { color:#087b76; font-size:11px; font-weight:900; letter-spacing:.12em; margin-bottom:9px; }
    h1 { font-size:32px; margin:0; letter-spacing:-1.3px; } h2 { font-size:23px; margin:0 0 8px; letter-spacing:-.8px; }
    .tap-report-lead,.tap-report-desc { color:#53696b; line-height:1.65; }.tap-report-lead{font-size:15px;max-width:145mm}.tap-report-desc{font-size:12px;margin:0 0 20px}
    .tap-report-meta { display:flex; gap:14px; margin:20px 0; padding:12px 0; border-top:1px solid #d8e4e2; border-bottom:1px solid #d8e4e2; font-size:11px; color:#53696b; }.tap-report-meta b{color:#102a2d;margin-right:auto}
    .tap-report-kpis { display:grid; grid-template-columns:repeat(4,1fr); gap:9px; margin:21px 0; }.tap-report-kpis div{border:1px solid #d8e4e2;border-radius:13px;padding:13px}.tap-report-kpis b{display:block;font-size:20px}.tap-report-kpis span{font-size:10px;color:#53696b}
    .tap-report-summary { padding:18px; border-left:4px solid #087b76; background:#eff9f7; border-radius:8px; font-size:13px; line-height:1.65; }
    .tap-report-watermark { position:absolute; right:16mm; top:13mm; color:#963728; background:#fff0ec; border:1px solid #ffd0c8; border-radius:99px; padding:5px 9px; font-size:9px; font-weight:900; }
    footer { position:absolute; left:16mm; right:16mm; bottom:10mm; padding-top:8px; border-top:1px solid #d8e4e2; color:#708382; font-size:9px; }
    .tap-report-score-list { display:grid; gap:11px; }.tap-report-score-row{display:grid;grid-template-columns:42mm 1fr 12mm;gap:9px;align-items:center;padding:8px 0;border-bottom:1px solid #edf2f1}.tap-report-score-row b{display:block;font-size:12px}.tap-report-score-row small{font-size:9px;color:#53696b}.tap-report-score-row>strong{text-align:right;font-size:12px}.tap-report-bar{height:9px;background:#e8f0ef;border-radius:99px;overflow:hidden}.tap-report-bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#25c3b5,#087b76)}
    .tap-report-method,.tap-report-warning { display:flex; gap:12px; margin-top:18px; padding:13px 15px; border-radius:11px; background:#eff9f7; font-size:11px; }.tap-report-method b,.tap-report-warning b{min-width:24mm}.tap-report-method span,.tap-report-warning span{color:#53696b}.tap-report-warning{background:#fffaf0;border:1px solid #f1dfb5}
    .tap-report-priority-list{display:grid;gap:11px}.tap-report-priority{display:grid;grid-template-columns:28px 1fr auto;gap:11px;align-items:center;border:1px solid #d8e4e2;border-radius:14px;padding:14px}.tap-report-priority>span{width:28px;height:28px;border-radius:50%;display:grid;place-items:center;background:#087b76;color:#fff;font-weight:900}.tap-report-priority b,.tap-report-priority small{display:block}.tap-report-priority small{color:#53696b;margin-top:3px}.tap-report-priority em{font-style:normal;font-size:9px;color:#963728;background:#fff0ec;border-radius:99px;padding:5px 7px}
    .tap-report-table{width:100%;border-collapse:collapse;margin-top:16px}.tap-report-table th,.tap-report-table td{padding:9px 7px;border-bottom:1px solid #e7efee;font-size:10px;text-align:right}.tap-report-table th{background:#f7faf9;color:#53696b}.tap-report-table th:first-child,.tap-report-table td:first-child{text-align:left}
    .tap-report-method-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:18px}.tap-report-method-grid div{padding:12px;border:1px solid #d8e4e2;border-radius:11px}.tap-report-method-grid b,.tap-report-method-grid span{display:block}.tap-report-method-grid b{font-size:10px}.tap-report-method-grid span{font-size:9px;color:#53696b;margin-top:4px;line-height:1.45}
    @media print { body{background:#fff}.tap-report-document{padding:0}.tap-report-sheet{margin:0;box-shadow:none} }
    """
    css += _PRE_POST_CSS
    title = (
        f"{model['project_name']} 조직 교육 전·후 변화 리포트"
        if model.get("pre_post")
        else f"{model['project_name']} 조직 교육수요 리포트"
    )
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{escape(str(title))}</title><style>{css}</style></head>"
        f"<body><div class=\"tap-report-document\">{_report_body(model)}</div></body></html>"
    )
