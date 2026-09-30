"""Project settings — reads .env with override=True so .env always wins."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv(Path(__file__).parent.parent / ".env", override=True)


class Settings(BaseSettings):
    # ── Postgres (DB owner / app superuser) ───────────────────────────────────
    postgres_host:     str = "localhost"
    postgres_port:     int = 5433
    postgres_db:       str = "headroom"
    postgres_user:     str = "headroom"
    postgres_password: str = Field(default="changeme", repr=False)

    # ── Application role passwords (set on roles by scripts/migrate.py) ───────
    hm_reader_password:    str = Field(default="", repr=False)
    hm_analyst_password:   str = Field(default="", repr=False)
    hm_approver_password:  str = Field(default="", repr=False)
    hm_evaluator_password: str = Field(default="", repr=False)
    hm_admin_password:     str = Field(default="", repr=False)

    # ── Vault ─────────────────────────────────────────────────────────────────
    hm_vault_key: str = Field(default="", repr=False)

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider:      Literal["local", "haiku"] = "local"
    ollama_model:      str = "llama3.2"
    anthropic_api_key: str = Field(default="", repr=False)

    # ── Forecasting rules ─────────────────────────────────────────────────────
    safety_weeks: int = 4

    # ── Generator reproducibility ─────────────────────────────────────────────
    seed: int = 42

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def role_dsn(self, role: str) -> str:
        """Return a SQLAlchemy DSN for a named application role."""
        password = getattr(self, f"{role}_password", "")
        return (
            f"postgresql+psycopg://{role}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
