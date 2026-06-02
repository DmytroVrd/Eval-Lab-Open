from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.llm_http import RETRY_STATUSES, post_with_retries


class LLMCallError(RuntimeError):
    pass


def _mock_target_response(prompt: str, model: str) -> str:
    preview = " ".join(prompt.strip().split())[:240]
    return (
        f"[mock target: {model}] This is a deterministic local response for: {preview}"
    )


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


async def call_target_model(
    *,
    prompt: str,
    model: str,
    temperature: float | None = None,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, int]:
    settings = settings or get_settings()
    started = time.perf_counter()

    if model.startswith("mock/") or (
        settings.local_mock_without_keys and not settings.openrouter_api_key
    ):
        return _mock_target_response(prompt, model), int((time.perf_counter() - started) * 1000)

    if not settings.openrouter_api_key:
        raise LLMCallError("OPENROUTER_API_KEY is required for non-mock target calls.")

    close_client = client is None
    http = client or httpx.AsyncClient(timeout=settings.request_timeout_seconds)
    try:
        response = await post_with_retries(
            http,
            f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "X-Title": "AI Eval Lab",
            },
            json_payload={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2 if temperature is None else temperature,
            },
        )
        response.raise_for_status()
        payload = response.json()
        choice = payload.get("choices", [{}])[0]
        message = choice.get("message", {})
        output = _content_to_text(message.get("content")).strip()
        if not output:
            raise LLMCallError("OpenRouter returned an empty response.")
        return output, int((time.perf_counter() - started) * 1000)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        if exc.response.status_code in RETRY_STATUSES:
            raise LLMCallError(
                f"OpenRouter stayed unavailable after retries ({exc.response.status_code}): {detail}"
            ) from exc
        raise LLMCallError(f"OpenRouter error {exc.response.status_code}: {detail}") from exc
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
        raise LLMCallError(f"OpenRouter call failed: {exc}") from exc
    finally:
        if close_client:
            await http.aclose()
