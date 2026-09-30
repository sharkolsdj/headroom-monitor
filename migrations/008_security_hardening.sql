-- 008: security hardening
--   1. Audit triggers: BULK_LOAD bypass restricted to hm_admin; fixed search_path
--   2. hm.parameters: block DELETE as well as UPDATE
--   3. audit.log: revoke INSERT/UPDATE/DELETE from application roles
--   4. vault.identity_map: composite PK (dataset_id, code)

-- ── 1a. Row-level audit trigger — hardened ────────────────────────────────────
-- SECURITY DEFINER so any role's writes are captured even without direct INSERT
-- on audit.log. SET search_path prevents search-path-injection attacks.
-- BULK_LOAD bypass is only honoured when current_user = 'hm_admin'.
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
    -- BULK_LOAD bypass is a privilege for hm_admin only; all other roles are
    -- audited row-by-row regardless of the GUC.
    IF current_user = 'hm_admin' THEN
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

-- ── 1b. Statement-level bulk-load summary trigger — hardened ──────────────────
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
    -- BULK_LOAD summary only honoured for hm_admin
    IF current_user != 'hm_admin' THEN
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

-- ── 2. Block DELETE on hm.parameters ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION hm.reject_parameter_delete()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'hm.parameters is append-only. DELETE is not permitted.';
END;
$$;

DROP TRIGGER IF EXISTS parameters_no_delete ON hm.parameters;
CREATE TRIGGER parameters_no_delete
BEFORE DELETE ON hm.parameters
FOR EACH ROW EXECUTE FUNCTION hm.reject_parameter_delete();

-- ── 3. Lock audit.log against direct writes from application roles ────────────
-- The SECURITY DEFINER trigger (owned by the DB owner) still writes to audit.log.
-- Application roles must never bypass the trigger by writing directly.
REVOKE INSERT, UPDATE, DELETE ON audit.log
    FROM hm_reader, hm_analyst, hm_approver, hm_evaluator;

-- ── 4. vault.identity_map — composite PK (dataset_id, code) ──────────────────
ALTER TABLE vault.identity_map DROP CONSTRAINT IF EXISTS identity_map_pkey;

ALTER TABLE vault.identity_map ADD COLUMN IF NOT EXISTS dataset_id TEXT;

-- Back-fill any existing rows (table should be empty; guards against re-runs)
UPDATE vault.identity_map SET dataset_id = 'UNSET' WHERE dataset_id IS NULL;

ALTER TABLE vault.identity_map ALTER COLUMN dataset_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE  conname = 'identity_map_pkey'
          AND  conrelid = 'vault.identity_map'::regclass
    ) THEN
        ALTER TABLE vault.identity_map ADD PRIMARY KEY (dataset_id, code);
    END IF;
END $$;
