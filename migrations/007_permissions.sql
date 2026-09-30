-- 007: role permissions
-- Re-runnable: GRANT is idempotent in Postgres.

-- ── hm_reader: read-only on hm ───────────────────────────────────────────────
GRANT USAGE ON SCHEMA hm TO hm_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA hm TO hm_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA hm GRANT SELECT ON TABLES TO hm_reader;

-- ── hm_analyst: reader + write forecast + propose parameters ─────────────────
GRANT USAGE ON SCHEMA hm TO hm_analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA hm TO hm_analyst;
ALTER DEFAULT PRIVILEGES IN SCHEMA hm GRANT SELECT ON TABLES TO hm_analyst;
GRANT INSERT ON hm.forecast_runs,  hm.forecast_lines TO hm_analyst;
GRANT INSERT ON hm.parameters TO hm_analyst;
GRANT USAGE ON SEQUENCE hm.forecast_runs_run_id_seq  TO hm_analyst;
GRANT USAGE ON SEQUENCE hm.forecast_lines_id_seq     TO hm_analyst;

-- ── hm_approver: analyst + approvals + read audit ────────────────────────────
GRANT USAGE ON SCHEMA hm TO hm_approver;
GRANT SELECT ON ALL TABLES IN SCHEMA hm TO hm_approver;
ALTER DEFAULT PRIVILEGES IN SCHEMA hm GRANT SELECT ON TABLES TO hm_approver;
GRANT INSERT ON hm.forecast_runs, hm.forecast_lines TO hm_approver;
GRANT INSERT ON hm.parameters TO hm_approver;
GRANT INSERT ON hm.approvals  TO hm_approver;
GRANT USAGE ON SEQUENCE hm.forecast_runs_run_id_seq  TO hm_approver;
GRANT USAGE ON SEQUENCE hm.forecast_lines_id_seq     TO hm_approver;
GRANT USAGE ON SEQUENCE hm.approvals_approval_id_seq TO hm_approver;
GRANT USAGE  ON SCHEMA audit TO hm_approver;
GRANT SELECT ON ALL TABLES IN SCHEMA audit TO hm_approver;
ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT SELECT ON TABLES TO hm_approver;

-- ── hm_evaluator: read hm + eval ─────────────────────────────────────────────
GRANT USAGE ON SCHEMA hm    TO hm_evaluator;
GRANT USAGE ON SCHEMA eval  TO hm_evaluator;
GRANT SELECT ON ALL TABLES IN SCHEMA hm   TO hm_evaluator;
GRANT SELECT ON ALL TABLES IN SCHEMA eval TO hm_evaluator;
ALTER DEFAULT PRIVILEGES IN SCHEMA hm   GRANT SELECT ON TABLES TO hm_evaluator;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval GRANT SELECT ON TABLES TO hm_evaluator;

-- ── hm_admin: full access to everything ──────────────────────────────────────
GRANT ALL ON SCHEMA hm, vault, eval, audit TO hm_admin;
GRANT ALL ON ALL TABLES    IN SCHEMA hm    TO hm_admin;
GRANT ALL ON ALL TABLES    IN SCHEMA vault TO hm_admin;
GRANT ALL ON ALL TABLES    IN SCHEMA eval  TO hm_admin;
GRANT ALL ON ALL TABLES    IN SCHEMA audit TO hm_admin;
GRANT ALL ON ALL SEQUENCES IN SCHEMA hm    TO hm_admin;
GRANT ALL ON ALL SEQUENCES IN SCHEMA audit TO hm_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA hm    GRANT ALL ON TABLES    TO hm_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA vault GRANT ALL ON TABLES    TO hm_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval  GRANT ALL ON TABLES    TO hm_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT ALL ON TABLES    TO hm_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA hm    GRANT ALL ON SEQUENCES TO hm_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT ALL ON SEQUENCES TO hm_admin;
