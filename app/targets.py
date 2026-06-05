from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings
from app.llm_http import RETRY_STATUSES, post_with_retries
from app.rate_limit import wait_for_provider_slot


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


def _gemini_parts_to_text(parts: Any) -> str:
    if not isinstance(parts, Sequence):
        return ""
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return "\n".join(texts)


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

    provider, provider_model = _split_model_provider(model)

    if model.startswith("mock/") or _should_mock(provider, settings):
        return _mock_target_response(prompt, model), int((time.perf_counter() - started) * 1000)

    close_client = client is None
    http = client or httpx.AsyncClient(timeout=settings.request_timeout_seconds)
    try:
        if provider == "gemini":
            if close_client:
                await wait_for_provider_slot("gemini", settings.gemini_min_interval_seconds)
            output = await _call_gemini(
                http=http,
                prompt=prompt,
                model=provider_model,
                temperature=temperature,
                settings=settings,
            )
        elif provider == "groq":
            if close_client:
                await wait_for_provider_slot("groq", settings.groq_min_interval_seconds)
            output = await _call_openai_compatible(
                http=http,
                prompt=prompt,
                model=provider_model,
                temperature=temperature,
                base_url=settings.groq_base_url,
                api_key=settings.groq_api_key,
                provider_name="Groq",
            )
        else:
            if close_client:
                await wait_for_provider_slot(
                    "openrouter",
                    settings.openrouter_min_interval_seconds,
                )
            output = await _call_openai_compatible(
                http=http,
                prompt=prompt,
                model=provider_model,
                temperature=temperature,
                base_url=settings.openrouter_base_url,
                api_key=settings.openrouter_api_key,
                provider_name="OpenRouter",
            )
        return output, int((time.perf_counter() - started) * 1000)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        if exc.response.status_code in RETRY_STATUSES:
            raise LLMCallError(
                f"{provider.title()} stayed unavailable after retries "
                f"({exc.response.status_code}): {detail}"
            ) from exc
        raise LLMCallError(f"{provider.title()} error {exc.response.status_code}: {detail}") from exc
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
        raise LLMCallError(f"{provider.title()} call failed: {exc}") from exc
    finally:
        if close_client:
            await http.aclose()


def _split_model_provider(model: str) -> tuple[str, str]:
    if model.startswith("gemini/"):
        return "gemini", model.removeprefix("gemini/")
    if model.startswith("groq/"):
        return "groq", model.removeprefix("groq/")
    return "openrouter", model


def _should_mock(provider: str, settings: Settings) -> bool:
    if not settings.local_mock_without_keys:
        return False
    return (
        (provider == "openrouter" and not settings.openrouter_api_key)
        or (provider == "gemini" and not settings.gemini_api_key)
        or (provider == "groq" and not settings.groq_api_key)
    )


async def _call_openai_compatible(
    *,
    http: httpx.AsyncClient,
    prompt: str,
    model: str,
    temperature: float | None,
    base_url: str,
    api_key: str | None,
    provider_name: str,
) -> str:
    if not api_key:
        raise LLMCallError(f"{provider_name.upper()}_API_KEY is required for non-mock target calls.")

    response = await post_with_retries(
        http,
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
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
        raise LLMCallError(f"{provider_name} returned an empty response.")
    return output


async def _call_gemini(
    *,
    http: httpx.AsyncClient,
    prompt: str,
    model: str,
    temperature: float | None,
    settings: Settings,
) -> str:
    if not settings.gemini_api_key:
        raise LLMCallError("GEMINI_API_KEY is required for non-mock target calls.")

    response = await post_with_retries(
        http,
        f"{settings.gemini_base_url.rstrip('/')}/models/{quote(model, safe='')}:generateContent",
        headers={
            "x-goog-api-key": settings.gemini_api_key,
            "Content-Type": "application/json",
        },
        json_payload={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2 if temperature is None else temperature,
            },
        },
    )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        prompt_feedback = payload.get("promptFeedback") or payload.get("prompt_feedback")
        raise LLMCallError(f"Gemini returned no candidates. Feedback: {prompt_feedback or payload}")
    candidate = candidates[0]
    content = candidate.get("content", {})
    output = _gemini_parts_to_text(content.get("parts")).strip()
    if not output:
        finish_reason = candidate.get("finishReason") or candidate.get("finish_reason")
        safety_ratings = candidate.get("safetyRatings") or candidate.get("safety_ratings")
        raise LLMCallError(
            "Gemini returned an empty response. "
            f"Finish reason: {finish_reason}; safety ratings: {safety_ratings}"
        )
    return output
