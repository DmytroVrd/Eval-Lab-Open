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
