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


@pytest.mark.asyncio
async def test_groq_judge_uses_openai_compatible_payload() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"score": 0.91, "passed": True, "reason": "Good answer."}
                            )
                        }
                    }
                ]
            },
            request=request,
        )

    settings = Settings(
        groq_api_key="groq-key",
        local_mock_without_keys=False,
        groq_base_url="https://groq.test/openai/v1",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await evaluate_answer(
            input_text="Question",
            output="Answer",
            reference=None,
            judge_model="groq/llama-3.3-70b-versatile",
            judge_provider="groq",
            pass_threshold=0.7,
            settings=settings,
            client=client,
        )

    assert result.score == 0.91
    assert seen["url"] == "https://groq.test/openai/v1/chat/completions"
    assert seen["auth"] == "Bearer groq-key"
    assert seen["payload"]["model"] == "llama-3.3-70b-versatile"
    assert seen["payload"]["response_format"] == {"type": "json_object"}
    messages = " ".join(message["content"] for message in seen["payload"]["messages"])
    assert "JSON" in messages


@pytest.mark.asyncio
async def test_groq_judge_retries_without_response_format_when_provider_rejects_it() -> None:
    seen_payloads: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        seen_payloads.append(payload)
        if "response_format" in payload:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "'messages' must contain the word 'json' in some form",
                        "type": "invalid_request_error",
                    }
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"score": 0.77, "passed": True, "reason": "Parsed without JSON mode."}
                            )
                        }
                    }
                ]
            },
            request=request,
        )

    settings = Settings(
        groq_api_key="groq-key",
        local_mock_without_keys=False,
        groq_base_url="https://groq.test/openai/v1",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await evaluate_answer(
            input_text="Question",
            output="Answer",
            reference=None,
            judge_model="groq/llama-3.3-70b-versatile",
            judge_provider="groq",
            pass_threshold=0.7,
            settings=settings,
            client=client,
        )

    assert result.score == 0.77
    assert len(seen_payloads) == 2
    assert "response_format" in seen_payloads[0]
    assert "response_format" not in seen_payloads[1]


@pytest.mark.asyncio
async def test_gemini_judge_uses_generate_content_payload() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "score": 0.84,
                                            "passed": True,
                                            "reason": "Useful answer.",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
            request=request,
        )

    settings = Settings(
        gemini_api_key="gemini-key",
        local_mock_without_keys=False,
        gemini_base_url="https://gemini.test/v1beta",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await evaluate_answer(
            input_text="Question",
            output="Answer",
            reference=None,
            judge_model="gemini/gemini-2.5-flash",
            judge_provider="gemini",
            pass_threshold=0.7,
            settings=settings,
            client=client,
        )

    assert result.score == 0.84
    assert seen["url"] == "https://gemini.test/v1beta/models/gemini-2.5-flash:generateContent"
    assert seen["key"] == "gemini-key"
    assert seen["payload"]["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.asyncio
async def test_groq_judge_uses_mock_without_key_when_allowed() -> None:
    result = await evaluate_answer(
        input_text="Question",
        output="Answer with enough useful context.",
        reference=None,
        judge_model="groq/llama-3.3-70b-versatile",
        judge_provider="groq",
        pass_threshold=0.7,
        settings=Settings(local_mock_without_keys=True, groq_api_key=None),
    )

    assert result.reason.startswith("Mock judge")
