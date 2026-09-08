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
 event TEXT NOT NULL, target_id TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS tap_sessions_user_idx ON tap_sessions(user_id);
CREATE INDEX IF NOT EXISTS tap_users_company_idx ON tap_users(company_id);
CREATE INDEX IF NOT EXISTS tap_projects_company_idx ON tap_projects(company_id);
CREATE INDEX IF NOT EXISTS tap_assignments_user_idx ON tap_assignments(user_id);
