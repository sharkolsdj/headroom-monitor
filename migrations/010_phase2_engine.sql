-- 010: Phase 2 — assumption_overrides + forecast table updates

-- ── CFO overrides (insert-only, audited) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS hm.assumption_overrides (
    override_id  BIGSERIAL   PRIMARY KEY,
    dataset_id   TEXT        NOT NULL REFERENCES hm.datasets(dataset_id) ON DELETE CASCADE,
    target_type  TEXT        NOT NULL
        CHECK (target_type IN ('invoice', 'customer', 'planned_payment', 'parameter')),
    target_id    TEXT        NOT NULL,
    field        TEXT        NOT NULL
        CHECK (field IN ('expected_date', 'amount', 'delay_days', 'value')),
    new_value    TEXT        NOT NULL,
    reason       TEXT,
    created_by   TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active       BOOLEAN     NOT NULL DEFAULT TRUE,
    supersedes   BIGINT      REFERENCES hm.assumption_overrides(override_id)
);

-- Insert-only enforcement (same pattern as hm.parameters)
CREATE OR REPLACE FUNCTION hm.assumption_overrides_immutable()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = hm
AS $$
BEGIN
    RAISE EXCEPTION
        'assumption_overrides is append-only; insert a new row with supersedes=% to cancel.',
        OLD.override_id;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'assumption_overrides_no_update'
          AND tgrelid = 'hm.assumption_overrides'::regclass
    ) THEN
        CREATE TRIGGER assumption_overrides_no_update
        BEFORE UPDATE ON hm.assumption_overrides
        FOR EACH ROW EXECUTE FUNCTION hm.assumption_overrides_immutable();
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'assumption_overrides_no_delete'
          AND tgrelid = 'hm.assumption_overrides'::regclass
    ) THEN
        CREATE TRIGGER assumption_overrides_no_delete
        BEFORE DELETE ON hm.assumption_overrides
        FOR EACH ROW EXECUTE FUNCTION hm.assumption_overrides_immutable();
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'audit_assumption_overrides'
          AND tgrelid = 'hm.assumption_overrides'::regclass
    ) THEN
        CREATE TRIGGER audit_assumption_overrides
        AFTER INSERT OR UPDATE OR DELETE ON hm.assumption_overrides
        FOR EACH ROW EXECUTE FUNCTION audit.log_row_change();
    END IF;
END $$;

-- ── Expand forecast tables for Phase 2 ────────────────────────────────────────
ALTER TABLE hm.forecast_runs
    ADD COLUMN IF NOT EXISTS as_of          DATE,
    ADD COLUMN IF NOT EXISTS engine_version TEXT,
    ADD COLUMN IF NOT EXISTS params         JSONB;

ALTER TABLE hm.forecast_lines
    ADD COLUMN IF NOT EXISTS scenario          TEXT,
    ADD COLUMN IF NOT EXISTS value             NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS p_below_threshold NUMERIC(8,6);

-- ── Permissions ───────────────────────────────────────────────────────────────
GRANT SELECT ON hm.assumption_overrides TO hm_reader;
GRANT SELECT ON hm.assumption_overrides TO hm_analyst;
GRANT SELECT ON hm.assumption_overrides TO hm_evaluator;
GRANT INSERT ON hm.assumption_overrides TO hm_approver;
GRANT USAGE  ON SEQUENCE hm.assumption_overrides_override_id_seq TO hm_approver;
GRANT ALL    ON hm.assumption_overrides TO hm_admin;
GRANT ALL    ON SEQUENCE hm.assumption_overrides_override_id_seq TO hm_admin;
