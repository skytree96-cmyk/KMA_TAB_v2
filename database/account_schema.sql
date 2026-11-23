-- Operational account data. Execute transactionally through AccountStore.initialize.
-- Names are separate from the legacy demonstration/reference schema.
CREATE TABLE IF NOT EXISTS tap_companies (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
 active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)), created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS tap_users (
 id TEXT PRIMARY KEY, login_id TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
 role TEXT NOT NULL CHECK (role IN ('kma','company','participant')),
 company_id TEXT REFERENCES tap_companies(id), password_hash TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
 must_change_password INTEGER NOT NULL DEFAULT 1 CHECK (must_change_password IN (0,1)),
 department TEXT NOT NULL DEFAULT '', job_title TEXT NOT NULL DEFAULT '',
 email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
 created_at DOUBLE PRECISION NOT NULL,
 CHECK ((role = 'kma' AND company_id IS NULL) OR (role <> 'kma' AND company_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS tap_sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES tap_users(id) ON DELETE CASCADE,
 created_at DOUBLE PRECISION NOT NULL, expires_at DOUBLE PRECISION NOT NULL,
 last_seen_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS tap_login_attempts (
 login_hash TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0,
 window_start DOUBLE PRECISION NOT NULL, locked_until DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tap_projects (
 id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES tap_companies(id),
 name TEXT NOT NULL, config_json TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES tap_users(id),
 created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS tap_assignments (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES tap_projects(id),
 user_id TEXT NOT NULL REFERENCES tap_users(id),
 active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)), created_at DOUBLE PRECISION NOT NULL,
 report_department TEXT, report_job_title TEXT,
 UNIQUE (project_id,user_id)
);
CREATE TABLE IF NOT EXISTS tap_assessments (
 assignment_id TEXT NOT NULL REFERENCES tap_assignments(id),
 phase TEXT NOT NULL CHECK (phase IN ('pre','post')), payload_json TEXT NOT NULL,
 completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0,1)),
 completed_at DOUBLE PRECISION, updated_at DOUBLE PRECISION NOT NULL,
 PRIMARY KEY (assignment_id,phase)
);
CREATE TABLE IF NOT EXISTS tap_audit_events (
 id TEXT PRIMARY KEY, actor_id TEXT REFERENCES tap_users(id),
 event TEXT NOT NULL, target_id TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL,
 detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS tap_sessions_user_idx ON tap_sessions(user_id);
CREATE INDEX IF NOT EXISTS tap_users_company_idx ON tap_users(company_id);
CREATE INDEX IF NOT EXISTS tap_projects_company_idx ON tap_projects(company_id);
CREATE INDEX IF NOT EXISTS tap_assignments_user_idx ON tap_assignments(user_id);
CREATE INDEX IF NOT EXISTS tap_audit_events_created_idx ON tap_audit_events(created_at);

CREATE TABLE IF NOT EXISTS tap_question_overrides (
 question_code TEXT PRIMARY KEY, item_text TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK (revision >= 1), updated_at DOUBLE PRECISION NOT NULL,
 updated_by TEXT NOT NULL REFERENCES tap_users(id)
);

-- Claude API ledger. Each call reserves its worst-case cost first and is settled
-- with the actual cost, so the monthly allocation holds even under concurrency.
CREATE TABLE IF NOT EXISTS tap_ai_usage (
 id TEXT PRIMARY KEY, month TEXT NOT NULL, feature TEXT NOT NULL, project_id TEXT,
 status TEXT NOT NULL CHECK (status IN ('reserved','settled')),
 amount_micros BIGINT NOT NULL CHECK (amount_micros >= 0),
 input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
 outcome TEXT NOT NULL DEFAULT '', created_at DOUBLE PRECISION NOT NULL, settled_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS tap_ai_usage_month_idx ON tap_ai_usage(month, feature);
CREATE TABLE IF NOT EXISTS tap_ai_results (
 feature TEXT NOT NULL, cache_key TEXT NOT NULL, result_text TEXT NOT NULL,
 created_at DOUBLE PRECISION NOT NULL, PRIMARY KEY (feature, cache_key)
);
CREATE TABLE IF NOT EXISTS tap_ai_state (
 state_key TEXT PRIMARY KEY, state_value TEXT NOT NULL, updated_at DOUBLE PRECISION NOT NULL
);
