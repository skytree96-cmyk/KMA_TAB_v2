"""Explicit, additive server-side seed for the user-requested synthetic company.

Run only when requested: DATABASE_URL=... python scripts/seed_sundaeguk.py.
The fixture is committed atomically; collisions abort and reruns never overwrite it.
All participant names, answers and the registration number are synthetic.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tap.account_store import AccountStore, ConflictError, KST, SESSION_SECONDS, ValidationError

FIXTURE = "sundaeguk-report-test-v1"
COMPANY = "주식회사 순대국"
REGISTRATION = "0000000001"  # Synthetic placeholder, not a real registration.
PROJECT = "순대국 서비스 역량 향상 프로젝트 (테스트)"
MANAGER = "sundae.manager"
PARTICIPANTS = tuple(f"sundae{i:02d}" for i in range(1, 16))
FACTORS = ("CORE-CO", "CORE-CL", "CORE-GM", "JOB-ST", "JOB-PS", "JOB-EX")


class _AtomicStore(AccountStore):
    """Reuse all public validation and authorization within one owned transaction."""

    def __init__(self, source, connection):
        self.__dict__.update(source.__dict__)
        self._connection = connection

    @contextmanager
    def _transaction(self):
        yield self._connection


@contextmanager
def _internal_session(store, conn, user_id):
    # No login/password reset or cleanup of other users' sessions is performed.
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = store._clock()
    store._execute(conn, "INSERT INTO tap_sessions(token_hash,user_id,created_at,expires_at,last_seen_at) VALUES (?,?,?,?,?)",
                   (digest, user_id, now, now + SESSION_SECONDS, now))
    try:
        yield token
    finally:
        store._execute(conn, "DELETE FROM tap_sessions WHERE token_hash=?", (digest,))


def _result(store, conn, company, project, created):
    counts = store._one(conn, "SELECT COUNT(*) AS total,SUM(CASE WHEN pre.completed=1 THEN 1 ELSE 0 END) AS pre_completed,SUM(CASE WHEN post.completed=1 THEN 1 ELSE 0 END) AS post_completed,SUM(CASE WHEN pre.assignment_id IS NULL AND post.assignment_id IS NULL THEN 1 ELSE 0 END) AS nonparticipants FROM tap_assignments a LEFT JOIN tap_assessments pre ON pre.assignment_id=a.id AND pre.phase='pre' LEFT JOIN tap_assessments post ON post.assignment_id=a.id AND post.phase='post' WHERE a.project_id=?", (project["id"],))
    return {"created": created, "company": COMPANY, "company_id": company["id"],
            "project": project["name"], "project_id": project["id"],
            "manager_login": MANAGER, **counts}


def _payload(config, phase, person, now):
    before, after = (2, 3, 2, 3, 3, 4), (4, 4, 3, 4, 3, 3)
    scores = after if phase == "post" else before
    responses = {}
    for index, question in enumerate(config["question_snapshot"]):
        base = scores[FACTORS.index(question["factor_code"])]
        responses[question["question_code"]] = max(1, min(5, base + (person + index) % 3 - 1))
    payload = {"responses": responses, "current_question": len(responses),
               "started_at": now, "duration_seconds": 180 + person * 20}
    if phase == "post":
        payload["post_transfer_responses"] = {
            "application_opportunity": 4, "supervisor_support": 4,
            "resources_authority": 3 + person % 2, "time_process_support": 4,
            "barriers": ["특별한 방해요인 없음"],
            "applied_content": "[합성 테스트 응답] 고객 요청 공유와 서비스 개선 점검을 연습했습니다.",
        }
    return payload


def seed_company(store: AccountStore) -> dict:
    """Seed 15 assigned people, five paired completions and ten unanswered accounts.

    This server-only hook requires an already activated KMA administrator. It
    creates temporary internal sessions solely for this transaction, runs normal
    project/response validation, and leaves every new account on forced password
    change. Existing accounts, sessions, responses and fixtures are never reset.
    """
    with store._transaction() as conn:
        if not store._sqlite:
            store._execute(conn, "SELECT pg_advisory_xact_lock(847201932)")
        companies = store._all(conn, "SELECT * FROM tap_companies WHERE slug=? OR name=?", (REGISTRATION, COMPANY))
        if companies:
            if len(companies) != 1 or companies[0]["slug"] != REGISTRATION or companies[0]["name"] != COMPANY:
                raise ConflictError("테스트 회사명 또는 사업자등록번호가 이미 사용 중입니다.")
            company = companies[0]
            projects = store._all(conn, "SELECT * FROM tap_projects WHERE company_id=?", (company["id"],))
            fixtures = [p for p in projects if json.loads(p["config_json"]).get("seed_fixture") == FIXTURE]
            users = store._all(conn, "SELECT login_id,role FROM tap_users WHERE company_id=?", (company["id"],))
            expected = {(MANAGER, "company"), *((login, "participant") for login in PARTICIPANTS)}
            if len(fixtures) != 1 or not expected <= {(u["login_id"], u["role"]) for u in users}:
                raise ConflictError("기존 회사는 이 테스트 데이터로 확인되지 않아 변경하지 않았습니다.")
            return _result(store, conn, company, fixtures[0], False)
        logins = (MANAGER, *PARTICIPANTS)
        occupied = store._one(conn, "SELECT id FROM tap_users WHERE login_id IN (" + ",".join("?" for _ in logins) + ") LIMIT 1", logins)
        if occupied:
            raise ConflictError("테스트용 ID가 이미 사용 중이므로 데이터를 추가하지 않았습니다.")
        admin = store._one(conn, "SELECT id FROM tap_users WHERE role='kma' AND active=1 AND must_change_password=0 ORDER BY created_at,id LIMIT 1")
        if not admin:
            raise ValidationError("최초 비밀번호 변경을 마친 KMA 관리자 계정이 필요합니다.")
        atomic = _AtomicStore(store, conn)
        today = datetime.fromtimestamp(store._clock(), KST).date()
        with _internal_session(atomic, conn, admin["id"]) as admin_token:
            company = atomic.create_company(admin_token, COMPANY, REGISTRATION)
            atomic.create_user(admin_token, MANAGER, "순대국 테스트 교육담당자", "company", company["id"], "kma",
                               profile={"department": "교육운영팀", "job_title": "담당자"})
            project = atomic.create_project(admin_token, PROJECT, {
                "company_id": company["id"], "seed_fixture": FIXTURE,
                "course_name": "고객 서비스와 팀 협업 역량 교육 (테스트)",
                "selected_factors": list(FACTORS), "target_level": "staff",
                "pre_start_date": (today - timedelta(days=30)).isoformat(),
                "pre_end_date": today.isoformat(), "training_date": today.isoformat(),
                "post_start_date": today.isoformat(),
                "post_end_date": (today + timedelta(days=30)).isoformat(),
            })
            for index, login in enumerate(PARTICIPANTS):
                person = atomic.create_user(admin_token, login, f"테스트 참여자{index + 1:02d}", "participant", company["id"], "kma",
                                            profile={"department": ("고객서비스팀", "매장운영팀", "품질관리팀")[index % 3],
                                                     "job_title": ("사원", "주임", "대리")[index % 3]})
                assignment = atomic.assign_participant(admin_token, project["id"], person["id"])
                if index < 5:
                    # This applies only to newly created fixture users and is
                    # invisible outside the uncommitted transaction.
                    atomic._execute(conn, "UPDATE tap_users SET must_change_password=0 WHERE id=?", (person["id"],))
                    with _internal_session(atomic, conn, person["id"]) as participant_token:
                        for phase in ("pre", "post"):
                            atomic.save_assessment(participant_token, assignment["id"], phase,
                                                   _payload(project["config"], phase, index, store._clock()), True)
                    atomic._execute(conn, "UPDATE tap_users SET must_change_password=1 WHERE id=?", (person["id"],))
            atomic._audit(conn, admin["id"], "seed_" + FIXTURE, company["id"])
            return _result(atomic, conn, company, project, True)


def main():
    try:
        store = AccountStore(os.environ.get("DATABASE_URL", ""))
        print(json.dumps(seed_company(store), ensure_ascii=False))
    except Exception as exc:
        # Database exceptions may carry credentials or infrastructure details.
        print("SUNDAEGUK SEED FAILED: " + type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
