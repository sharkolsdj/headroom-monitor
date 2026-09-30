-- 006: audit log, trigger functions, and triggers on every hm table

-- ── Audit log table ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit.log (
    id         BIGSERIAL   PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    db_user    TEXT        NOT NULL,
    table_name TEXT        NOT NULL,
    op         TEXT        NOT NULL,   -- INSERT | UPDATE | DELETE | BULK_LOAD
    row_pk     JSONB,
    old_row    JSONB,
    new_row    JSONB
);

CREATE INDEX IF NOT EXISTS audit_log_table_ts ON audit.log (table_name, ts DESC);

-- ── Row-level trigger function ────────────────────────────────────────────────
-- TG_ARGV: PK column names for this table (zero or more).
-- In bulk-load mode (SET hm.bulk_load = 'on') the row trigger is silent;
-- the statement trigger (below) writes one summary row instead.
CREATE OR REPLACE FUNCTION audit.log_row_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_bulk TEXT;
    v_pk   JSONB := '{}'::jsonb;
    v_rec  JSONB;
    i      INT;
BEGIN
    v_bulk := coalesce(current_setting('hm.bulk_load', true), 'off');
    IF v_bulk = 'on' THEN
        RETURN NULL;
    END IF;

    v_rec := CASE TG_OP WHEN 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;

    -- Build row_pk from trigger args (column names passed at CREATE TRIGGER time)
    FOR i IN 0 .. TG_NARGS - 1 LOOP
        v_pk := v_pk || jsonb_build_object(TG_ARGV[i], v_rec -> TG_ARGV[i]);
    END LOOP;

    INSERT INTO audit.log (ts, db_user, table_name, op, row_pk, old_row, new_row)
    VALUES (
        now(),
        session_user,
        TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
        TG_OP,
        v_pk,
        CASE TG_OP WHEN 'INSERT' THEN NULL ELSE to_jsonb(OLD) END,
        CASE TG_OP WHEN 'DELETE' THEN NULL ELSE to_jsonb(NEW) END
    );
    RETURN NULL;
END;
$$;

-- ── Statement-level trigger function (bulk-load summary) ─────────────────────
-- Generator sets:  SET hm.bulk_load = 'on'; SET hm.bulk_row_count = '<n>';
-- before each bulk INSERT, then 'off' / '0' afterwards.
CREATE OR REPLACE FUNCTION audit.log_bulk_statement()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_bulk  TEXT;
    v_count TEXT;
BEGIN
    v_bulk := coalesce(current_setting('hm.bulk_load', true), 'off');
    IF v_bulk != 'on' THEN
        RETURN NULL;
    END IF;

    v_count := coalesce(current_setting('hm.bulk_row_count', true), '0');

    INSERT INTO audit.log (ts, db_user, table_name, op, row_pk, old_row, new_row)
    VALUES (
        now(),
        session_user,
        TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
        'BULK_LOAD',
        NULL,
        NULL,
        jsonb_build_object('row_count', v_count::int)
    );
    RETURN NULL;
END;
$$;

-- ── parameters: block all UPDATEs (append-only versioned table) ───────────────
CREATE OR REPLACE FUNCTION hm.reject_parameter_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'hm.parameters is append-only. INSERT a new version (key, value, version+1) instead of UPDATE.';
END;
$$;

DROP TRIGGER IF EXISTS parameters_no_update ON hm.parameters;
CREATE TRIGGER parameters_no_update
BEFORE UPDATE ON hm.parameters
FOR EACH ROW EXECUTE FUNCTION hm.reject_parameter_update();

-- ── Attach audit triggers to every hm business table ─────────────────────────
-- Excludes schema_migrations (meta-table) and parameters (has its own guard).
-- Row trigger: captures INSERT / UPDATE / DELETE with old+new values.
-- Statement trigger: captures BULK_LOAD summary when hm.bulk_load = 'on'.
DO $$
DECLARE
    r    record;
    trig text;
BEGIN
    FOR r IN
        SELECT tablename
        FROM   pg_tables
        WHERE  schemaname = 'hm'
          AND  tablename NOT IN ('schema_migrations')
    LOOP
        -- Row-level trigger
        trig := 'audit_row_' || r.tablename;
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON hm.%I;
             CREATE TRIGGER %I
             AFTER INSERT OR UPDATE OR DELETE ON hm.%I
             FOR EACH ROW EXECUTE FUNCTION audit.log_row_change()',
            trig, r.tablename, trig, r.tablename
        );

        -- Statement-level trigger (bulk INSERT summary only)
        trig := 'audit_stmt_' || r.tablename;
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON hm.%I;
             CREATE TRIGGER %I
             AFTER INSERT ON hm.%I
             FOR EACH STATEMENT EXECUTE FUNCTION audit.log_bulk_statement()',
            trig, r.tablename, trig, r.tablename
        );
    END LOOP;
END;
$$;
