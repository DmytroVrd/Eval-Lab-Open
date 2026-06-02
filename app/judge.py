from __future__ import annotations

import json
import re
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import Settings, get_settings
from app.llm_http import RETRY_STATUSES, post_with_retries


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
        "Return the evaluation as structured data only."
    )


def _system_rubric(pass_threshold: float) -> str:
    return (
        "You are a strict evaluator of LLM answer quality. Judge factual "
        "correctness, relevance to the question, and completeness. If a reference "
        "answer is provided, compare against it. Return score from 0 to 1, "
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


async def evaluate_answer(
    *,
    input_text: str,
    output: str,
    reference: str | None,
    judge_model: str,
    judge_provider: Literal["openrouter", "anthropic", "mock"] | str = "openrouter",
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
                last_error = exc
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
    return "response_format" in text and ("unsupported" in text or "not supported" in text)


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
