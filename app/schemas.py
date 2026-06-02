from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import RunStatus


class TestSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TestCaseCreate(BaseModel):
    input: str = Field(min_length=1)
    reference: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "input" not in normalized:
            for key in ("prompt", "question", "text"):
                if key in normalized:
                    normalized["input"] = normalized[key]
                    break
        if "reference" not in normalized:
            for key in ("expected", "expected_output", "answer", "target"):
                if key in normalized:
                    normalized["reference"] = normalized[key]
                    break
        return normalized


class TestCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    test_set_id: int
    input: str
    reference: str | None
    created_at: datetime


class TestSetSummary(BaseModel):
    id: int
    name: str
    created_at: datetime
    case_count: int = 0


class TestSetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    cases: list[TestCaseRead] = []


class RunCreate(BaseModel):
    test_set_id: int
    target_model: str | None = None
    judge_model: str | None = None
    judge_provider: Literal["openrouter", "anthropic", "mock"] | None = None
    prompt_template: str | None = Field(default=None, min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_cases: int | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "target_model" not in normalized:
            for key in ("model", "model_name"):
                if key in normalized:
                    normalized["target_model"] = normalized[key]
                    break
        config = normalized.get("config")
        if isinstance(config, dict):
            for key in (
                "target_model",
                "judge_model",
                "judge_provider",
                "prompt_template",
                "temperature",
                "max_cases",
            ):
                if key not in normalized and key in config:
                    normalized[key] = config[key]
            if "target_model" not in normalized:
                for key in ("model", "model_name"):
                    if key in config:
                        normalized["target_model"] = config[key]
                        break
        return normalized

    @field_validator("prompt_template")
    @classmethod
    def must_contain_input_placeholder(cls, value: str | None) -> str | None:
        if value is not None and "{input}" not in value:
            raise ValueError("prompt_template must contain {input}")
        return value


class RunQueued(BaseModel):
    run_id: int


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    test_set_id: int
    target_model: str
    judge_model: str
    judge_provider: str
    prompt_template: str
    temperature: float | None
    max_cases: int | None
    status: RunStatus
    avg_score: float | None
    pass_rate: float | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    done_count: int
    total_count: int
    model: str
    score: float | None
    completed: int
    total: int


class ResultRead(BaseModel):
    id: int
    run_id: int
    test_case_id: int
    input: str
    reference: str | None
    output: str
    score: float
    passed: bool
    judge_reason: str
    latency_ms: int
    error: str | None


class AppConfigRead(BaseModel):
    default_target_model: str
    default_model: str
    default_judge_model: str
    default_judge_provider: str
    models: list[str]
    judge_models: list[str]
    pass_threshold: float
    max_concurrency: int
    openrouter_configured: bool
    anthropic_configured: bool
    local_mock_without_keys: bool
