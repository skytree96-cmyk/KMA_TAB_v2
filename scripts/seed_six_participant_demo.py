from __future__ import annotations

"""Build and optionally publish one privacy-safe six-participant demo fixture.

The default command only writes a local JSON bundle. GitHub writes require the
explicit ``--apply`` flag. The disposable company proof is read from an
environment variable and is never written to a file or printed.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tap.aggregation import aggregate_factor_results
from tap.config import MIN_GROUP_N
from tap.dashboard import completed_store_submission_factor_rows
from tap.data import load_competencies, questions_for_factors
from tap.github_demo_store import (
    ROOT_PATH,
    DemoStoreConfig,
    DemoStoreError,
    GitHubDemoStore,
    _validate_company_registry,
    _validate_project_index,
    _validate_project_payload,
    _validate_submission_payload,
    company_approval_status,
    project_payload_from_state,
    submission_payload_from_state,
)
from tap.radar import build_pre_post_radar
from tap.reporting import build_pre_post_group_summary, prepare_group_results
from tap.tenant import (
    CompanyIdentity,
    derive_company_identity,
    hash_company_access_code,
)


FIXTURE_GENERATED_AT = "2026-08-21T09:00:00Z"
SYNTHETIC_COMPANY_NAME = "TAP 합성 예시기업"
SYNTHETIC_PROJECT_ID = "TAP-SYNTH-N6-202608"
SYNTHETIC_PROJECT_NAME = "합성 6인 공통역량 교육"
SYNTHETIC_PARTICIPANT_COUNT = 6
SYNTHETIC_FACTOR_CODES = (
    "CORE-CO",
    "CORE-CL",
    "CORE-GM",
    "JOB-ST",
    "JOB-PS",
    "JOB-EX",
    "LEAD-PD",
    "LEAD-CI",
)

_PRE_FACTOR_CENTERS = (2, 3, 3, 2, 3, 2, 2, 3)
_POST_FACTOR_GAINS = (2, 1, 1, 2, 1, 2, 1, 1)
_ALLOWED_BARRIERS = (
    "시간·프로세스 제약",
    "도구·정보·권한 부족",
    "특별한 방해요인 없음",
)


def _snapshot(project_name: str) -> tuple[list[dict[str, Any]], list[str], str]:
    questions = questions_for_factors(list(SYNTHETIC_FACTOR_CODES))
    found_factors = {str(row["factor_code"]) for row in questions}
    if found_factors != set(SYNTHETIC_FACTOR_CODES):
        missing = sorted(set(SYNTHETIC_FACTOR_CODES) - found_factors)
        raise DemoStoreError(f"합성 fixture 문항은행에서 역량을 찾지 못했습니다: {missing}")

    ordered = sorted(
        questions,
        key=lambda row: hashlib.sha256(
            f"{project_name}|{row['question_code']}".encode("utf-8")
        ).hexdigest(),
    )
    snapshot_rows = sorted(
        (
            str(row["question_code"]),
            str(row["revised_text"]),
            str(row.get("scoring_direction", "direct")),
        )
        for row in ordered
    )
    snapshot_hash = hashlib.sha256(
        "\n".join("|".join(parts) for parts in snapshot_rows).encode("utf-8")
    ).hexdigest()
    return ordered, [str(row["question_code"]) for row in ordered], snapshot_hash


def _responses(
    questions: list[dict[str, Any]], participant_index: int
) -> tuple[dict[str, int], dict[str, int]]:
    pre: dict[str, int] = {}
    post: dict[str, int] = {}
    factor_index = {code: index for index, code in enumerate(SYNTHETIC_FACTOR_CODES)}
    for row in questions:
        code = str(row["question_code"])
        factor_position = factor_index[str(row["factor_code"])]
        item_position = int(row["item_order"]) - 1
        jitter = ((participant_index * 2 + item_position + factor_position) % 3) - 1
        before = max(1, min(4, _PRE_FACTOR_CENTERS[factor_position] + jitter))
        nominal_gain = _POST_FACTOR_GAINS[factor_position]
        gain = max(
            0,
            nominal_gain
            - int((participant_index + item_position + factor_position) % 4 == 0),
        )
        pre[code] = before
        post[code] = min(5, before + gain)
    return pre, post


def build_fixture_bundle(
    *,
    company_identity: CompanyIdentity,
    company_access_digest: str,
    participant_salt: str,
    project_id: str = SYNTHETIC_PROJECT_ID,
    project_name: str = SYNTHETIC_PROJECT_NAME,
) -> dict[str, Any]:
    """Return a deterministic approved-company/project/submission bundle.

    ``company_identity`` and ``company_access_digest`` are already-safe opaque
    values. The function never accepts or stores a raw business registration
    number. Raw synthetic participant labels exist only long enough to derive
    project-scoped HMAC keys.
    """

    if company_identity.identity_source != "business_registration":
        raise DemoStoreError("합성 fixture 기업은 회사명·사업자등록번호 신청 방식을 사용해야 합니다.")

    questions, question_codes, snapshot_hash = _snapshot(project_name)
    target_means = {
        code: round(4.0 + (index % 3) * 0.1, 1)
        for index, code in enumerate(SYNTHETIC_FACTOR_CODES)
    }
    project_state: dict[str, Any] = {
        "project_id": project_id,
        "project_name": project_name,
        "course_name": "공통역량 교육 · 합성 fixture",
        "project_start_date": "2026-08-01",
        "project_end_date": "2026-08-05",
        "target_level": "manager",
        "training_date": "2026-08-07",
        "pre_start_date": "2026-08-01",
        "pre_end_date": "2026-08-05",
        "post_start_date": "2026-08-15",
        "post_end_date": "2026-08-20",
        "allow_schedule_override": False,
        "target_means": target_means,
        "organization_priorities": ["CORE-CO", "JOB-PS", "LEAD-PD"],
        "learner_interests": ["CORE-GM", "LEAD-CI"],
        "training_cause": "mixed_or_unknown",
        "delivery_preference": "all",
        "current_assessment_phase": "post",
        "selected_factors": list(SYNTHETIC_FACTOR_CODES),
        "assessment_version": f"TAP-1.0+{snapshot_hash[:12]}",
        "question_snapshot_hash": snapshot_hash,
        "question_snapshot_codes": question_codes,
        "project_created_at": FIXTURE_GENERATED_AT,
        **company_identity.to_payload(),
        "company_access_digest": company_access_digest,
    }
    project = project_payload_from_state(project_state)
    project["created_at"] = FIXTURE_GENERATED_AT
    project["updated_at"] = FIXTURE_GENERATED_AT

    submissions: list[dict[str, Any]] = []
    for participant_index in range(SYNTHETIC_PARTICIPANT_COUNT):
        pre, post = _responses(questions, participant_index)
        participant_label = f"SYNTHETIC-P{participant_index + 1:02d}"
        state = {
            **project_state,
            "participant_id": participant_label,
            "responses_by_phase": {"pre": pre, "post": post},
            "assessment_started_at_by_phase": {
                "pre": f"2026-08-05T00:{participant_index:02d}:00Z",
                "post": f"2026-08-20T00:{participant_index:02d}:00Z",
            },
            "assessment_completed_by_phase": {"pre": True, "post": True},
            "assessment_completed_at_by_phase": {
                "pre": "2026-08-05",
                "post": "2026-08-20",
            },
            "duration_seconds_by_phase": {
                "pre": 410 + participant_index * 13,
                "post": 385 + participant_index * 11,
            },
            "post_transfer_responses": {
                "application_opportunity": 3 + (participant_index % 3),
                "supervisor_support": 3 + ((participant_index + 1) % 3),
                "resources_authority": 3 + ((participant_index + 2) % 3),
                "time_process_support": 3 + (participant_index % 2),
                "barriers": [_ALLOWED_BARRIERS[participant_index % len(_ALLOWED_BARRIERS)]],
            },
        }
        submission = submission_payload_from_state(state, salt=participant_salt)
        submission["updated_at"] = FIXTURE_GENERATED_AT
        submissions.append(submission)

    company = {
        "schema_version": 1,
        "demo_only": True,
        "record_type": "company",
        **company_identity.to_payload(),
        "company_access_digest": company_access_digest,
        "approval_status": "approved",
        "requested_at": FIXTURE_GENERATED_AT,
        "reviewed_at": FIXTURE_GENERATED_AT,
        "review_note": "합성 6인 조직 리포트 검증용",
        "created_at": FIXTURE_GENERATED_AT,
        "updated_at": FIXTURE_GENERATED_AT,
    }
    project_index = {
        "schema_version": 1,
        "demo_only": True,
        "record_type": "project_index",
        "project_id": project_id,
        "company_id": company_identity.company_id,
        "updated_at": FIXTURE_GENERATED_AT,
    }
    return {
        "fixture_version": 1,
        "company": company,
        "project": project,
        "project_index": project_index,
        "submissions": submissions,
    }


def validate_fixture_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Validate privacy, completion, aggregation and eight-axis radar output."""

    company = dict(bundle["company"])
    project = dict(bundle["project"])
    submissions = [dict(row) for row in bundle["submissions"]]
    company_id = str(company["company_id"])
    expected_codes = set(str(code) for code in project["question_snapshot_codes"])

    _validate_company_registry(company)
    _validate_project_payload(project)
    _validate_project_index(dict(bundle["project_index"]))
    for submission in submissions:
        _validate_submission_payload(submission)

    if company_approval_status(company) != "approved":
        raise DemoStoreError("합성 기업은 approved 상태여야 합니다.")
    if len(submissions) != SYNTHETIC_PARTICIPANT_COUNT:
        raise DemoStoreError("합성 참여자는 정확히 6명이어야 합니다.")
    if len({str(row["participant_key"]) for row in submissions}) != 6:
        raise DemoStoreError("합성 참여자 가명키는 6개 모두 달라야 합니다.")
    for row in submissions:
        if row.get("company_id") != company_id:
            raise DemoStoreError("합성 제출의 company_id가 일치하지 않습니다.")
        for phase in ("pre", "post"):
            snapshot = dict(row["phases"][phase])
            if snapshot.get("completed") is not True:
                raise DemoStoreError("합성 제출은 교육 전·후 모두 완료되어야 합니다.")
            if set(str(code) for code in snapshot["responses"]) != expected_codes:
                raise DemoStoreError("합성 완료 제출에 전체 문항 응답이 필요합니다.")

    encoded = json.dumps(bundle, ensure_ascii=False, sort_keys=True)
    if "participant_id" in encoded or "SYNTHETIC-P" in encoded:
        raise DemoStoreError("합성 bundle에 원문 참여자 ID가 남아 있습니다.")
    if any(key in encoded.lower() for key in ("business_registration_number", "kma_assigned_code")):
        raise DemoStoreError("합성 bundle에 기업 식별 원문 필드가 남아 있습니다.")

    questions = questions_for_factors(list(project["selected_factors"]))
    warnings: list[str] = []
    factor_rows = completed_store_submission_factor_rows(
        submissions,
        questions,
        project_id=str(project["project_id"]),
        assessment_version=str(project["assessment_version"]),
        target_level=str(project["target_level"]),
        target_means=dict(project["target_means"]),
        question_snapshot_hash=str(project["question_snapshot_hash"]),
        warnings=warnings,
    )
    frame, errors, preparation_warnings = prepare_group_results(
        pd.DataFrame(factor_rows),
        load_competencies(),
        require_metadata=True,
        allow_schedule_override=False,
    )
    if errors:
        raise DemoStoreError("합성 조직 리포트 검증 실패: " + " | ".join(errors))
    warnings.extend(preparation_warnings)
    comparison = build_pre_post_group_summary(frame, min_group_n=MIN_GROUP_N)
    aggregates = aggregate_factor_results(
        frame.loc[frame["session_type"].eq("post")].to_dict("records"),
        min_group_n=MIN_GROUP_N,
    )
    radar = build_pre_post_radar(
        comparison["comparison_rows"],
        min_paired_n=MIN_GROUP_N,
        preferred_codes=SYNTHETIC_FACTOR_CODES,
    )
    if comparison["paired_participant_count"] != 6:
        raise DemoStoreError("전·후 비교 참여자 N이 6이 아닙니다.")
    if len(comparison["comparison_rows"]) != len(SYNTHETIC_FACTOR_CODES):
        raise DemoStoreError("전·후 비교 역량 수가 8이 아닙니다.")
    if any(row.get("status") != "공개" for row in comparison["comparison_rows"]):
        raise DemoStoreError("N≥5인데 공개되지 않은 합성 비교 역량이 있습니다.")
    if any(row.get("group_mean") is None or row.get("n") != 6 for row in aggregates):
        raise DemoStoreError("교육 후 조직 평균이 6명 기준으로 공개되지 않았습니다.")
    if radar["axis_count"] != len(SYNTHETIC_FACTOR_CODES):
        raise DemoStoreError("8각형 레이더 그래프 생성 검증에 실패했습니다.")

    return {
        "company_id": company_id,
        "company_name": str(company["company_name"]),
        "approval_status": "approved",
        "project_id": str(project["project_id"]),
        "participant_count": 6,
        "pre_completed": 6,
        "post_completed": 6,
        "paired_participant_count": 6,
        "published_factor_count": len(comparison["comparison_rows"]),
        "radar_axis_count": int(radar["axis_count"]),
        "warnings": warnings,
    }


def fixture_files(bundle: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Map the bundle to the exact demo-data branch paths."""

    company = dict(bundle["company"])
    project = dict(bundle["project"])
    company_id = str(company["company_id"])
    project_id = str(project["project_id"])
    root = f"{ROOT_PATH}/companies/{company_id}"
    files: dict[str, Mapping[str, Any]] = {
        f"{root}/company.json": company,
        f"{root}/projects/{project_id}.json": project,
        f"{ROOT_PATH}/project-index/{project_id}.json": dict(bundle["project_index"]),
    }
    for submission in bundle["submissions"]:
        participant_key = str(submission["participant_key"])
        files[f"{root}/submissions/{project_id}/{participant_key}.json"] = dict(
            submission
        )
    return files


def write_fixture_bundle(bundle: Mapping[str, Any], output_dir: Path) -> list[Path]:
    """Write a local mirror of the future demo-data paths; never contacts GitHub."""

    written: list[Path] = []
    for relative_path, payload in fixture_files(bundle).items():
        target = output_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(target)
    return written


def apply_fixture(
    bundle: Mapping[str, Any],
    *,
    config: DemoStoreConfig,
    disposable_company_proof: str,
) -> dict[str, Any]:
    """Publish through the guarded store API after an explicit CLI opt-in."""

    company = dict(bundle["company"])
    identity = derive_company_identity(
        salt=config.salt,
        company_name=str(company["company_name"]),
        business_registration_number=disposable_company_proof,
    )
    expected_digest = hash_company_access_code(
        identity.company_id, disposable_company_proof, config.salt
    )
    if identity.company_id != company.get("company_id") or expected_digest != company.get(
        "company_access_digest"
    ):
        raise DemoStoreError("합성 bundle과 일회성 기업 확인값이 일치하지 않습니다.")

    requester = GitHubDemoStore(config, company_access_code=disposable_company_proof)
    registry = requester.request_company_registration(
        identity.to_payload(), expected_digest
    )
    status = company_approval_status(registry)
    if status == "pending":
        reviewer = GitHubDemoStore(
            config,
            company_registration_code=config.company_code,
        )
        registry = reviewer.review_company_registration(
            identity.company_id,
            "approved",
            reviewer_note="합성 6인 조직 리포트 검증용",
        )
        status = company_approval_status(registry)
    if status != "approved":
        raise DemoStoreError(f"합성 기업 승인 상태가 {status!r}라 적용할 수 없습니다.")

    tenant_store = GitHubDemoStore(
        config,
        company_access_code=disposable_company_proof,
    )
    saved_project = tenant_store.save_project(bundle["project"])
    participant_store = GitHubDemoStore(
        config,
        participant_access_code=config.participant_code,
    )
    saved_submissions = [
        participant_store.save_submission(row) for row in bundle["submissions"]
    ]
    return {
        "company": registry,
        "project": saved_project,
        "submissions": saved_submissions,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="승인 기업 1곳·합성 참여자 6명의 교육 전·후 완료 fixture 생성"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp/six-participant-demo"),
        help="GitHub demo-data 경로를 미러링할 로컬 출력 폴더",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="검증 후 실제 configured demo-data branch에 저장",
    )
    parser.add_argument("--company-name", default=SYNTHETIC_COMPANY_NAME)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = DemoStoreConfig.from_sources(environ=os.environ)
    disposable_proof = os.environ.get("TAP_FIXTURE_COMPANY_PROOF", "").strip()
    if not config.salt:
        raise SystemExit("demo-store participant salt 환경설정이 필요합니다.")
    if not disposable_proof:
        raise SystemExit(
            "TAP_FIXTURE_COMPANY_PROOF 환경변수에 테스트 전용 10자리 값을 일회성으로 설정해 주세요."
        )

    identity = derive_company_identity(
        salt=config.salt,
        company_name=args.company_name,
        business_registration_number=disposable_proof,
    )
    digest = hash_company_access_code(
        identity.company_id, disposable_proof, config.salt
    )
    bundle = build_fixture_bundle(
        company_identity=identity,
        company_access_digest=digest,
        participant_salt=config.salt,
    )
    summary = validate_fixture_bundle(bundle)
    encoded = json.dumps(bundle, ensure_ascii=False)
    if disposable_proof in encoded:
        raise SystemExit("안전검사 실패: 일회성 기업 확인값이 출력 bundle에 포함되었습니다.")
    written = write_fixture_bundle(bundle, args.output_dir)
    summary["local_file_count"] = len(written)
    summary["output_dir"] = str(args.output_dir.resolve())

    if args.apply:
        if not config.company_code:
            raise SystemExit("--apply에는 KMA 기업 승인관리 코드 환경설정이 필요합니다.")
        if not config.participant_code:
            raise SystemExit("--apply에는 참여자 접속코드 환경설정이 필요합니다.")
        apply_fixture(
            bundle,
            config=config,
            disposable_company_proof=disposable_proof,
        )
        summary["applied"] = True
    else:
        summary["applied"] = False

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
