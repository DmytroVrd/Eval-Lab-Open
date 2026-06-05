from __future__ import annotations

import httpx
import pytest

from app.llm_http import post_with_retries


@pytest.mark.asyncio
async def test_post_with_retries_runs_before_attempt_for_each_try() -> None:
    attempts = 0
    slots = 0

    async def before_attempt() -> None:
        nonlocal slots
        slots += 1

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        status_code = 503 if attempts < 3 else 200
        return httpx.Response(
            status_code,
            headers={"Retry-After": "0"},
            json={"ok": True},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await post_with_retries(
            client,
            "https://provider.test/generate",
            headers={},
            json_payload={},
            before_attempt=before_attempt,
        )

    assert response.status_code == 200
    assert attempts == 3
    assert slots == 3
