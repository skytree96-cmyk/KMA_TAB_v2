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
        AccountStore, AuthenticationError, AuthorizationError, ConflictError,
        hash_password,
    )
    from tap.data import questions_for_factors
    from tap.scoring import score_pre_post_responses

    now = [datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp()]
    initial = secrets.token_urlsafe(24)
    changed = secrets.token_urlsafe(24)
    reset = secrets.token_urlsafe(24)
    store = AccountStore(scoped_url, clock=lambda: now[0])
    store.initialize()
    seed_hash = hash_password(initial)
    _check(store.bootstrap_admin("check-admin", seed_hash))
    _check(not store.bootstrap_admin("check-admin-again", seed_hash))
    temporary_admin = store.login("check-admin", initial)
    admin = store.change_password(temporary_admin, initial, changed)
    _denied(AuthenticationError, store.principal, temporary_admin)
    company_a = store.create_company(admin, "Isolated Check A", "checka")
    company_b = store.create_company(admin, "Isolated Check B", "checkb")

    def user(login_id: str, role: str, company: dict):
        record = store.create_user(admin, login_id, "Isolated Test Account", role, company["id"], initial)
        temporary_token = store.login(login_id, initial)
        _check(store.principal(temporary_token)["must_change_password"])
        _denied(AuthorizationError, store.list_projects, temporary_token)
        return record, store.change_password(temporary_token, initial, changed)

    participant, participant_token = user("checka-one", "participant", company_a)
    _, peer_token = user("checka-two", "participant", company_a)
    _, other_company_token = user("checkb-manager", "company", company_b)
    project = store.create_project(admin, "Isolated PostgreSQL Check", {
        "company_id": company_a["id"], "selected_factors": ["CORE-CO"],
        "target_level": "manager", "course_name": "Persistence Check",
        "pre_start_date": "2026-09-07", "pre_end_date": "2026-09-09",
        "training_date": "2026-09-10", "post_start_date": "2026-11-05",
        "post_end_date": "2026-11-12", "target_means": {"CORE-CO": 3.5},
    })
    assignment = store.assign_participant(admin, project["id"], participant["id"])
    assignment_id = assignment["id"]
    codes = project["config"]["question_snapshot_codes"]
    _check(len(codes) == 4)
    own = store.list_assignments(participant_token)
    _check(len(own) == 1 and own[0]["id"] == assignment_id)
    _check(store.list_assignments(peer_token) == [])
    _check(store.list_projects(other_company_token) == [])
    _denied(AuthorizationError, store.project_results, other_company_token, project["id"])
    _denied(AuthorizationError, store.project_results, participant_token, project["id"])
    _denied(AuthorizationError, store.load_assessment, peer_token, assignment_id, "pre")

    draft = {"responses": {codes[0]: 0}, "current_question": 1,
             "started_at": now[0], "duration_seconds": 12}
    _denied(AuthorizationError, store.save_assessment, peer_token, assignment_id, "pre", draft, False)
    receipt = store.save_assessment(participant_token, assignment_id, "pre", draft, False)
    _check(receipt["completed"] is False and receipt["payload"] == draft)

    # A fresh store and fresh connections must recover the server draft.
    store = AccountStore(scoped_url, clock=lambda: now[0])
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
    print("POSTGRES ACCOUNT CHECK PASSED: pre/post persistence, tenant isolation, immutable submissions, reset/revocation, isolated schema cleaned", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
