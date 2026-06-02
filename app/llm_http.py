from __future__ import annotations

import asyncio
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any

import httpx

RETRY_STATUSES = {429, 500, 502, 503, 504}


def retry_delay_seconds(response: httpx.Response, attempt_index: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                pass
    return float(2 ** (attempt_index + 1))


async def post_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    json_payload: dict[str, Any],
    max_attempts: int = 3,
) -> httpx.Response:
    response: httpx.Response | None = None
    for attempt_index in range(max_attempts):
        response = await client.post(url, headers=headers, json=json_payload)
        if response.status_code not in RETRY_STATUSES or attempt_index >= max_attempts - 1:
            return response
        await asyncio.sleep(retry_delay_seconds(response, attempt_index))
    assert response is not None
    return response

