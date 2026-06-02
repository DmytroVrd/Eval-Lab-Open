from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import AppConfigRead

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config", response_model=AppConfigRead)
async def read_config() -> AppConfigRead:
    settings = get_settings()
    return AppConfigRead(
        default_target_model=settings.default_target_model,
        default_model=settings.default_target_model,
        default_judge_model=settings.default_judge_model,
        default_judge_provider=settings.default_judge_provider,
        models=[
            settings.default_target_model,
            "mock/target",
        ],
        judge_models=[
            settings.default_judge_model,
            "mock/judge",
        ],
        pass_threshold=settings.pass_threshold,
        max_concurrency=settings.max_concurrency,
        openrouter_configured=bool(settings.openrouter_api_key),
        anthropic_configured=bool(settings.anthropic_api_key),
        local_mock_without_keys=settings.local_mock_without_keys,
    )
