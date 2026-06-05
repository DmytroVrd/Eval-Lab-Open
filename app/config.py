from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Eval Lab"
    database_url: str = "sqlite+aiosqlite:///./eval_lab.db"

    openrouter_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    groq_api_key: str | None = None

    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    default_target_model: str = "openrouter/free"
    default_gemini_model: str = "gemini-2.5-flash"
    default_groq_model: str = "llama-3.3-70b-versatile"
    default_judge_provider: Literal["openrouter", "anthropic", "gemini", "groq", "mock"] = "openrouter"
    default_judge_model: str = "openrouter/free"

    pass_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    max_concurrency: int = Field(default=2, ge=1, le=20)
    request_timeout_seconds: float = Field(default=60.0, ge=5.0)
    openrouter_min_interval_seconds: float = Field(default=3.2, ge=0.0)
    gemini_min_interval_seconds: float = Field(default=12.5, ge=0.0)
    groq_min_interval_seconds: float = Field(default=1.0, ge=0.0)
    fallback_to_mock_judge_on_error: bool = True

    local_mock_without_keys: bool = True

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("sqlite:///"):
            return value.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
