"""Apply SQL migrations in order. Idempotent: already-applied files are skipped."""
from __future__ import annotations

import sys
from pathlib import Path

import sqlalchemy as sa

# config.py handles load_dotenv with override=True; always import settings from there.
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import settings  # noqa: E402

MIGRATIONS_DIR = ROOT / "migrations"

ROLE_ENV_VARS: dict[str, str] = {
    "hm_reader":    "HM_READER_PASSWORD",
    "hm_analyst":   "HM_ANALYST_PASSWORD",
    "hm_approver":  "HM_APPROVER_PASSWORD",
    "hm_evaluator": "HM_EVALUATOR_PASSWORD",
    "hm_admin":     "HM_ADMIN_PASSWORD",
}


def _owner_engine() -> sa.Engine:
    """Connect as the DB owner (POSTGRES_USER) for DDL and migration tracking."""
    return sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)


def _bootstrap(conn: sa.Connection) -> None:
    """Ensure hm schema and schema_migrations table exist before anything else."""
    conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS hm"))
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS hm.schema_migrations (
            filename   TEXT        PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))


def _applied(conn: sa.Connection) -> set[str]:
    rows = conn.execute(sa.text("SELECT filename FROM hm.schema_migrations"))
    return {r[0] for r in rows}


def _set_role_passwords(engine: sa.Engine) -> None:
    """Set role passwords from settings (idempotent ALTER ROLE)."""
    role_passwords = {
        "hm_reader":    settings.hm_reader_password,
        "hm_analyst":   settings.hm_analyst_password,
        "hm_approver":  settings.hm_approver_password,
        "hm_evaluator": settings.hm_evaluator_password,
        "hm_admin":     settings.hm_admin_password,
    }
    with engine.begin() as conn:
        for role, password in role_passwords.items():
            if not password:
                print(f"  warn  password not set for {role} — skipping")
                continue
            # ALTER ROLE PASSWORD does not accept bind params in Postgres DDL.
            # Passwords are escaped by doubling single-quote chars.
            escaped = password.replace("'", "''")
            conn.execute(sa.text(f"ALTER ROLE {role} PASSWORD '{escaped}'"))


def apply_migrations(
    engine: sa.Engine | None = None,
    migrations_dir: Path | None = None,
    verbose: bool = True,
) -> int:
    """Apply pending migrations. Returns number of migrations applied."""
    engine = engine or _owner_engine()
    migrations_dir = migrations_dir or MIGRATIONS_DIR

    files = sorted(migrations_dir.glob("*.sql"))
    applied_count = 0

    with engine.begin() as conn:
        _bootstrap(conn)
        already = _applied(conn)

        for f in files:
            if f.name in already:
                if verbose:
                    print(f"  skip   {f.name}")
                continue
            if verbose:
                print(f"  apply  {f.name}")
            conn.execute(sa.text(f.read_text(encoding="utf-8")))
            conn.execute(
                sa.text("INSERT INTO hm.schema_migrations (filename) VALUES (:n)"),
                {"n": f.name},
            )
            applied_count += 1

    _set_role_passwords(engine)
    return applied_count


if __name__ == "__main__":
    n = apply_migrations(verbose=True)
    print(f"Done. {n} migration(s) applied.")
    sys.exit(0)
