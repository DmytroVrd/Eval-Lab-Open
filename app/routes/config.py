from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import AppConfigRead

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config", response_model=AppConfigRead)
async def read_config() -> AppConfigRead:
    settings = get_settings()
    models = _unique(
        [
            settings.default_target_model,
            "mock/target",
            f"gemini/{settings.default_gemini_model}",
            f"groq/{settings.default_groq_model}",
        ]
    )
    judge_models = _unique([settings.default_judge_model, "mock/judge"])
    return AppConfigRead(
        default_target_model=settings.default_target_model,
        default_model=settings.default_target_model,
        default_judge_model=settings.default_judge_model,
        default_judge_provider=settings.default_judge_provider,
        models=models,
        judge_models=judge_models,
        pass_threshold=settings.pass_threshold,
        max_concurrency=settings.max_concurrency,
        openrouter_configured=bool(settings.openrouter_api_key),
        anthropic_configured=bool(settings.anthropic_api_key),
        gemini_configured=bool(settings.gemini_api_key),
        groq_configured=bool(settings.groq_api_key),
        local_mock_without_keys=settings.local_mock_without_keys,
    )


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
