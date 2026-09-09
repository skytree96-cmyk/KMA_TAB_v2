"""Exercise account persistence in a disposable, isolated PostgreSQL schema.

Normal use: set TEST_DATABASE_URL and run this file. Render's one-time startup
check additionally requires BOTH --render-preflight and TAP_POSTGRES_PREFLIGHT=1
before DATABASE_URL can be selected. Credentials and raw DB errors never print.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_RE = re.compile(r"tapcheck_[0-9a-f]{32}\Z")


class _StageFailure(Exception):
    """Carry only a static stage name and exception class, never DB messages."""

    def __init__(self, stage: str, error_type: str):
        self.stage = stage
        self.error_type = error_type
        super().__init__(stage)


@contextmanager
def _diagnostic_stage(stage: str):
    try:
        yield
    except _StageFailure:
        raise
    except Exception as exc:
        raise _StageFailure(stage, type(exc).__name__) from None


def _schema_url(dsn: str, schema: str) -> str:
    """Keep URL credentials/SSL settings but replace all search-path options."""
    if not SCHEMA_RE.fullmatch(schema):
        raise ValueError("Invalid isolated schema")
    parts = urlsplit(dsn)
    if parts.scheme not in {"postgres", "postgresql"} or not parts.netloc or parts.fragment:
        raise ValueError("A PostgreSQL URL is required")
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "options"]
    # No public/$user fallback: every unqualified AccountStore statement is
    # confined to the generated schema. pg_catalog remains implicitly visible.
    query.append(("options", f"-csearch_path={schema} -cstatement_timeout=15000 -clock_timeout=10000"))
    # libpq applies RFC 3986 percent decoding, not HTML form decoding: '+' is
    # literal. options arguments MUST use %20 for their separating spaces.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, quote_via=quote), ""))


@contextmanager
def _isolated_schema(dsn: str):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "tapcheck_" + uuid.uuid4().hex
    scoped_url = _schema_url(dsn, schema)
    # Parse using libpq before any mutation. The store accepts a URL, while
    # maintenance connections can use make_conninfo's keyword DSN directly.
    make_conninfo(scoped_url)
    maintenance_dsn = make_conninfo(
        dsn, options="-csearch_path=pg_catalog -cstatement_timeout=15000 -clock_timeout=10000",
        connect_timeout=10,
    )
    created = False
    schema_oid = None
    try:
        with _diagnostic_stage("schema-create"), psycopg.connect(maintenance_dsn, autocommit=True) as conn:
            # Deliberately omit IF NOT EXISTS: a collision must fail without
            # adopting, modifying, or deleting an already-existing schema.
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            created = True
            row = conn.execute(
                "SELECT oid, nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) "
                "FROM pg_namespace WHERE nspname=%s", (schema,),
            ).fetchone()
            if not row or not row[1]:
                raise RuntimeError("Schema ownership verification failed")
            schema_oid = row[0]
        with _diagnostic_stage("schema-isolation"), psycopg.connect(scoped_url, connect_timeout=10) as conn:
            current, paths = conn.execute("SELECT current_schema(), current_schemas(false)").fetchone()
            if current != schema or list(paths) != [schema]:
                raise RuntimeError("Schema isolation verification failed")
        yield scoped_url
    finally:
        if created:
            # This is the only destructive operation. Require the exact newly
            # created name, original OID, and current ownership before dropping.
            with _diagnostic_stage("schema-cleanup"), psycopg.connect(maintenance_dsn, autocommit=True) as conn:
                if not SCHEMA_RE.fullmatch(schema) or schema_oid is None:
                    raise RuntimeError("Schema cleanup guard failed")
                row = conn.execute(
                    "SELECT oid, nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) "
                    "FROM pg_namespace WHERE nspname=%s", (schema,),
                ).fetchone()
                if not row or row[0] != schema_oid or not row[1]:
                    raise RuntimeError("Schema cleanup ownership changed")
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _check(condition: bool) -> None:
    if not condition:
        raise AssertionError("PostgreSQL account check failed")


def _denied(exception_type, function, *args) -> None:
    try:
        function(*args)
    except exception_type:
        return
    raise AssertionError("An unauthorized operation succeeded")


def _exercise(scoped_url: str) -> None:
    from tap.account_store import (
        AccountStore, AuthenticationError, AuthorizationError, ConflictError, ValidationError,
        hash_password,
    )
    import psycopg
    from tap.data import questions_for_factors
    from tap.scoring import score_pre_post_responses

    now = [datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp()]
    initial = secrets.token_urlsafe(24)
    changed = secrets.token_urlsafe(24)
    reset = secrets.token_urlsafe(24)
    store = AccountStore(scoped_url, clock=lambda: now[0])
    # Create the prior schema and a real legacy user only in this isolated schema.
    legacy_schema = (ROOT / "database" / "account_schema.sql").read_text(encoding="utf-8")
    legacy_schema = legacy_schema.replace(" department TEXT NOT NULL DEFAULT '', job_title TEXT NOT NULL DEFAULT '',\n", "")
    legacy_schema = legacy_schema.replace(" email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',\n", "")
    with psycopg.connect(scoped_url, connect_timeout=10) as conn:
        for statement in legacy_schema.split(";"):
            if statement.strip():
                conn.execute(statement)
        columns = {row[0] for row in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='tap_users'")}
        _check(not {"department", "job_title", "email", "phone"} & columns)
    seed_hash = hash_password(initial)
    _check(store.bootstrap_admin("check-admin", seed_hash))
    store.initialize()
    store.initialize()
    _check(not store.bootstrap_admin("check-admin-again", seed_hash))
    temporary_admin = store.login("check-admin", initial)
    _check(all(store.principal(temporary_admin)[key] == "" for key in ("department", "job_title", "email", "phone")))
    admin = store.change_password(temporary_admin, initial, changed)
    _denied(AuthenticationError, store.principal, temporary_admin)
    company_a = store.create_company(admin, "Isolated Check A", "0123456789")
    company_b = store.create_company(admin, "Isolated Check B", "1234567890")

    def user(login_id: str, role: str, company: dict, profile=None):
        record = store.create_user(admin, login_id, "Isolated Test Account", role, company["id"], initial, profile=profile)
        temporary_token = store.login(login_id, initial)
        _check(store.principal(temporary_token)["must_change_password"])
        _denied(AuthorizationError, store.list_projects, temporary_token)
        return record, store.change_password(temporary_token, initial, changed)

    profile = {"department": "People", "job_title": "Manager", "email": "participant@example.invalid", "phone": "+82 10-1234-5678"}
    participant, participant_token = user("0123456789-participant001", "participant", company_a, profile=profile)
    _check({key: store.principal(participant_token)[key] for key in profile} == profile)
    _, peer_token = user("0123456789-participant002", "participant", company_a)
    _, other_company_token = user("manager001", "company", company_b)
    _check(participant["id"] not in {row["id"] for row in store.list_users(other_company_token)})
    project = store.create_project(admin, "Isolated PostgreSQL Check", {
        "company_id": company_a["id"], "selected_factors": ["CORE-CO"],
        "target_level": "manager", "course_name": "Persistence Check",
        "pre_start_date": "2026-09-07", "pre_end_date": "2026-09-09",
        "training_date": "2026-09-10", "post_start_date": "2026-11-05",
        "post_end_date": "2026-11-12", "target_means": {"CORE-CO": 3.5},
    })
    assignment = store.assign_participant(admin, project["id"], participant["id"])
    assignment_id = assignment["id"]
    corrected = store.set_company_registration_number(admin, company_a["id"], "0000000001")
    _check(corrected["id"] == company_a["id"] and corrected["registration_number"] == "0000000001")
    _check(store.principal(participant_token)["login_id"] == "0123456789-participant001")
    _denied(AuthorizationError, store.set_company_registration_number, other_company_token, company_a["id"], "2222222222")
    _denied(ConflictError, store.create_company, admin, "Duplicate Check", "0000000001")
    _denied(ConflictError, store.create_user, admin, "manager001", "Duplicate Account", "company", company_a["id"], initial)
    custom = store.create_user(admin, "participant001", "Custom ID", "participant", company_a["id"], initial)
    _check(custom["login_id"] == "participant001" and custom["company_id"] == company_a["id"])
    _denied(ConflictError, store.create_user, admin, "participant001", "Duplicate Custom ID", "participant", company_b["id"], initial)
    _denied(AuthorizationError, store.create_user, other_company_token, "another.custom", "Wrong Company", "participant", company_a["id"], initial)
    codes = project["config"]["question_snapshot_codes"]
    _check(len(codes) == 4)
    own = store.list_assignments(participant_token)
    _check(len(own) == 1 and own[0]["id"] == assignment_id)
    _check(store.list_assignments(peer_token) == [])
    _check(store.list_projects(other_company_token) == [])
    _denied(AuthorizationError, store.project_results, other_company_token, project["id"])
    _denied(AuthorizationError, store.project_results, participant_token, project["id"])
    _denied(AuthorizationError, store.load_assessment, peer_token, assignment_id, "pre")

    # Catalog overrides persist independently of already-created instruments.
    bank = {row["question_code"]: row for row in store.list_question_bank(admin)}
    _check(bank[codes[0]]["revision"] == 0)
    _denied(AuthorizationError, store.list_question_bank, other_company_token)
    _denied(AuthorizationError, store.save_question_text, participant_token, codes[0], "Denied edit", 0)
    edited = store.save_question_text(admin, codes[0], "Synthetic revised question", 0)
    _check(edited["revision"] == 1 and edited["updated_by"] == "check-admin")
    _denied(ConflictError, store.save_question_text, admin, codes[0], "Stale edit", 0)
    newer = store.create_project(admin, "New instrument", {**project["config"], "company_id": company_a["id"]})
    _check(newer["config"]["question_snapshot"][0]["revised_text"] == "Synthetic revised question")
    _check(newer["config"]["question_snapshot_hash"] != project["config"]["question_snapshot_hash"])
    projects = {row["id"]: row for row in store.list_projects(admin)}
    _check(projects[project["id"]]["config"] == project["config"])
    summary = store.dashboard_summary(admin)
    _check((summary["companies_count"], summary["company_users_count"], summary["participant_users_count"]) == (2, 1, 3))
    _check(len(summary["projects"]) == 2)
    _check(summary["participating_users_count"] == 0 and len(summary["company_participation"]) == 2)
    foreign_summary = store.dashboard_summary(other_company_token)
    _check(foreign_summary["companies_count"] == 1 and foreign_summary["projects"] == [])
    _check(foreign_summary["participant_users_count"] == 0)
    _denied(AuthorizationError, store.dashboard_summary, participant_token)

    draft = {"responses": {codes[0]: 0}, "current_question": 1,
             "started_at": now[0], "duration_seconds": 12}
    _denied(AuthorizationError, store.save_assessment, peer_token, assignment_id, "pre", draft, False)
    receipt = store.save_assessment(participant_token, assignment_id, "pre", draft, False)
    _check(receipt["completed"] is False and receipt["payload"] == draft)
    draft_summary = store.dashboard_summary(admin)
    _check(draft_summary["participating_users_count"] == 1 and draft_summary["pre_completed_users_count"] == 0)

    # A fresh store and fresh connections must recover the server draft.
    store = AccountStore(scoped_url, clock=lambda: now[0])
    _check({key: store.principal(participant_token)[key] for key in profile} == profile)
    restored_bank = {row["question_code"]: row for row in store.list_question_bank(admin)}
    _check(restored_bank[codes[0]] == edited)
    restored = store.load_assessment(participant_token, assignment_id, "pre")
    _check(restored is not None and restored["payload"] == draft and not restored["completed"])
    pre = {"responses": {code: 0 if index == 0 else 3 for index, code in enumerate(codes)},
           "current_question": len(codes), "started_at": now[0], "duration_seconds": 90}
    before = store.save_assessment(participant_token, assignment_id, "pre", pre, True)
    repeated = store.save_assessment(participant_token, assignment_id, "pre", pre, True)
    _check(before["completed"] is True and repeated["completed_at"] == before["completed_at"])
    _denied(ConflictError, store.save_assessment, participant_token, assignment_id, "pre", draft, False)

    # Advance only the isolated store's clock, then renew real stored sessions.
    now[0] = datetime(2026, 11, 6, tzinfo=timezone.utc).timestamp()
    store = AccountStore(scoped_url, clock=lambda: now[0])
    participant_token = store.login(participant["login_id"], changed)
    admin = store.login("check-admin", changed)
    _check(store.load_assessment(participant_token, assignment_id, "pre")["payload"] == pre)
    post = {"responses": {code: 0 if index == 0 else 4 for index, code in enumerate(codes)},
            "current_question": len(codes), "started_at": now[0], "duration_seconds": 95,
            "post_transfer_responses": {"application_opportunity": 4, "supervisor_support": 4,
                                        "resources_authority": 3, "time_process_support": 4,
                                        "barriers": [], "applied_content": "Synthetic isolated check"}}
    after = store.save_assessment(participant_token, assignment_id, "post", post, True)
    _check(after["completed"] is True)
    store = AccountStore(scoped_url, clock=lambda: now[0])
    _check(store.load_assessment(participant_token, assignment_id, "post")["payload"] == post)
    report = store.project_results(admin, project["id"])
    _check(len(report) == 1 and report[0]["user_id"] == participant["id"])
    _check(report[0]["pre_payload"] == pre and report[0]["post_payload"] == post)
    completed_summary = store.dashboard_summary(admin)
    _check((completed_summary["participating_companies_count"], completed_summary["participating_users_count"], completed_summary["pre_completed_users_count"], completed_summary["post_completed_users_count"]) == (1, 1, 1, 1))
    _check(len(completed_summary["completion_trend"]) == 12)
    _check(sum(row["pre_completed"] for row in completed_summary["completion_trend"]) == 1)
    _check(sum(row["post_completed"] for row in completed_summary["completion_trend"]) == 1)
    progress = {row["id"]: row for row in completed_summary["projects"]}
    _check((progress[project["id"]]["assigned"], progress[project["id"]]["pre_completed"], progress[project["id"]]["post_completed"]) == (1, 1, 1))
    comparison = score_pre_post_responses(questions_for_factors(["CORE-CO"]), pre["responses"], post["responses"])
    _check(len(comparison) == 1 and comparison[0]["paired_valid_items"] == 3
           and comparison[0]["self_reported_change"] == 1.0)

    store.reset_password(admin, participant["id"], reset)
    _denied(AuthenticationError, store.principal, participant_token)
    _denied(AuthenticationError, store.load_assessment, participant_token, assignment_id, "pre")
    reset_token = store.login(participant["login_id"], reset)
    _check(store.principal(reset_token)["must_change_password"])
    store.set_user_active(admin, participant["id"], False)
    _denied(AuthenticationError, store.principal, reset_token)
    store.set_user_active(admin, participant["id"], True)
    _denied(AuthenticationError, store.principal, reset_token)


    from scripts.seed_sundaeguk import seed_company
    from tap.account_reports import summarize_project
    # The earlier registration-edit check occupied the seed placeholder.
    store.set_company_registration_number(admin, company_a["id"], "0000000002")
    fixture = seed_company(store)
    _check(fixture["created"] and (fixture["total"], fixture["pre_completed"], fixture["post_completed"], fixture["nonparticipants"]) == (15, 5, 5, 10))
    repeat = seed_company(store)
    _check(not repeat["created"] and repeat["project_id"] == fixture["project_id"])
    seeded_project = next(p for p in store.list_projects(admin) if p["id"] == fixture["project_id"])
    seeded_results = store.project_results(admin, fixture["project_id"])
    _check(len(seeded_results) == 15)
    seeded_summary = summarize_project(seeded_project, seeded_results)
    _check(len(seeded_summary) == 6 and all(row["paired_n"] == 5 and row["pre_mean"] is not None and row["post_mean"] is not None for row in seeded_summary))
    company_summary = next(row for row in store.dashboard_summary(admin)["company_participation"] if row["company_id"] == fixture["company_id"])
    _check(company_summary["total"] == 15 and company_summary["participating"] == 5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check accounts in a disposable PostgreSQL schema.")
    parser.add_argument("--render-preflight", action="store_true", help="Use DATABASE_URL only with TAP_POSTGRES_PREFLIGHT=1.")
    args = parser.parse_args(argv)
    try:
        if args.render_preflight:
            if os.environ.get("TAP_POSTGRES_PREFLIGHT") != "1":
                raise PermissionError("Render preflight was not enabled")
            dsn = os.environ.get("DATABASE_URL", "")
        else:
            dsn = os.environ.get("TEST_DATABASE_URL", "")
        if not dsn:
            raise ValueError("An explicit database URL is required")
        with _isolated_schema(dsn) as scoped_url:
            with _diagnostic_stage("account-check"):
                _exercise(scoped_url)
    except Exception as exc:
        # Never print exception text/tracebacks, DSNs, passwords, or raw SQL.
        error_type = exc.error_type if isinstance(exc, _StageFailure) else type(exc).__name__
        stage = exc.stage if isinstance(exc, _StageFailure) else "configuration"
        print(f"POSTGRES ACCOUNT CHECK FAILED: {error_type}; stage={stage}", flush=True)
        return 1
    print("POSTGRES ACCOUNT CHECK PASSED: pre/post persistence, tenant isolation, immutable submissions, question catalog, dashboard scope, synthetic fixture, reset/revocation, isolated schema cleaned", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
