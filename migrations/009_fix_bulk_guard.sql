-- 009: fix BULK_LOAD guard in audit triggers
--   In a SECURITY DEFINER function current_user = function owner ('headroom'),
--   never the caller. Use session_user to check whether hm_admin is connected.

-- ── 1a. Row-level audit trigger — session_user guard ─────────────────────────
CREATE OR REPLACE FUNCTION audit.log_row_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_bulk TEXT;
    v_pk   JSONB := '{}'::jsonb;
    v_rec  JSONB;
    i      INT;
BEGIN
    -- BULK_LOAD bypass is a privilege for hm_admin only; checked via session_user
    -- because current_user in a SECURITY DEFINER function is always the owner.
    IF session_user = 'hm_admin' THEN
        v_bulk := coalesce(current_setting('hm.bulk_load', true), 'off');
        IF v_bulk = 'on' THEN
            RETURN NULL;
        END IF;
    END IF;

    v_rec := CASE TG_OP WHEN 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;

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

-- ── 1b. Statement-level bulk-load summary trigger — session_user guard ────────
CREATE OR REPLACE FUNCTION audit.log_bulk_statement()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_bulk  TEXT;
    v_count TEXT;
BEGIN
    -- BULK_LOAD summary only honoured for hm_admin (session_user, not current_user)
    IF session_user != 'hm_admin' THEN
        RETURN NULL;
    END IF;

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

-- ── 2. Ensure all roles have CONNECT on the current database ──────────────────
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['hm_reader','hm_analyst','hm_approver','hm_evaluator','hm_admin']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I',
                           current_database(), r);
        END IF;
    END LOOP;
END;
$$;
