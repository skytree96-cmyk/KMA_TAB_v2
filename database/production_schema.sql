-- TAP production persistence reference schema (PostgreSQL 15+)
-- This database must be server-only. Do not expose it through an anonymous REST key.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS instrument_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version text UNIQUE NOT NULL,
  framework_json jsonb NOT NULL,
  scoring_json jsonb NOT NULL,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  instrument_version_id uuid NOT NULL REFERENCES instrument_versions(id),
  title text NOT NULL,
  training_title text NOT NULL,
  training_starts_at timestamptz,
  training_ends_at timestamptz,
  evaluation_design text NOT NULL DEFAULT 'single_group_pre_post'
    CHECK (evaluation_design IN ('single_group_pre_post','comparison_group_pre_post')),
  target_level text NOT NULL CHECK (target_level IN ('staff','manager','executive')),
  selected_factor_codes text[] NOT NULL,
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','closed','archived')),
  starts_at timestamptz,
  ends_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS assessment_windows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  phase text NOT NULL CHECK (phase IN ('pre','post','followup')),
  opens_at timestamptz NOT NULL,
  closes_at timestamptz NOT NULL,
  recall_window_days smallint NOT NULL DEFAULT 56 CHECK (recall_window_days BETWEEN 1 AND 365),
  instrument_version_id uuid NOT NULL REFERENCES instrument_versions(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (closes_at > opens_at),
  UNIQUE (project_id, phase)
);

CREATE TABLE IF NOT EXISTS participants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  project_id uuid NOT NULL REFERENCES projects(id),
  external_subject_id text NOT NULL,
  pairing_key_hash text NOT NULL,
  evaluation_group text NOT NULL DEFAULT 'training'
    CHECK (evaluation_group IN ('training','comparison','waitlist')),
  access_token_hash text UNIQUE NOT NULL,
  token_expires_at timestamptz NOT NULL,
  token_revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, external_subject_id),
  UNIQUE (project_id, pairing_key_hash)
);

CREATE TABLE IF NOT EXISTS consents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  participant_id uuid NOT NULL REFERENCES participants(id),
  consent_version text NOT NULL,
  scope text NOT NULL CHECK (scope IN ('required_processing','share_individual_with_hr')),
  granted_at timestamptz,
  withdrawn_at timestamptz,
  event_ip inet,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS assessment_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  participant_id uuid NOT NULL REFERENCES participants(id),
  project_id uuid NOT NULL REFERENCES projects(id),
  instrument_version_id uuid NOT NULL REFERENCES instrument_versions(id),
  assessment_window_id uuid REFERENCES assessment_windows(id),
  session_type text NOT NULL CHECK (session_type IN ('pre','post','followup')),
  question_snapshot jsonb NOT NULL,
  status text NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','completed','expired','void')),
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  duration_seconds integer CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
  quality_flags text[] NOT NULL DEFAULT '{}',
  UNIQUE (participant_id, project_id, session_type)
);

CREATE TABLE IF NOT EXISTS responses (
  session_id uuid NOT NULL REFERENCES assessment_sessions(id) ON DELETE CASCADE,
  question_code text NOT NULL,
  response_status text NOT NULL CHECK (response_status IN ('answered','no_opportunity')),
  response_value smallint CHECK (
    (response_status = 'answered' AND response_value BETWEEN 1 AND 5)
    OR (response_status = 'no_opportunity' AND response_value IS NULL)
  ),
  answered_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, question_code)
);

CREATE TABLE IF NOT EXISTS transfer_context_responses (
  session_id uuid NOT NULL REFERENCES assessment_sessions(id) ON DELETE CASCADE,
  item_code text NOT NULL,
  dimension text NOT NULL CHECK (
    dimension IN ('application_opportunity','manager_support','tools','authority','process','other_barrier')
  ),
  response_value smallint CHECK (response_value IS NULL OR response_value BETWEEN 1 AND 5),
  response_text text,
  answered_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, item_code)
);

CREATE TABLE IF NOT EXISTS competency_scores (
  session_id uuid NOT NULL REFERENCES assessment_sessions(id) ON DELETE CASCADE,
  factor_code text NOT NULL,
  score_mean numeric(4,2) CHECK (score_mean IS NULL OR score_mean BETWEEN 1 AND 5),
  score_index numeric(5,1) CHECK (score_index IS NULL OR score_index BETWEEN 0 AND 100),
  valid_item_n smallint NOT NULL,
  assigned_item_n smallint NOT NULL,
  score_status text NOT NULL CHECK (score_status IN ('scored','insufficient_data')),
  calculated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, factor_code)
);

CREATE TABLE IF NOT EXISTS course_catalog (
  course_id text PRIMARY KEY,
  title text NOT NULL,
  delivery text NOT NULL CHECK (delivery IN ('online','offline','blended')),
  target_level text NOT NULL DEFAULT 'all',
  url text,
  active boolean NOT NULL DEFAULT true,
  catalog_version text NOT NULL
);

CREATE TABLE IF NOT EXISTS training_participation (
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  participant_id uuid NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
  course_id text REFERENCES course_catalog(course_id),
  participation_status text NOT NULL DEFAULT 'planned'
    CHECK (participation_status IN ('planned','completed','partial','absent','unknown')),
  attended_minutes integer CHECK (attended_minutes IS NULL OR attended_minutes >= 0),
  completed_at timestamptz,
  PRIMARY KEY (project_id, participant_id)
);

CREATE TABLE IF NOT EXISTS competency_course_map (
  factor_code text NOT NULL,
  course_id text NOT NULL REFERENCES course_catalog(course_id),
  content_fit numeric(3,2) NOT NULL CHECK (content_fit BETWEEN 0 AND 1),
  rationale text NOT NULL,
  mapping_version text NOT NULL,
  PRIMARY KEY (factor_code, course_id, mapping_version)
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id bigserial PRIMARY KEY,
  organization_id uuid,
  actor_id text NOT NULL,
  action text NOT NULL,
  object_type text NOT NULL,
  object_id text,
  detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projects_org ON projects(organization_id);
CREATE INDEX IF NOT EXISTS idx_windows_project ON assessment_windows(project_id, phase);
CREATE INDEX IF NOT EXISTS idx_participants_project ON participants(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON assessment_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_responses_session ON responses(session_id);
CREATE INDEX IF NOT EXISTS idx_transfer_session ON transfer_context_responses(session_id);

CREATE OR REPLACE VIEW paired_competency_changes AS
SELECT
  pre_session.project_id,
  pre_session.participant_id,
  pre_score.factor_code,
  pre_score.score_mean AS pre_score_mean,
  post_score.score_mean AS post_score_mean,
  post_score.score_mean - pre_score.score_mean AS observed_change,
  pre_score.valid_item_n AS pre_valid_item_n,
  post_score.valid_item_n AS post_valid_item_n
FROM assessment_sessions AS pre_session
JOIN competency_scores AS pre_score
  ON pre_score.session_id = pre_session.id
JOIN assessment_sessions AS post_session
  ON post_session.project_id = pre_session.project_id
 AND post_session.participant_id = pre_session.participant_id
 AND post_session.session_type = 'post'
JOIN competency_scores AS post_score
  ON post_score.session_id = post_session.id
 AND post_score.factor_code = pre_score.factor_code
WHERE pre_session.session_type = 'pre'
  AND pre_session.status = 'completed'
  AND post_session.status = 'completed'
  AND pre_score.score_status = 'scored'
  AND post_score.score_status = 'scored'
  AND pre_session.instrument_version_id = post_session.instrument_version_id;

-- Deny anonymous access by default if this schema is used in Supabase/PostgREST.
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE instrument_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessment_windows ENABLE ROW LEVEL SECURITY;
ALTER TABLE participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessment_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE transfer_context_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE competency_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_catalog ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_participation ENABLE ROW LEVEL SECURITY;
ALTER TABLE competency_course_map ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- No public policies are intentionally created. Use a server-side DB role and enforce org ownership.
