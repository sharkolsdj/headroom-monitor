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

# ── test 1: migrations are idempotent ─────────────────────────────────────────

def test_migrations_idempotent(owner_engine):
    """Running apply_migrations a second time must apply zero new files."""
    applied = apply_migrations(engine=owner_engine, migrations_dir=MIGRATIONS_DIR, verbose=False)
    assert applied == 0, f"Second run applied {applied} migration(s); expected 0"

def test_all_migration_files_recorded(owner_engine):
    """Every .sql file in migrations/ must appear in hm.schema_migrations."""
    expected = {f.name for f in sorted(MIGRATIONS_DIR.glob("*.sql"))}
    actual   = set()
    with owner_engine.connect() as conn:
        rows = conn.execute(text("SELECT filename FROM hm.schema_migrations"))
        actual = {r[0] for r in rows}
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

    # Insert, then update in separate transactions so audit entries are committed
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
            ORDER BY ts DESC
            LIMIT  1
        """), {"id": ds_id}).fetchone()

    assert row is not None, "No audit row found for UPDATE on hm.datasets"
    assert row.old_row["description"] == "original"
    assert row.new_row["description"] == "updated"

    # Cleanup
    _exec(owner_engine, "DELETE FROM hm.datasets WHERE dataset_id = :id", id=ds_id)

# ── test 4: parameters is append-only ─────────────────────────────────────────

def test_parameters_rejects_update(owner_engine):
    """UPDATE on hm.parameters must raise an exception."""
    _exec(owner_engine,
          "INSERT INTO hm.parameters (key, value, version) "
          "VALUES ('_test_key', '\"v1\"'::jsonb, 99) "
          "ON CONFLICT DO NOTHING")

    with pytest.raises(Exception, match="(?i)append-only|parameters"):
        with owner_engine.begin() as conn:
            conn.execute(text(
                "UPDATE hm.parameters SET value = '\"v2\"'::jsonb WHERE key = '_test_key'"
            ))

    # Cleanup
    _exec(owner_engine, "DELETE FROM hm.parameters WHERE key = '_test_key'")
