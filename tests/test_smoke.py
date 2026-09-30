"""Smoke test: verify Postgres is reachable and the target database exists."""
import pytest
import sqlalchemy as sa

from config import settings


def test_postgres_connection():
    engine = sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)
    with engine.connect() as conn:
        result = conn.execute(sa.text("SELECT 1")).scalar()
    assert result == 1, "Expected SELECT 1 to return 1"


def test_postgres_database_name():
    engine = sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)
    with engine.connect() as conn:
        db_name = conn.execute(sa.text("SELECT current_database()")).scalar()
    assert db_name == settings.postgres_db
