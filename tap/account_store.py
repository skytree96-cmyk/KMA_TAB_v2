"""PostgreSQL account, tenant and assessment boundary for the production app.

Every public operation revalidates its opaque session against the database. No
browser-supplied role, company or participant identifier is authoritative.
SQLite is explicitly opt-in for isolated tests, never an automatic DB fallback.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Any
import uuid

from tap.data import load_competencies, load_questions, questions_for_factors
from tap.selection import applicable_to_level, selection_errors


class AccountStoreError(ValueError):
    """Safe, user-facing operational error."""


class AuthenticationError(AccountStoreError):
    pass


class AuthorizationError(AccountStoreError):
    pass


class ValidationError(AccountStoreError):
    pass


class ConflictError(AccountStoreError):
    pass


class RateLimitError(AuthenticationError):
    pass


AccountError = AccountStoreError


SESSION_SECONDS = 8 * 60 * 60
SESSION_IDLE_SECONDS = 30 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
KST = timezone(timedelta(hours=9))
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 3
_LOGIN_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}\Z")
_REGISTRATION_RE = re.compile(r"[0-9]{10}\Z")
_PROFILE_LIMITS = {"department": 100, "job_title": 80, "email": 254, "phone": 40}
_PROFILE_LABELS = {"department": "부서", "job_title": "직급", "email": "이메일", "phone": "연락처"}
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")
_PHONE_RE = re.compile(r"\+?[0-9][0-9 ().-]*\Z")
_TRANSFER_KEYS = frozenset({"application_opportunity", "supervisor_support", "resources_authority", "time_process_support"})
_BARRIERS = frozenset({"적용 기회 부족", "상사·동료 지원 부족", "도구·정보·권한 부족", "시간·프로세스 제약", "특별한 방해요인 없음"})


def _password_input(password: str) -> bytes:
    if not isinstance(password, str) or not 3 <= len(password) <= 128:
        raise ValidationError("비밀번호는 3~128자여야 합니다.")
    return password.encode("utf-8")


def hash_password(password: str) -> str:
    """Salted scrypt: OWASP's 32 MiB, r=8, p=3 configuration."""
    raw = _password_input(password)
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(raw, salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
                           maxmem=64 * 1024 * 1024, dklen=32)
    return "$".join(("scrypt", str(_SCRYPT_N), str(_SCRYPT_R), str(_SCRYPT_P),
                     base64.b64encode(salt).decode(), base64.b64encode(value).decode()))


def _parse_hash(encoded: str) -> tuple[bytes, bytes]:
    try:
        algorithm, n, r, p, salt, digest = encoded.split("$")
        if (algorithm, int(n), int(r), int(p)) != ("scrypt", _SCRYPT_N, _SCRYPT_R, _SCRYPT_P):
            raise ValueError
        decoded_salt = base64.b64decode(salt, validate=True)
        decoded_hash = base64.b64decode(digest, validate=True)
        if len(decoded_salt) != 16 or len(decoded_hash) != 32:
            raise ValueError
        return decoded_salt, decoded_hash
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("지원하지 않는 초기 비밀번호 해시입니다.") from exc


def verify_password(password: str, encoded: str) -> bool:
    try:
        if not isinstance(password, str) or len(password) > 128:
            return False
        salt, expected = _parse_hash(encoded)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N,
                                r=_SCRYPT_R, p=_SCRYPT_P, maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _json(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > 500_000:
            raise ValueError
        return encoded
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValidationError("저장할 데이터 형식이나 크기가 올바르지 않습니다.") from exc


def _text(value: Any, label: str, maximum: int = 120) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum or any(ord(c) < 32 for c in value):
        raise ValidationError(f"{label}이 비어 있거나 올바르지 않습니다.")
    return value.strip()


def _login_id(value: Any) -> str:
    value = _text(value, "로그인 ID", 64).lower()
    if not _LOGIN_RE.fullmatch(value):
        raise ValidationError("ID는 영문 소문자·숫자·점·밑줄·하이픈으로 3~64자여야 합니다.")
    return value


class AccountStore:
    def __init__(self, dsn: str, *, allow_sqlite_for_tests: bool = False, clock=time.time):
        self._clock = clock
        self._sqlite = bool(allow_sqlite_for_tests and dsn.startswith("sqlite:///"))
        if self._sqlite:
            self._dsn = dsn[len("sqlite:///"):]
            if self._dsn == ":memory:":
                raise ValidationError("테스트 DB는 임시 파일 경로를 사용하세요.")
        elif isinstance(dsn, str) and dsn.startswith(("postgresql://", "postgres://")):
            self._dsn = dsn
        else:
            raise ValidationError("운영에는 PostgreSQL DATABASE_URL이 필요합니다.")

    @contextmanager
    def _transaction(self):
        if self._sqlite:
            conn = sqlite3.connect(self._dsn, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
        else:
            import psycopg
            from psycopg.rows import dict_row
            conn = psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=10)
        try:
            yield conn
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if isinstance(exc, sqlite3.IntegrityError) or getattr(exc, "sqlstate", "") in {"23505", "23503", "23514"}:
                raise ConflictError("이미 등록된 ID이거나 연결할 수 없는 데이터입니다.") from exc
            raise
        finally:
            conn.close()

    def _execute(self, conn, sql: str, params=()):
        return conn.execute(sql.replace("?", "%s") if not self._sqlite else sql, params)

    def _one(self, conn, sql: str, params=(), *, lock=False):
        if lock and not self._sqlite:
            sql += " FOR UPDATE"
        row = self._execute(conn, sql, params).fetchone()
        return dict(row) if row is not None else None

    def _all(self, conn, sql: str, params=()):
        return [dict(row) for row in self._execute(conn, sql, params).fetchall()]

    def initialize(self) -> None:
        schema = (Path(__file__).resolve().parents[1] / "database" / "account_schema.sql").read_text(encoding="utf-8")
        with self._transaction() as conn:
            if not self._sqlite:
                self._execute(conn, "SELECT pg_advisory_xact_lock(847201901)")
            for statement in schema.split(";"):
                if statement.strip():
                    self._execute(conn, statement)
            # Additive migration for databases created before optional profiles.
            # The existing initialization lock/transaction covers all columns.
            existing = {row["name"] for row in self._all(conn, "PRAGMA table_info(tap_users)")} if self._sqlite else set()
            for field in _PROFILE_LIMITS:
                if self._sqlite:
                    if field not in existing:
                        self._execute(conn, f"ALTER TABLE tap_users ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")
                else:
                    self._execute(conn, f"ALTER TABLE tap_users ADD COLUMN IF NOT EXISTS {field} TEXT NOT NULL DEFAULT ''")

    def bootstrap_admin(self, login_id: str, password_hash: str) -> bool:
        """Server-only seed hook. Never expose this method as an end-user form."""
        login_id = _login_id(login_id)
        _parse_hash(password_hash)
        with self._transaction() as conn:
            if not self._sqlite:
                self._execute(conn, "SELECT pg_advisory_xact_lock(847201901)")
            if self._one(conn, "SELECT id FROM tap_users LIMIT 1"):
                return False
            user_id = str(uuid.uuid4())
            self._execute(conn, "INSERT INTO tap_users(id,login_id,display_name,role,company_id,password_hash,created_at) VALUES (?,?,?,'kma',NULL,?,?)",
                          (user_id, login_id, "KMA 관리자", password_hash, self._clock()))
            self._audit(conn, user_id, "bootstrap_admin", user_id)
            return True

    def _audit(self, conn, actor_id, event, target_id):
        self._execute(conn, "INSERT INTO tap_audit_events(id,actor_id,event,target_id,created_at) VALUES (?,?,?,?,?)",
                      (str(uuid.uuid4()), actor_id, event, target_id, self._clock()))

    def _new_session(self, conn, user_id) -> str:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        self._execute(conn, "DELETE FROM tap_sessions WHERE expires_at <= ? OR last_seen_at <= ?", (now, now - SESSION_IDLE_SECONDS))
        self._execute(conn, "INSERT INTO tap_sessions(token_hash,user_id,created_at,expires_at,last_seen_at) VALUES (?,?,?,?,?)",
                      (hashlib.sha256(token.encode()).hexdigest(), user_id, now, now + SESSION_SECONDS, now))
        return token

    def login(self, login_id: str, password: str) -> str:
        # Unknown IDs follow the same persisted failure path and expensive hash check.
        normalized = str(login_id or "").strip().lower()[:128]
        login_key = hashlib.sha256(normalized.encode()).hexdigest()
        failure = None
        token = None
        with self._transaction() as conn:
            now = self._clock()
            user = self._one(conn, "SELECT * FROM tap_users WHERE login_id=?", (normalized,), lock=True)
            company = self._one(conn, "SELECT active FROM tap_companies WHERE id=?", (user["company_id"],)) if user and user["company_id"] else None
            self._execute(conn, "INSERT INTO tap_login_attempts(login_hash,window_start) VALUES (?,?) ON CONFLICT (login_hash) DO NOTHING", (login_key, now))
            attempt = self._one(conn, "SELECT * FROM tap_login_attempts WHERE login_hash=?", (login_key,), lock=True)
            if attempt["locked_until"] > now:
                failure = RateLimitError("로그인 시도가 많습니다. 15분 후 다시 시도하세요.")
            else:
                # Random dummy salt/digest does equal work without storing a default credential.
                dummy = "$".join(("scrypt", str(_SCRYPT_N), str(_SCRYPT_R), str(_SCRYPT_P), base64.b64encode(b"\0" * 16).decode(), base64.b64encode(b"\0" * 32).decode()))
                correct = verify_password(password, user["password_hash"] if user else dummy)
                if not correct or not user or not user["active"] or (user["company_id"] and (not company or not company["active"])):
                    failures = (attempt["failures"] if now - attempt["window_start"] < LOGIN_WINDOW_SECONDS else 0) + 1
                    start = attempt["window_start"] if now - attempt["window_start"] < LOGIN_WINDOW_SECONDS else now
                    self._execute(conn, "UPDATE tap_login_attempts SET failures=?,window_start=?,locked_until=? WHERE login_hash=?",
                                  (failures, start, now + LOGIN_WINDOW_SECONDS if failures >= LOGIN_MAX_FAILURES else 0, login_key))
                    failure = AuthenticationError("ID 또는 비밀번호를 확인하세요.")
                else:
                    self._execute(conn, "DELETE FROM tap_login_attempts WHERE login_hash=?", (login_key,))
                    token = self._new_session(conn, user["id"])
        if failure:
            raise failure
        return token

    def _require(self, conn, token, roles=None, *, allow_password_change=False):
        if not isinstance(token, str) or not 32 <= len(token) <= 128:
            raise AuthenticationError("다시 로그인해 주세요.")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = self._clock()
        user = self._one(conn, "SELECT u.*,c.name AS company_name,c.slug AS company_slug,c.active AS company_active FROM tap_sessions s JOIN tap_users u ON u.id=s.user_id LEFT JOIN tap_companies c ON c.id=u.company_id WHERE s.token_hash=? AND s.expires_at>? AND s.last_seen_at>?", (token_hash, now, now - SESSION_IDLE_SECONDS))
        if user:
            # Serialize each user's requests with password resets/deactivation, then
            # re-read the session after the lock so a revoked token cannot race in.
            self._one(conn, "SELECT id FROM tap_users WHERE id=?", (user["id"],), lock=True)
            user = self._one(conn, "SELECT u.*,c.name AS company_name,c.slug AS company_slug,c.active AS company_active FROM tap_sessions s JOIN tap_users u ON u.id=s.user_id LEFT JOIN tap_companies c ON c.id=u.company_id WHERE s.token_hash=? AND s.expires_at>? AND s.last_seen_at>?", (token_hash, now, now - SESSION_IDLE_SECONDS))
        if not user or not user["active"] or (user["company_id"] and not user["company_active"]):
            raise AuthenticationError("다시 로그인해 주세요.")
        if user["must_change_password"] and not allow_password_change:
            raise AuthorizationError("임시 비밀번호를 먼저 변경해 주세요.")
        if roles and user["role"] not in roles:
            raise AuthorizationError("이 작업에 대한 권한이 없습니다.")
        updated = self._execute(conn, "UPDATE tap_sessions SET last_seen_at=? WHERE token_hash=?", (now, token_hash))
        if updated.rowcount != 1:
            raise AuthenticationError("다시 로그인해 주세요.")
        return user

    @staticmethod
    def _public_user(user):
        return {key: (bool(user[key]) if key in {"active", "must_change_password"} else user[key]) for key in ("id", "login_id", "display_name", "role", "company_id", "active", "must_change_password", "company_name", "company_slug", "department", "job_title", "email", "phone") if key in user}

    def principal(self, token: str) -> dict:
        with self._transaction() as conn:
            return self._public_user(self._require(conn, token, allow_password_change=True))

    def logout(self, token: str) -> None:
        if not isinstance(token, str) or len(token) > 128:
            return
        with self._transaction() as conn:
            self._execute(conn, "DELETE FROM tap_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def change_password(self, token: str, current_password: str, new_password: str) -> str:
        _password_input(new_password)
        with self._transaction() as conn:
            user = self._require(conn, token, allow_password_change=True)
            current = self._one(conn, "SELECT * FROM tap_users WHERE id=?", (user["id"],), lock=True)
            if not verify_password(current_password, current["password_hash"]):
                raise AuthenticationError("현재 비밀번호가 맞지 않습니다.")
            if verify_password(new_password, current["password_hash"]):
                raise ValidationError("기존 비밀번호와 다른 비밀번호를 입력하세요.")
            self._execute(conn, "UPDATE tap_users SET password_hash=?,must_change_password=0 WHERE id=?", (hash_password(new_password), user["id"]))
            self._execute(conn, "DELETE FROM tap_sessions WHERE user_id=?", (user["id"],))
            self._audit(conn, user["id"], "change_password", user["id"])
            return self._new_session(conn, user["id"])

    def dashboard_summary(self, token: str) -> dict:
        """Aggregate operational counts without loading assessment payloads."""
        with self._transaction() as conn:
            actor = self._require(conn, token, {"kma", "company"})
            scoped = actor["role"] == "company"
            params = (actor["company_id"],) if scoped else ()
            companies = self._one(conn, "SELECT COUNT(*) AS total FROM tap_companies" + (" WHERE id=?" if scoped else ""), params)
            users = self._all(conn, "SELECT role,COUNT(*) AS total FROM tap_users WHERE role IN ('company','participant')" + (" AND company_id=?" if scoped else "") + " GROUP BY role", params)
            counts = {row["role"]: row["total"] for row in users}
            projects = self._all(conn, "SELECT p.id,p.company_id,c.name AS company_name,p.name,p.created_at,p.config_json,COALESCE(a.assigned,0) AS assigned,COALESCE(a.pre_completed,0) AS pre_completed,COALESCE(a.post_completed,0) AS post_completed FROM tap_projects p JOIN tap_companies c ON c.id=p.company_id LEFT JOIN (SELECT a.project_id,COUNT(*) AS assigned,SUM(CASE WHEN pre.completed=1 THEN 1 ELSE 0 END) AS pre_completed,SUM(CASE WHEN post.completed=1 THEN 1 ELSE 0 END) AS post_completed FROM tap_assignments a LEFT JOIN tap_assessments pre ON pre.assignment_id=a.id AND pre.phase='pre' LEFT JOIN tap_assessments post ON post.assignment_id=a.id AND post.phase='post' WHERE a.active=1 GROUP BY a.project_id) a ON a.project_id=p.id" + (" WHERE p.company_id=?" if scoped else "") + " ORDER BY p.created_at,p.id", params)
            for project in projects:
                project["config"] = json.loads(project.pop("config_json"))
            return {"companies_count": companies["total"], "company_users_count": counts.get("company", 0), "participant_users_count": counts.get("participant", 0), "projects": projects}

    def _question_bank(self, conn) -> list[dict]:
        overrides = {row["question_code"]: row for row in self._all(conn, "SELECT o.question_code,o.item_text,o.revision,o.updated_at,u.login_id AS updated_by FROM tap_question_overrides o JOIN tap_users u ON u.id=o.updated_by")}
        rows = []
        for original in load_questions():
            row = {**original, "revision": 0, "updated_at": None, "updated_by": None}
            override = overrides.get(row["question_code"])
            if override:
                row.update(revised_text=override["item_text"], revision=override["revision"], updated_at=override["updated_at"], updated_by=override["updated_by"])
            rows.append(row)
        return rows

    def list_question_bank(self, token: str) -> list[dict]:
        with self._transaction() as conn:
            self._require(conn, token, {"kma"})
            return self._question_bank(conn)

    def save_question_text(self, token: str, question_code: str, text: str, expected_revision: int) -> dict:
        with self._transaction() as conn:
            actor = self._require(conn, token, {"kma"})
            if type(expected_revision) is not int or expected_revision < 0:
                raise ValidationError("문항 수정 버전을 확인하세요.")
            if not isinstance(question_code, str) or question_code not in {row["question_code"] for row in load_questions()}:
                raise ValidationError("수정할 문항을 확인하세요.")
            item_text = _text(text, "문항 문구", 2000)
            current = self._one(conn, "SELECT revision FROM tap_question_overrides WHERE question_code=?", (question_code,), lock=True)
            revision = current["revision"] if current else 0
            if revision != expected_revision:
                raise ConflictError("다른 수정 내용이 저장되었습니다. 문항을 새로 불러온 뒤 다시 수정하세요.")
            now = self._clock()
            if current:
                self._execute(conn, "UPDATE tap_question_overrides SET item_text=?,revision=?,updated_at=?,updated_by=? WHERE question_code=? AND revision=?", (item_text, revision + 1, now, actor["id"], question_code, revision))
            else:
                self._execute(conn, "INSERT INTO tap_question_overrides(question_code,item_text,revision,updated_at,updated_by) VALUES (?,?,?,?,?)", (question_code, item_text, 1, now, actor["id"]))
            self._audit(conn, actor["id"], "save_question_text", question_code)
            return next(row for row in self._question_bank(conn) if row["question_code"] == question_code)

    def list_companies(self, token: str) -> list[dict]:
        with self._transaction() as conn:
            user = self._require(conn, token, {"kma", "company"})
            rows = self._all(conn, "SELECT id,name,slug,active FROM tap_companies" + (" WHERE id=?" if user["role"] == "company" else "") + " ORDER BY name", (user["company_id"],) if user["role"] == "company" else ())
            return [self._public_company(row) for row in rows]

    @staticmethod
    def _registration_number(value: Any) -> str:
        # Preserve leading zeroes and reject Unicode digits or punctuation.
        if not isinstance(value, str) or not _REGISTRATION_RE.fullmatch(value):
            raise ValidationError("사업자등록번호는 숫자 10자리로 입력해 주세요.")
        return value

    @staticmethod
    def _public_company(company: dict) -> dict:
        result = {key: company[key] for key in ("id", "name", "slug", "active")}
        result["active"] = bool(result["active"])
        # The legacy column and all UUID links remain unchanged.
        result["registration_number"] = result["slug"]
        return result

    def create_company(self, token: str, name: str, slug: str) -> dict:
        name, slug = _text(name, "회사명"), self._registration_number(slug)
        with self._transaction() as conn:
            actor = self._require(conn, token, {"kma"})
            company_id = str(uuid.uuid4())
            self._execute(conn, "INSERT INTO tap_companies(id,name,slug,created_at) VALUES (?,?,?,?)", (company_id, name, slug, self._clock()))
            self._audit(conn, actor["id"], "create_company", company_id)
            return self._public_company({"id": company_id, "name": name, "slug": slug, "active": True})

    def set_company_registration_number(self, token: str, company_id: str, registration_number: str) -> dict:
        """Correct company metadata without renaming accounts or UUIDs."""
        with self._transaction() as conn:
            actor = self._require(conn, token, {"kma"})
            number = self._registration_number(registration_number)
            company = self._one(conn, "SELECT id,name,slug,active FROM tap_companies WHERE id=?", (company_id,), lock=True)
            if not company:
                raise ValidationError("회사를 확인하세요.")
            self._execute(conn, "UPDATE tap_companies SET slug=? WHERE id=?", (number, company_id))
            self._audit(conn, actor["id"], "set_company_registration_number", company_id)
            company["slug"] = number
            return self._public_company(company)

    def list_users(self, token: str) -> list[dict]:
        with self._transaction() as conn:
            actor = self._require(conn, token, {"kma", "company"})
            rows = self._all(conn, "SELECT u.*,c.name AS company_name,c.slug AS company_slug FROM tap_users u LEFT JOIN tap_companies c ON c.id=u.company_id" + (" WHERE u.company_id=?" if actor["role"] == "company" else "") + " ORDER BY u.created_at,u.id", (actor["company_id"],) if actor["role"] == "company" else ())
            return [self._public_user(row) for row in rows]

    @staticmethod
    def _profile(profile: dict | None) -> dict[str, str]:
        if profile is None:
            profile = {}
        if not isinstance(profile, dict) or set(profile) - _PROFILE_LIMITS.keys():
            raise ValidationError("추가 계정 정보 형식을 확인해 주세요.")
        cleaned = {}
        for field, maximum in _PROFILE_LIMITS.items():
            value = profile.get(field, "")
            if (not isinstance(value, str) or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)
                    or len(value.strip()) > maximum):
                raise ValidationError(f"{_PROFILE_LABELS[field]}는 제어문자 없이 {maximum}자 이내로 입력해 주세요.")
            cleaned[field] = value.strip()
        if cleaned["email"] and not _EMAIL_RE.fullmatch(cleaned["email"]):
            raise ValidationError("이메일 형식을 확인해 주세요.")
        phone = cleaned["phone"]
        if phone and (not _PHONE_RE.fullmatch(phone) or not 5 <= sum(c in "0123456789" for c in phone) <= 20):
            raise ValidationError("연락처는 숫자와 +, 공백, 괄호, 하이픈, 점을 사용해 입력해 주세요.")
        return cleaned

    def create_user(self, token: str, login_id: str, display_name: str, role: str, company_id: str | None, temp_password: str, *, profile: dict | None = None) -> dict:
        login_id, display_name = _login_id(login_id), _text(display_name, "이름")
        _password_input(temp_password)
        profile = self._profile(profile)
        with self._transaction() as conn:
            actor = self._require(conn, token, {"kma", "company"})
            if role not in {"company", "participant"}:
                raise AuthorizationError("추가 KMA 관리자 생성은 운영 관리 절차를 이용하세요.")
            if actor["role"] == "company" and (role != "participant" or company_id != actor["company_id"]):
                raise AuthorizationError("담당 회사의 참여자만 생성할 수 있습니다.")
            company = self._one(conn, "SELECT * FROM tap_companies WHERE id=? AND active=1", (company_id,))
            if not company:
                raise ValidationError("회사를 확인하세요.")
            user_id = str(uuid.uuid4())
            self._execute(conn, "INSERT INTO tap_users(id,login_id,display_name,role,company_id,password_hash,created_at,department,job_title,email,phone) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (user_id, login_id, display_name, role, company_id, hash_password(temp_password), self._clock(), profile["department"], profile["job_title"], profile["email"], profile["phone"]))
            self._audit(conn, actor["id"], "create_user", user_id)
            return {"id": user_id, "login_id": login_id, "display_name": display_name, "role": role, "company_id": company_id, "active": True, "must_change_password": True, "company_name": company["name"], "company_slug": company["slug"], **profile}

    def _managed_user(self, conn, actor, user_id):
        target = self._one(conn, "SELECT * FROM tap_users WHERE id=?", (user_id,), lock=True)
        if not target or target["role"] == "kma" or (actor["role"] == "company" and (target["company_id"] != actor["company_id"] or target["role"] != "participant")):
            raise AuthorizationError("관리할 수 없는 계정입니다.")
        return target

    def reset_password(self, token: str, user_id: str, temp_password: str) -> None:
        _password_input(temp_password)
        with self._transaction() as conn:
            actor = self._require(conn, token, {"kma", "company"})
            target = self._managed_user(conn, actor, user_id)
            self._execute(conn, "UPDATE tap_users SET password_hash=?,must_change_password=1 WHERE id=?", (hash_password(temp_password), target["id"]))
            self._execute(conn, "DELETE FROM tap_sessions WHERE user_id=?", (target["id"],))
            self._execute(conn, "DELETE FROM tap_login_attempts WHERE login_hash=?", (hashlib.sha256(target["login_id"].encode()).hexdigest(),))
            self._audit(conn, actor["id"], "reset_password", target["id"])

    def set_user_active(self, token: str, user_id: str, active: bool) -> None:
        if type(active) is not bool:
            raise ValidationError("활성 상태를 확인하세요.")
        with self._transaction() as conn:
            actor = self._require(conn, token, {"kma", "company"})
            target = self._managed_user(conn, actor, user_id)
            self._execute(conn, "UPDATE tap_users SET active=? WHERE id=?", (int(active), target["id"]))
            self._execute(conn, "DELETE FROM tap_sessions WHERE user_id=?", (target["id"],))
            self._audit(conn, actor["id"], "activate_user" if active else "deactivate_user", target["id"])

    @staticmethod
    def _project_config(config: dict, question_overrides: dict | None = None) -> dict:
        if not isinstance(config, dict):
            raise ValidationError("프로젝트 설정을 확인하세요.")
        config = json.loads(_json(config))
        config.pop("company_id", None)
        factors = config.get("selected_factors")
        if not isinstance(factors, list) or not factors or any(not isinstance(v, str) for v in factors) or len(set(factors)) != len(factors):
            raise ValidationError("검사 역량을 선택하세요.")
        competencies = load_competencies()
        errors = selection_errors(factors, competencies)
        selected = {r["factor_code"]: r for r in competencies}
        level = config.get("target_level", "manager")
        if level not in {"staff", "manager", "executive"}:
            raise ValidationError("대상 직급을 확인하세요.")
        if errors or any(not selected.get(f, {}).get("active_for_scoring") or not applicable_to_level(selected[f], level) for f in factors):
            raise ValidationError("선택할 수 없는 검사 역량입니다. " + " ".join(errors))
        questions = [dict(row) for row in questions_for_factors(factors)]
        for question in questions:
            if question_overrides and question["question_code"] in question_overrides:
                question["revised_text"] = question_overrides[question["question_code"]]
        if not questions:
            raise ValidationError("검사 문항이 없습니다.")
        config["target_level"] = level
        config["question_snapshot"] = questions
        config["question_snapshot_codes"] = [q["question_code"] for q in questions]
        snapshot = sorted((str(q["question_code"]), str(q["revised_text"]), str(q.get("scoring_direction", "direct"))) for q in questions)
        config["question_snapshot_hash"] = hashlib.sha256("\n".join("|".join(parts) for parts in snapshot).encode()).hexdigest()
        config["full_question_snapshot_hash"] = hashlib.sha256(_json(questions).encode()).hexdigest()
        config["assessment_version"] = "TAP-1.0+" + config["question_snapshot_hash"][:12]
        config["allow_schedule_override"] = False
        dates = {}
        for key in ("pre_start_date", "pre_end_date", "training_date", "post_start_date", "post_end_date"):
            if config.get(key):
                try:
                    dates[key] = date.fromisoformat(config[key])
                    if dates[key].isoformat() != config[key]:
                        raise ValueError
                except (ValueError, TypeError) as exc:
                    raise ValidationError("검사 일정은 YYYY-MM-DD 형식이어야 합니다.") from exc
        if len(dates) != 5 or not (dates["pre_start_date"] <= dates["pre_end_date"] <= dates["training_date"] <= dates["post_start_date"] <= dates["post_end_date"]):
            raise ValidationError("일정은 사전 시작≤사전 종료≤교육일≤사후 시작≤사후 종료 순서여야 합니다.")
        _json(config)
        return config

    def create_project(self, token: str, name: str, config: dict) -> dict:
        name = _text(name, "프로젝트명")
        if not isinstance(config, dict):
            raise ValidationError("프로젝트 설정을 확인하세요.")
        with self._transaction() as conn:
            actor = self._require(conn, token, {"kma", "company"})
            company_id = actor["company_id"] if actor["role"] == "company" else config.get("company_id")
            if actor["role"] == "company" and config.get("company_id", company_id) != company_id:
                raise AuthorizationError("담당 회사에만 프로젝트를 만들 수 있습니다.")
            if not self._one(conn, "SELECT id FROM tap_companies WHERE id=? AND active=1", (company_id,)):
                raise ValidationError("회사를 선택하세요.")
            overrides = {row["question_code"]: row["item_text"] for row in self._all(conn, "SELECT question_code,item_text FROM tap_question_overrides")}
            config = self._project_config(config, overrides)
            project_id = str(uuid.uuid4())
            self._execute(conn, "INSERT INTO tap_projects(id,company_id,name,config_json,created_by,created_at) VALUES (?,?,?,?,?,?)", (project_id, company_id, name, _json(config), actor["id"], self._clock()))
            self._audit(conn, actor["id"], "create_project", project_id)
            return {"id": project_id, "company_id": company_id, "name": name, "config": config}

    def _project(self, conn, actor, project_id):
        project = self._one(conn, "SELECT * FROM tap_projects WHERE id=?", (project_id,))
        if not project or actor["role"] not in {"kma", "company"} or (actor["role"] == "company" and project["company_id"] != actor["company_id"]):
            raise AuthorizationError("접근할 수 없는 프로젝트입니다.")
        return project

    def list_projects(self, token: str) -> list[dict]:
        with self._transaction() as conn:
            actor = self._require(conn, token)
            if actor["role"] == "participant":
                rows = self._all(conn, "SELECT p.* FROM tap_projects p JOIN tap_assignments a ON a.project_id=p.id WHERE a.user_id=? AND a.active=1 AND p.company_id=? ORDER BY p.created_at,p.id", (actor["id"], actor["company_id"]))
            else:
                rows = self._all(conn, "SELECT * FROM tap_projects" + (" WHERE company_id=?" if actor["role"] == "company" else "") + " ORDER BY created_at,id", (actor["company_id"],) if actor["role"] == "company" else ())
            for row in rows:
                row["config"] = json.loads(row.pop("config_json"))
            return rows

    def assign_participant(self, token: str, project_id: str, user_id: str) -> dict:
        with self._transaction() as conn:
            actor = self._require(conn, token, {"kma", "company"})
            project = self._project(conn, actor, project_id)
            user = self._one(conn, "SELECT * FROM tap_users WHERE id=? AND role='participant' AND active=1", (user_id,))
            if not user or user["company_id"] != project["company_id"]:
                raise AuthorizationError("같은 회사의 활성 참여자만 배정할 수 있습니다.")
            self._execute(conn, "INSERT INTO tap_assignments(id,project_id,user_id,created_at) VALUES (?,?,?,?) ON CONFLICT (project_id,user_id) DO NOTHING", (str(uuid.uuid4()), project_id, user_id, self._clock()))
            result = self._assignments(conn, "a.project_id=? AND a.user_id=?", (project_id, user_id))[0]
            self._audit(conn, actor["id"], "assign_participant", result["id"])
            return result

    def _assignments(self, conn, where, params):
        rows = self._all(conn, "SELECT a.*,u.display_name AS user_name,u.login_id,p.name AS project_name,p.company_id,p.config_json,COALESCE(pre.completed,0) AS pre_completed,COALESCE(post.completed,0) AS post_completed FROM tap_assignments a JOIN tap_users u ON u.id=a.user_id JOIN tap_projects p ON p.id=a.project_id LEFT JOIN tap_assessments pre ON pre.assignment_id=a.id AND pre.phase='pre' LEFT JOIN tap_assessments post ON post.assignment_id=a.id AND post.phase='post' WHERE " + where + " ORDER BY a.created_at,a.id", params)
        for row in rows:
            row["config"] = json.loads(row.pop("config_json"))
            for key in ("active", "pre_completed", "post_completed"):
                row[key] = bool(row[key])
        return rows

    def list_assignments(self, token: str, project_id: str | None = None) -> list[dict]:
        with self._transaction() as conn:
            actor = self._require(conn, token)
            conditions, params = ["1=1"], []
            if actor["role"] == "participant":
                conditions.extend(["a.active=1", "a.user_id=?", "p.company_id=?"])
                params.extend([actor["id"], actor["company_id"]])
            elif actor["role"] == "company":
                conditions.append("p.company_id=?")
                params.append(actor["company_id"])
            if project_id:
                if actor["role"] != "participant":
                    self._project(conn, actor, project_id)
                conditions.append("a.project_id=?")
                params.append(project_id)
            return self._assignments(conn, " AND ".join(conditions), params)

    def set_assignment_active(self, token: str, assignment_id: str, active: bool) -> None:
        """Remove/reinstate a project assignment without disabling its account."""
        if type(active) is not bool:
            raise ValidationError("배정 상태를 확인하세요.")
        with self._transaction() as conn:
            actor = self._require(conn, token, {"kma", "company"})
            assignment = self._one(conn, "SELECT * FROM tap_assignments WHERE id=?", (assignment_id,), lock=True)
            if not assignment:
                raise AuthorizationError("관리할 수 없는 배정입니다.")
            self._project(conn, actor, assignment["project_id"])
            self._execute(conn, "UPDATE tap_assignments SET active=? WHERE id=?", (int(active), assignment_id))
            self._audit(conn, actor["id"], "activate_assignment" if active else "deactivate_assignment", assignment_id)

    def _owned_assignment(self, conn, actor, assignment_id, *, write=False):
        assignment = self._one(conn, "SELECT * FROM tap_assignments WHERE id=?", (assignment_id,), lock=write)
        if not assignment or not assignment["active"]:
            raise AuthorizationError("배정된 검사를 확인하세요.")
        project = self._one(conn, "SELECT * FROM tap_projects WHERE id=?", (assignment["project_id"],))
        if actor["role"] != "participant" or assignment["user_id"] != actor["id"] or project["company_id"] != actor["company_id"]:
            raise AuthorizationError("본인에게 배정된 검사만 열 수 있습니다.")
        return assignment, json.loads(project["config_json"])

    @staticmethod
    def _assessment(row):
        if row is None:
            return None
        row["payload"] = json.loads(row.pop("payload_json"))
        row["completed"] = bool(row["completed"])
        return row

    @staticmethod
    def _phase(phase):
        if phase not in {"pre", "post"}:
            raise ValidationError("검사 단계를 확인하세요.")
        return phase

    def load_assessment(self, token: str, assignment_id: str, phase: str) -> dict | None:
        phase = self._phase(phase)
        with self._transaction() as conn:
            actor = self._require(conn, token, {"participant"})
            self._owned_assignment(conn, actor, assignment_id)
            return self._assessment(self._one(conn, "SELECT * FROM tap_assessments WHERE assignment_id=? AND phase=?", (assignment_id, phase)))

    @staticmethod
    def _payload(config, phase, payload, completed):
        allowed = {"responses", "current_question", "started_at", "duration_seconds", "post_transfer_responses"}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise ValidationError("검사 저장 형식을 확인하세요.")
        payload = json.loads(_json(payload))
        responses = payload.get("responses")
        codes = set(config["question_snapshot_codes"])
        if not isinstance(responses, dict) or set(responses) - codes or any(type(v) is not int or not 0 <= v <= 5 for v in responses.values()):
            raise ValidationError("검사 문항과 응답 범위를 확인하세요.")
        if completed and set(responses) != codes:
            raise ValidationError("모든 검사 문항에 응답해야 제출할 수 있습니다.")
        if "current_question" in payload and (type(payload["current_question"]) is not int or not 0 <= payload["current_question"] <= len(codes)):
            raise ValidationError("검사 진행 위치를 확인하세요.")
        for field in ("started_at", "duration_seconds"):
            if field in payload and payload[field] is not None and (type(payload[field]) not in (int, float) or not math.isfinite(payload[field]) or payload[field] < 0):
                raise ValidationError("검사 시간 형식을 확인하세요.")
        transfer = payload.get("post_transfer_responses", {})
        if not isinstance(transfer, dict) or set(transfer) - (_TRANSFER_KEYS | {"barriers", "applied_content"}):
            raise ValidationError("현업 적용 응답을 확인하세요.")
        if phase == "pre" and transfer:
            raise ValidationError("사전검사에는 현업 적용 응답을 저장할 수 없습니다.")
        if phase == "post":
            if any(type(transfer[k]) is not int or not 1 <= transfer[k] <= 5 for k in _TRANSFER_KEYS & transfer.keys()) or (completed and not _TRANSFER_KEYS <= transfer.keys()):
                raise ValidationError("현업 적용 환경 네 문항에 응답해 주세요.")
            if "barriers" in transfer:
                barriers = transfer["barriers"]
                if (not isinstance(barriers, list) or any(not isinstance(v, str) or v not in _BARRIERS for v in barriers)
                        or len(set(barriers)) != len(barriers)
                        or ("특별한 방해요인 없음" in barriers and len(barriers) > 1)):
                    raise ValidationError("현업 적용 장애요인을 확인하세요.")
            if "applied_content" in transfer and (not isinstance(transfer["applied_content"], str) or len(transfer["applied_content"]) > 2000):
                raise ValidationError("현업 적용 사례는 2,000자 이내입니다.")
        return payload

    def save_assessment(self, token: str, assignment_id: str, phase: str, payload: dict, completed: bool) -> dict:
        phase = self._phase(phase)
        if type(completed) is not bool:
            raise ValidationError("제출 상태를 확인하세요.")
        with self._transaction() as conn:
            actor = self._require(conn, token, {"participant"})
            _, config = self._owned_assignment(conn, actor, assignment_id, write=True)
            payload = self._payload(config, phase, payload, completed)
            encoded = _json(payload)
            old = self._one(conn, "SELECT * FROM tap_assessments WHERE assignment_id=? AND phase=?", (assignment_id, phase))
            if old and old["completed"]:
                if completed and old["payload_json"] == encoded:
                    return self._assessment(old)
                raise ConflictError("제출된 검사는 변경할 수 없습니다.")
            snapshot = config.get("question_snapshot")
            if not isinstance(snapshot, list) or not snapshot or hashlib.sha256(_json(snapshot).encode()).hexdigest() != config["full_question_snapshot_hash"]:
                raise ConflictError("검사 문항 버전이 변경되었습니다. 교육담당자에게 문의하세요.")
            today = datetime.fromtimestamp(self._clock(), KST).date()
            if config.get(f"{phase}_start_date") and not date.fromisoformat(config[f"{phase}_start_date"]) <= today <= date.fromisoformat(config[f"{phase}_end_date"]):
                raise AuthorizationError("현재는 해당 검사 기간이 아닙니다.")
            if phase == "post":
                pre = self._one(conn, "SELECT completed FROM tap_assessments WHERE assignment_id=? AND phase='pre'", (assignment_id,))
                if not pre or not pre["completed"]:
                    raise AuthorizationError("사전검사를 먼저 완료해 주세요.")
            now = self._clock()
            self._execute(conn, "INSERT INTO tap_assessments(assignment_id,phase,payload_json,completed,completed_at,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT (assignment_id,phase) DO UPDATE SET payload_json=excluded.payload_json,completed=excluded.completed,completed_at=excluded.completed_at,updated_at=excluded.updated_at", (assignment_id, phase, encoded, int(completed), now if completed else None, now))
            if completed:
                self._audit(conn, actor["id"], "submit_" + phase, assignment_id)
            return {"assignment_id": assignment_id, "phase": phase, "payload": payload, "completed": completed, "completed_at": now if completed else None, "updated_at": now}

    def project_results(self, token: str, project_id: str) -> list[dict]:
        """Authorized report input; presentation must preserve the N>=5 rule."""
        with self._transaction() as conn:
            actor = self._require(conn, token, {"kma", "company"})
            self._project(conn, actor, project_id)
            rows = self._assignments(conn, "a.project_id=?", (project_id,))
            completed = self._all(conn, "SELECT s.assignment_id,s.phase,s.payload_json FROM tap_assessments s JOIN tap_assignments a ON a.id=s.assignment_id WHERE a.project_id=? AND s.completed=1", (project_id,))
            payloads = {(row["assignment_id"], row["phase"]): json.loads(row["payload_json"]) for row in completed}
            for row in rows:
                for phase in ("pre", "post"):
                    row[phase + "_payload"] = payloads.get((row["id"], phase))
            return rows
