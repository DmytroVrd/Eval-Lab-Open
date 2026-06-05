from __future__ import annotations

import json
import re
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import Settings, get_settings
from app.llm_http import RETRY_STATUSES, post_with_retries
from app.rate_limit import wait_for_provider_slot


class JudgeError(RuntimeError):
    pass


class JudgeResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    reason: str = Field(min_length=1)


def _token_set(value: str) -> set[str]:
    return set(re.findall(r"[\w']+", value.lower()))


def _mock_judge(
    *,
    input_text: str,
    output: str,
    reference: str | None,
    pass_threshold: float,
) -> JudgeResult:
    if not output.strip():
        return JudgeResult(score=0.0, passed=False, reason="No answer was produced.")

    if reference:
        reference_tokens = _token_set(reference)
        output_tokens = _token_set(output)
        if not reference_tokens:
            score = 0.5
        else:
            score = len(reference_tokens & output_tokens) / len(reference_tokens)
        score = max(0.0, min(1.0, score))
        passed = score >= pass_threshold
        return JudgeResult(
            score=round(score, 3),
            passed=passed,
            reason="Mock judge compared lexical overlap with the reference answer.",
        )

    score = 0.75 if len(output.strip()) >= min(40, max(10, len(input_text) // 2)) else 0.45
    return JudgeResult(
        score=score,
        passed=score >= pass_threshold,
        reason="Mock judge used answer length and non-empty relevance heuristics.",
    )


def _judge_prompt(input_text: str, output: str, reference: str | None) -> str:
    reference_text = reference or "(no reference answer provided)"
    return (
        "Question/input:\n"
        f"{input_text}\n\n"
        "Model answer:\n"
        f"{output}\n\n"
        "Reference answer:\n"
        f"{reference_text}\n\n"
        'Return only a valid JSON object like {"score": 0.8, "passed": true, "reason": "short reason"}.'
    )


def _system_rubric(pass_threshold: float) -> str:
    return (
        "You are a strict evaluator of LLM answer quality. Judge factual "
        "correctness, relevance to the question, and completeness. If a reference "
        "answer is provided, compare against it. Return only valid JSON with "
        '"score", "passed", and "reason". Return score from 0 to 1, '
        f"passed = score >= {pass_threshold}, and a short reason."
    )


def _extract_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _gemini_parts_to_text(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return "\n".join(texts)


def _strip_provider_prefix(model: str, provider: str) -> str:
    return model.removeprefix(f"{provider}/")


async def evaluate_answer(
    *,
    input_text: str,
    output: str,
    reference: str | None,
    judge_model: str,
    judge_provider: Literal["openrouter", "anthropic", "gemini", "groq", "mock"] | str = "openrouter",
    pass_threshold: float | None = None,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> JudgeResult:
    settings = settings or get_settings()
    threshold = settings.pass_threshold if pass_threshold is None else pass_threshold

    if judge_provider == "mock" or judge_model.startswith("mock/"):
        return _mock_judge(
            input_text=input_text,
            output=output,
            reference=reference,
            pass_threshold=threshold,
        )

    if judge_provider == "anthropic":
        if settings.local_mock_without_keys and not settings.anthropic_api_key:
            return _mock_judge(
                input_text=input_text,
                output=output,
                reference=reference,
                pass_threshold=threshold,
            )
        return await _evaluate_with_anthropic(
            input_text=input_text,
            output=output,
            reference=reference,
            judge_model=judge_model,
            pass_threshold=threshold,
            settings=settings,
            client=client,
        )

    if judge_provider == "gemini" or judge_model.startswith("gemini/"):
        if settings.local_mock_without_keys and not settings.gemini_api_key:
            return _mock_judge(
                input_text=input_text,
                output=output,
                reference=reference,
                pass_threshold=threshold,
            )
        return await _evaluate_with_gemini(
            input_text=input_text,
            output=output,
            reference=reference,
            judge_model=judge_model,
            pass_threshold=threshold,
            settings=settings,
            client=client,
        )

    if judge_provider == "groq" or judge_model.startswith("groq/"):
        if settings.local_mock_without_keys and not settings.groq_api_key:
            return _mock_judge(
                input_text=input_text,
                output=output,
                reference=reference,
                pass_threshold=threshold,
            )
        return await _evaluate_with_groq(
            input_text=input_text,
            output=output,
            reference=reference,
            judge_model=judge_model,
            pass_threshold=threshold,
            settings=settings,
            client=client,
        )

    if settings.local_mock_without_keys and not settings.openrouter_api_key:
        return _mock_judge(
            input_text=input_text,
            output=output,
            reference=reference,
            pass_threshold=threshold,
        )
    return await _evaluate_with_openrouter(
        input_text=input_text,
        output=output,
        reference=reference,
        judge_model=judge_model,
        pass_threshold=threshold,
        settings=settings,
        client=client,
    )


async def _evaluate_with_openrouter(
    *,
    input_text: str,
    output: str,
    reference: str | None,
    judge_model: str,
    pass_threshold: float,
    settings: Settings,
    client: httpx.AsyncClient | None,
) -> JudgeResult:
    if not settings.openrouter_api_key:
        raise JudgeError("OPENROUTER_API_KEY is required for OpenRouter judge calls.")

    close_client = client is None
    http = client or httpx.AsyncClient(timeout=settings.request_timeout_seconds)
    try:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = await _post_openrouter_judge(
                    http=http,
                    settings=settings,
                    judge_model=judge_model,
                    input_text=input_text,
                    output=output,
                    reference=reference,
                    pass_threshold=pass_threshold,
                    use_response_format=True,
                    throttle=close_client,
                )
                if _is_response_format_unsupported(response):
                    response = await _post_openrouter_judge(
                        http=http,
                        settings=settings,
                        judge_model=judge_model,
                        input_text=input_text,
                        output=output,
                        reference=reference,
                        pass_threshold=pass_threshold,
                        use_response_format=False,
                        throttle=close_client,
                    )
                response.raise_for_status()
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                data = _extract_json(content)
                result = JudgeResult.model_validate(data)
                passed = result.score >= pass_threshold
                return result.model_copy(update={"passed": passed})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in RETRY_STATUSES:
                    detail = exc.response.text[:500]
                    raise JudgeError(
                        "OpenRouter judge stayed unavailable after retries "
                        f"({exc.response.status_code}): {detail}"
                    ) from exc
                detail = exc.response.text[:500]
                raise JudgeError(
                    f"OpenRouter judge error {exc.response.status_code}: {detail}"
                ) from exc
            except (httpx.HTTPError, KeyError, IndexError, ValueError, ValidationError) as exc:
                last_error = exc
        raise JudgeError(f"OpenRouter judge returned invalid structured output: {last_error}")
    finally:
        if close_client:
            await http.aclose()


async def _post_openrouter_judge(
    *,
    http: httpx.AsyncClient,
    settings: Settings,
    judge_model: str,
    input_text: str,
    output: str,
    reference: str | None,
    pass_threshold: float,
    use_response_format: bool,
    throttle: bool,
) -> httpx.Response:
    payload: dict[str, Any] = {
        "model": judge_model,
        "messages": [
            {"role": "system", "content": _system_rubric(pass_threshold)},
            {
                "role": "user",
                "content": _judge_prompt(input_text, output, reference),
            },
        ],
        "temperature": 0,
    }
    if use_response_format:
        payload["response_format"] = {"type": "json_object"}

    if throttle:
        await wait_for_provider_slot("openrouter", settings.openrouter_min_interval_seconds)

    return await post_with_retries(
        http,
        f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "X-Title": "AI Eval Lab",
        },
        json_payload=payload,
    )


def _is_response_format_unsupported(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    text = response.text.lower()
    return (
        ("response_format" in text and ("unsupported" in text or "not supported" in text))
        or ("must contain the word" in text and "json" in text)
    )


async def _evaluate_with_groq(
    *,
    input_text: str,
    output: str,
    reference: str | None,
    judge_model: str,
    pass_threshold: float,
    settings: Settings,
    client: httpx.AsyncClient | None,
) -> JudgeResult:
    if not settings.groq_api_key:
        raise JudgeError("GROQ_API_KEY is required for Groq judge calls.")

    close_client = client is None
    http = client or httpx.AsyncClient(timeout=settings.request_timeout_seconds)
    try:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = await _post_openai_compatible_judge(
                    http=http,
                    base_url=settings.groq_base_url,
                    api_key=settings.groq_api_key,
                    provider_name="Groq",
                    provider_key="groq",
                    min_interval_seconds=settings.groq_min_interval_seconds,
                    judge_model=_strip_provider_prefix(judge_model, "groq"),
                    input_text=input_text,
                    output=output,
                    reference=reference,
                    pass_threshold=pass_threshold,
                    use_response_format=True,
                    throttle=close_client,
                )
                if _is_response_format_unsupported(response):
                    response = await _post_openai_compatible_judge(
                        http=http,
                        base_url=settings.groq_base_url,
                        api_key=settings.groq_api_key,
                        provider_name="Groq",
                        provider_key="groq",
                        min_interval_seconds=settings.groq_min_interval_seconds,
                        judge_model=_strip_provider_prefix(judge_model, "groq"),
                        input_text=input_text,
                        output=output,
                        reference=reference,
                        pass_threshold=pass_threshold,
                        use_response_format=False,
                        throttle=close_client,
                    )
                response.raise_for_status()
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                data = _extract_json(content)
                result = JudgeResult.model_validate(data)
                passed = result.score >= pass_threshold
                return result.model_copy(update={"passed": passed})
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:500]
                if exc.response.status_code in RETRY_STATUSES:
                    raise JudgeError(
                        "Groq judge stayed unavailable after retries "
                        f"({exc.response.status_code}): {detail}"
                    ) from exc
                raise JudgeError(f"Groq judge error {exc.response.status_code}: {detail}") from exc
            except (httpx.HTTPError, KeyError, IndexError, ValueError, ValidationError) as exc:
                last_error = exc
        raise JudgeError(f"Groq judge returned invalid structured output: {last_error}")
    finally:
        if close_client:
            await http.aclose()


async def _post_openai_compatible_judge(
    *,
    http: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    provider_name: str,
    provider_key: str,
    min_interval_seconds: float,
    judge_model: str,
    input_text: str,
    output: str,
    reference: str | None,
    pass_threshold: float,
    use_response_format: bool,
    throttle: bool,
) -> httpx.Response:
    payload: dict[str, Any] = {
        "model": judge_model,
        "messages": [
            {"role": "system", "content": _system_rubric(pass_threshold)},
            {"role": "user", "content": _judge_prompt(input_text, output, reference)},
        ],
        "temperature": 0,
    }
    if use_response_format:
        payload["response_format"] = {"type": "json_object"}

    if throttle:
        await wait_for_provider_slot(provider_key, min_interval_seconds)

    return await post_with_retries(
        http,
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "AI Eval Lab",
        },
        json_payload=payload,
    )


async def _evaluate_with_gemini(
    *,
    input_text: str,
    output: str,
    reference: str | None,
    judge_model: str,
    pass_threshold: float,
    settings: Settings,
    client: httpx.AsyncClient | None,
) -> JudgeResult:
    if not settings.gemini_api_key:
        raise JudgeError("GEMINI_API_KEY is required for Gemini judge calls.")

    close_client = client is None
    http = client or httpx.AsyncClient(timeout=settings.request_timeout_seconds)
    model = _strip_provider_prefix(judge_model, "gemini")
    try:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                if close_client:
                    await wait_for_provider_slot("gemini", settings.gemini_min_interval_seconds)
                response = await post_with_retries(
                    http,
                    f"{settings.gemini_base_url.rstrip('/')}/models/{quote(model, safe='')}:generateContent",
                    headers={
                        "x-goog-api-key": settings.gemini_api_key,
                        "Content-Type": "application/json",
                    },
                    json_payload={
                        "contents": [
                            {
                                "parts": [
                                    {
                                        "text": (
                                            f"{_system_rubric(pass_threshold)}\n\n"
                                            f"{_judge_prompt(input_text, output, reference)}\n\n"
                                            "Return only valid JSON with score, passed, and reason."
                                        )
                                    }
                                ]
                            }
                        ],
                        "generationConfig": {
                            "temperature": 0,
                            "responseMimeType": "application/json",
                        },
                    },
                )
                response.raise_for_status()
                payload = response.json()
                candidate = payload.get("candidates", [{}])[0]
                content = candidate.get("content", {})
                text = _gemini_parts_to_text(content.get("parts"))
                data = _extract_json(text)
                result = JudgeResult.model_validate(data)
                passed = result.score >= pass_threshold
                return result.model_copy(update={"passed": passed})
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:500]
                if exc.response.status_code in RETRY_STATUSES:
                    raise JudgeError(
                        "Gemini judge stayed unavailable after retries "
                        f"({exc.response.status_code}): {detail}"
                    ) from exc
                raise JudgeError(f"Gemini judge error {exc.response.status_code}: {detail}") from exc
            except (httpx.HTTPError, KeyError, IndexError, ValueError, ValidationError) as exc:
                last_error = exc
        raise JudgeError(f"Gemini judge returned invalid structured output: {last_error}")
    finally:
        if close_client:
            await http.aclose()


async def _evaluate_with_anthropic(
    *,
    input_text: str,
    output: str,
    reference: str | None,
    judge_model: str,
    pass_threshold: float,
    settings: Settings,
    client: httpx.AsyncClient | None,
) -> JudgeResult:
    if not settings.anthropic_api_key:
        raise JudgeError("ANTHROPIC_API_KEY is required for Anthropic judge calls.")

    close_client = client is None
    http = client or httpx.AsyncClient(timeout=settings.request_timeout_seconds)
    tool = {
        "name": "record_evaluation",
        "description": "Record the answer quality evaluation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "score": {"type": "number", "minimum": 0, "maximum": 1},
                "passed": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["score", "passed", "reason"],
        },
    }
    try:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = await http.post(
                    f"{settings.anthropic_base_url.rstrip('/')}/messages",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": judge_model,
                        "max_tokens": 512,
                        "temperature": 0,
                        "system": _system_rubric(pass_threshold),
                        "tools": [tool],
                        "tool_choice": {"type": "tool", "name": "record_evaluation"},
                        "messages": [
                            {
                                "role": "user",
                                "content": _judge_prompt(input_text, output, reference),
                            }
                        ],
                    },
                )
                response.raise_for_status()
                payload = response.json()
                tool_input = _find_anthropic_tool_input(payload)
                result = JudgeResult.model_validate(tool_input)
                passed = result.score >= pass_threshold
                return result.model_copy(update={"passed": passed})
            except (httpx.HTTPError, KeyError, ValueError, ValidationError) as exc:
                last_error = exc
        raise JudgeError(f"Anthropic judge returned invalid structured output: {last_error}")
    finally:
        if close_client:
            await http.aclose()


def _find_anthropic_tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    for block in payload.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "record_evaluation":
            tool_input = block.get("input")
            if isinstance(tool_input, dict):
                return tool_input
    raise JudgeError("Anthropic response did not include record_evaluation tool output.")
