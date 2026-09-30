from __future__ import annotations

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv(Path(__file__).parent / ".env")


class Settings(BaseSettings):
    # Postgres
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_db: str = "headroom"
    postgres_user: str = "headroom"
    postgres_password: str = "changeme"

    # LLM
    llm_provider: Literal["local", "haiku"] = "local"
    ollama_model: str = "llama3.2"
    anthropic_api_key: str = Field(default="", repr=False)

    # Forecasting rules
    safety_weeks: int = 4

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
