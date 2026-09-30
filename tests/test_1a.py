"""
1A tests: migrations, roles, vault isolation, audit trigger, parameters immutability.
Migrations are applied once per session via the autouse fixture.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from config import settings
from scripts.migrate import apply_migrations, MIGRATIONS_DIR, _owner_engine

# ── session-scoped setup ──────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def run_migrations():
    """Apply all migrations before any test in this module runs."""
    apply_migrations(verbose=False)


@pytest.fixture(scope="session")
def owner_engine():
    return _owner_engine()


@pytest.fixture(scope="session")
def analyst_engine():
    return sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def _exec(engine, sql, **params):
    with engine.begin() as conn:
        return conn.execute(text(sql), params)

def _scalar(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()

def _delete_parameter_bypass(engine, key: str) -> None:
    """Delete from hm.parameters for test cleanup, bypassing immutability triggers."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE hm.parameters DISABLE TRIGGER parameters_no_update"))
        conn.execute(text("ALTER TABLE hm.parameters DISABLE TRIGGER parameters_no_delete"))
        conn.execute(text("DELETE FROM hm.parameters WHERE key = :k"), {"k": key})
        conn.execute(text("ALTER TABLE hm.parameters ENABLE TRIGGER parameters_no_update"))
        conn.execute(text("ALTER TABLE hm.parameters ENABLE TRIGGER parameters_no_delete"))

# ── test 1: migrations are idempotent ─────────────────────────────────────────

def test_migrations_idempotent(owner_engine):
    """Running apply_migrations a second time must apply zero new files."""
    applied = apply_migrations(engine=owner_engine, migrations_dir=MIGRATIONS_DIR, verbose=False)
    assert applied == 0, f"Second run applied {applied} migration(s); expected 0"

def test_all_migration_files_recorded(owner_engine):
    """Every .sql file in migrations/ must appear in hm.schema_migrations."""
    expected = {f.name for f in sorted(MIGRATIONS_DIR.glob("*.sql"))}
    with owner_engine.connect() as conn:
        actual = {r[0] for r in conn.execute(text("SELECT filename FROM hm.schema_migrations"))}
    assert expected == actual

# ── test 2: hm_analyst permission isolation ───────────────────────────────────

@pytest.mark.parametrize("schema,table", [
    ("vault", "identity_map"),
    ("eval",  "scenario_truth"),
    ("audit", "log"),
])
def test_analyst_denied_on_protected_schemas(analyst_engine, schema, table):
    """hm_analyst must get permission denied on vault, eval, and audit tables."""
    with pytest.raises(Exception, match="(?i)permission denied|not found|does not exist"):
        with analyst_engine.connect() as conn:
            conn.execute(text(f"SELECT 1 FROM {schema}.{table} LIMIT 1"))

# ── test 3: UPDATE on hm table creates an audit row with old and new values ───

def test_update_creates_audit_row_with_old_new(owner_engine):
    """An UPDATE on hm.datasets must produce an audit.log row with old_row/new_row."""
    ds_id = "TEST_AUDIT_1A"
    _exec(owner_engine,
          "INSERT INTO hm.datasets (dataset_id, description, seed, as_of_date) "
          "VALUES (:id, 'original', 42, '2026-01-01') "
          "ON CONFLICT (dataset_id) DO UPDATE SET description = 'original'",
          id=ds_id)
    _exec(owner_engine,
          "UPDATE hm.datasets SET description = 'updated' WHERE dataset_id = :id",
          id=ds_id)
    with owner_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT old_row, new_row
            FROM   audit.log
            WHERE  op = 'UPDATE'
              AND  table_name = 'hm.datasets'
              AND  new_row->>'dataset_id' = :id
            ORDER BY ts DESC LIMIT 1
        """), {"id": ds_id}).fetchone()
    assert row is not None, "No audit row found for UPDATE on hm.datasets"
    assert row.old_row["description"] == "original"
    assert row.new_row["description"] == "updated"
    _exec(owner_engine, "DELETE FROM hm.datasets WHERE dataset_id = :id", id=ds_id)

# ── test 4: parameters is append-only (UPDATE) ────────────────────────────────

def test_parameters_rejects_update(owner_engine):
    """UPDATE on hm.parameters must raise an exception."""
    _exec(owner_engine,
          "INSERT INTO hm.parameters (key, value, version) "
          "VALUES ('_test_key', '\"v1\"'::jsonb, 99) ON CONFLICT DO NOTHING")
    with pytest.raises(Exception, match="(?i)append-only|parameters"):
        with owner_engine.begin() as conn:
            conn.execute(text(
                "UPDATE hm.parameters SET value = '\"v2\"'::jsonb WHERE key = '_test_key'"
            ))
    _delete_parameter_bypass(owner_engine, "_test_key")

# ── test 5 (new): parameters rejects DELETE ───────────────────────────────────

def test_parameters_rejects_delete(owner_engine):
    """DELETE on hm.parameters must raise an exception (append-only)."""
    _exec(owner_engine,
          "INSERT INTO hm.parameters (key, value, version) "
          "VALUES ('_test_del', '\"v1\"'::jsonb, 99) ON CONFLICT DO NOTHING")
    with pytest.raises(Exception, match="(?i)append-only|parameters"):
        with owner_engine.begin() as conn:
            conn.execute(text("DELETE FROM hm.parameters WHERE key = '_test_del'"))
    _delete_parameter_bypass(owner_engine, "_test_del")

# ── test 6 (new): analyst INSERT creates an audit row ────────────────────────

def test_analyst_insert_creates_audit_row(owner_engine, analyst_engine):
    """hm_analyst inserting into hm.forecast_runs must produce an audit.log row."""
    ds_id = "TEST_ANALYST_AUDIT"
    _exec(owner_engine,
          "INSERT INTO hm.datasets (dataset_id, description, seed, as_of_date) "
          "VALUES (:id, 'analyst audit test', 10, '2026-01-01') ON CONFLICT DO NOTHING",
          id=ds_id)
    try:
        _exec(analyst_engine,
              "INSERT INTO hm.forecast_runs (dataset_id) VALUES (:id)", id=ds_id)
        with owner_engine.connect() as conn:
            count = conn.execute(text("""
                SELECT count(*) FROM audit.log
                WHERE  table_name = 'hm.forecast_runs'
                  AND  db_user    = 'hm_analyst'
                  AND  op         = 'INSERT'
            """)).scalar()
        assert count > 0, "Expected an audit INSERT row from hm_analyst"
    finally:
        _exec(owner_engine, "DELETE FROM hm.datasets WHERE dataset_id = :id", id=ds_id)

# ── test 7 (new): analyst setting bulk_load GUC is ignored by trigger ─────────

def test_analyst_bulk_load_guc_ignored(owner_engine, analyst_engine):
    """hm_analyst setting hm.bulk_load='on' must still produce row-level audit rows."""
    ds_id = "TEST_BULK_BYPASS"
    _exec(owner_engine,
          "INSERT INTO hm.datasets (dataset_id, description, seed, as_of_date) "
          "VALUES (:id, 'bulk bypass test', 11, '2026-01-01') ON CONFLICT DO NOTHING",
          id=ds_id)
    try:
        with analyst_engine.begin() as conn:
            conn.execute(text("SET hm.bulk_load = 'on'"))
            conn.execute(text("SET hm.bulk_row_count = '999'"))
            conn.execute(text(
                "INSERT INTO hm.forecast_runs (dataset_id) VALUES (:id)"
            ), {"id": ds_id})
        # The trigger must have written a row-level INSERT, not a BULK_LOAD summary
        with owner_engine.connect() as conn:
            row = conn.execute(text("""
                SELECT op FROM audit.log
                WHERE  table_name = 'hm.forecast_runs'
                  AND  db_user    = 'hm_analyst'
                ORDER BY ts DESC LIMIT 1
            """)).fetchone()
        assert row is not None, "No audit row found"
        assert row.op == "INSERT", (
            f"Expected row-level INSERT audit entry but got '{row.op}' — "
            "bulk_load GUC must not bypass audit for non-admin roles"
        )
    finally:
        _exec(owner_engine, "DELETE FROM hm.datasets WHERE dataset_id = :id", id=ds_id)

# ── test 8 (new): analyst cannot UPDATE or DELETE audit.log ───────────────────

@pytest.mark.parametrize("stmt", [
    "UPDATE audit.log SET op = 'TAMPER' WHERE id = -1",
    "DELETE FROM audit.log WHERE id = -1",
])
def test_analyst_cannot_modify_audit_log(analyst_engine, stmt):
    """hm_analyst must be denied UPDATE and DELETE on audit.log."""
    with pytest.raises(Exception,
                       match="(?i)permission denied|does not exist|schema"):
        with analyst_engine.begin() as conn:
            conn.execute(text(stmt))
