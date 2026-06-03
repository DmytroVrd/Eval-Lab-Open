from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.targets import call_target_model


@pytest.mark.asyncio
async def test_target_retries_429_and_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    sleeps: list[float] = []
    payloads: list[dict] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.llm_http.asyncio.sleep", fake_sleep)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        payloads.append(json.loads(request.content.decode("utf-8")))
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        if attempts == 2:
            return httpx.Response(500, request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Retried answer"}}]},
            request=request,
        )

    settings = Settings(
        openrouter_api_key="test-key",
        local_mock_without_keys=False,
        openrouter_base_url="https://openrouter.test/api/v1",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        output, latency_ms = await call_target_model(
            prompt="Question",
            model="openrouter/free",
            temperature=0.6,
            settings=settings,
            client=client,
        )

    assert output == "Retried answer"
    assert latency_ms >= 0
    assert attempts == 3
    assert sleeps == [0.0, 4.0]
    assert payloads[-1]["temperature"] == 0.6


@pytest.mark.asyncio
async def test_groq_target_uses_openai_compatible_payload() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Groq answer"}}]},
            request=request,
        )

    settings = Settings(
        groq_api_key="groq-key",
        local_mock_without_keys=False,
        groq_base_url="https://groq.test/openai/v1",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        output, _ = await call_target_model(
            prompt="Question",
            model="groq/llama-3.3-70b-versatile",
            temperature=0.1,
            settings=settings,
            client=client,
        )

    assert output == "Groq answer"
    assert seen["url"] == "https://groq.test/openai/v1/chat/completions"
    assert seen["auth"] == "Bearer groq-key"
    assert seen["payload"] == {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": "Question"}],
        "temperature": 0.1,
    }


@pytest.mark.asyncio
async def test_gemini_target_uses_generate_content_payload() -> None:
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
                            "parts": [{"text": "Gemini answer"}],
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
        output, _ = await call_target_model(
            prompt="Question",
            model="gemini/gemini-2.5-flash",
            temperature=0.3,
            settings=settings,
            client=client,
        )

    assert output == "Gemini answer"
    assert seen["url"] == "https://gemini.test/v1beta/models/gemini-2.5-flash:generateContent"
    assert seen["key"] == "gemini-key"
    assert seen["payload"] == {
        "contents": [{"parts": [{"text": "Question"}]}],
        "generationConfig": {"temperature": 0.3},
    }


@pytest.mark.asyncio
async def test_missing_gemini_key_uses_mock_when_allowed() -> None:
    settings = Settings(local_mock_without_keys=True, gemini_api_key=None)

    output, _ = await call_target_model(
        prompt="Question",
        model="gemini/gemini-2.5-flash",
        settings=settings,
    )

    assert output.startswith("[mock target: gemini/gemini-2.5-flash]")
