from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.judge import evaluate_answer


@pytest.mark.asyncio
async def test_mock_judge_passes_against_reference_overlap() -> None:
    result = await evaluate_answer(
        input_text="What is FastAPI?",
        output="FastAPI is a Python web framework for APIs.",
        reference="Python web framework",
        judge_model="mock/judge",
        judge_provider="mock",
        pass_threshold=0.7,
    )

    assert result.passed is True
    assert result.score >= 0.7
    assert result.reason


@pytest.mark.asyncio
async def test_mock_judge_scores_empty_output_as_zero() -> None:
    result = await evaluate_answer(
        input_text="Question",
        output="",
        reference=None,
        judge_model="mock/judge",
        judge_provider="mock",
        pass_threshold=0.7,
    )

    assert result.score == 0
    assert result.passed is False


@pytest.mark.asyncio
async def test_openrouter_judge_falls_back_when_response_format_is_unsupported() -> None:
    seen_payloads: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        seen_payloads.append(payload)
        if "response_format" in payload:
            return httpx.Response(
                400,
                json={"error": {"message": "response_format unsupported by this model"}},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"score": 0.82, "passed": True, "reason": "Solid answer."}
                            )
                        }
                    }
                ]
            },
            request=request,
        )

    settings = Settings(
        openrouter_api_key="test-key",
        local_mock_without_keys=False,
        openrouter_base_url="https://openrouter.test/api/v1",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await evaluate_answer(
            input_text="Question",
            output="Answer",
            reference=None,
            judge_model="openrouter/free",
            judge_provider="openrouter",
            pass_threshold=0.7,
            settings=settings,
            client=client,
        )

    assert result.score == 0.82
    assert len(seen_payloads) == 2
    assert "response_format" in seen_payloads[0]
    assert "response_format" not in seen_payloads[1]
