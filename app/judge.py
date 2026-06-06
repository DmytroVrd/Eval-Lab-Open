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
    correctness: float | None = Field(default=None, ge=0.0, le=1.0)
    relevance: float | None = Field(default=None, ge=0.0, le=1.0)
    completeness: float | None = Field(default=None, ge=0.0, le=1.0)
    prompt_quality: float | None = Field(default=None, ge=0.0, le=1.0)


def _token_set(value: str) -> set[str]:
    return set(re.findall(r"[\w']+", value.lower()))


def _has_detail_blocking_instruction(prompt: str) -> bool:
    prompt = re.sub(
        r"\b(do not|don't|without)\s+(add|invent|create|include)\s+new\s+details\b",
        " ",
        prompt,
    )
    prompt = re.sub(r"\bno\s+new\s+details\b", " ", prompt)
    negation = r"(avoid|hide|skip|omit|remove|ignore|exclude|without|no|do not|don't)"
    detail = (
        r"(details?|specifics?|technical|explanations?|explain|reasoning|steps?|"
        r"evidence|sources?|citations?|facts?)"
    )
    if re.search(rf"\b{negation}\b(?:\W+\w+){{0,4}}\W+\b{detail}\b", prompt):
        return True
    if re.search(r"\b(keep|make)\b(?:\W+\w+){0,3}\W+\b(vague|generic|broad)\b", prompt):
        return True
    return False


def _prompt_quality_score(prompt_template: str | None, reference: str | None) -> tuple[float, str]:
    if not prompt_template:
        return 0.4, "prompt template was not provided"

    prompt = prompt_template.lower()
    prompt_without_input = prompt.replace("{input}", " ")
    tokens = re.findall(r"[a-zA-Z']+", prompt_without_input)
    meaningful_tokens = [
        token
        for token in tokens
        if token
        not in {
            "user",
            "text",
            "input",
            "the",
            "a",
            "an",
            "and",
            "me",
            "you",
            "are",
            "is",
            "to",
            "for",
            "of",
            "in",
            "it",
            "this",
            "that",
            "just",
            "saying",
        }
    ]
    task_terms = {
        "answer",
        "rewrite",
        "translate",
        "summarize",
        "classify",
        "extract",
        "compare",
        "explain",
        "analyze",
        "preserve",
        "facts",
        "meaning",
        "format",
        "steps",
        "criteria",
        "concise",
        "clear",
        "natural",
    }
    constraint_terms = {
        "do not",
        "don't",
        "preserve",
        "only",
        "exactly",
        "required",
        "include",
        "without",
        "no new",
        "facts",
        "meaning",
    }

    if re.search(r"\b(dumb|stupid|idiot|moron|shut up|insult|demean|mock|not smart)\b", prompt):
        return 0.1, "prompt is hostile or insulting"
    if _has_detail_blocking_instruction(prompt):
        return 0.35, "prompt blocks details that the task may need"
    if reference and (
        re.search(r"\b(do not|don't)\s+mention\b", prompt)
    ):
        return 0.3, "prompt hides details that may be required by the task"
    if len(meaningful_tokens) <= 1:
        return 0.15, "prompt has almost no task instruction"
    if len(meaningful_tokens) <= 3 and not (set(meaningful_tokens) & task_terms):
        return 0.25, "prompt is too vague to define the task"
    if len(meaningful_tokens) <= 6 and not (set(meaningful_tokens) & task_terms):
        return 0.35, "prompt is vague and lacks clear success criteria"

    task_overlap = len(set(meaningful_tokens) & task_terms)
    has_constraint = any(term in prompt for term in constraint_terms)
    if task_overlap >= 2 and has_constraint:
        return 0.9, "prompt defines a clear task and constraints"
    if task_overlap >= 1:
        return 0.7, "prompt defines a task but has limited constraints"
    return 0.55, "prompt is understandable but underspecified"


def _mock_judge(
    *,
    input_text: str,
    output: str,
    reference: str | None,
    prompt_template: str | None,
    pass_threshold: float,
) -> JudgeResult:
    if not output.strip():
        return JudgeResult(score=0.0, passed=False, reason="No answer was produced.")

    if reference:
        input_tokens = _token_set(input_text)
        reference_tokens = _token_set(reference)
        output_tokens = _token_set(output)
        if not reference_tokens:
            score = 0.5
        else:
            score = len(reference_tokens & output_tokens) / len(reference_tokens)
        reference_only_tokens = reference_tokens - input_tokens
        if reference_only_tokens and output_tokens:
            reference_only_score = len(reference_only_tokens & output_tokens) / len(reference_only_tokens)
            input_copy_ratio = len(output_tokens & input_tokens) / len(output_tokens)
            if input_copy_ratio >= 0.65 and reference_only_score < 0.5:
                score = min(score, max(0.15, reference_only_score * 0.6 + 0.15))
        score = max(0.0, min(1.0, score))
        passed = score >= pass_threshold
        result = JudgeResult(
            score=round(score, 3),
            passed=passed,
            reason="Mock judge compared reference coverage and penalized input-only paraphrases.",
            correctness=round(score, 3),
            relevance=round(0.9 if output_tokens else 0.0, 3),
            completeness=round(score, 3),
            prompt_quality=_prompt_quality_score(prompt_template, reference)[0],
        )
        return _apply_prompt_quality_cap(result, prompt_template, reference, pass_threshold)

    score = 0.75 if len(output.strip()) >= min(40, max(10, len(input_text) // 2)) else 0.45
    result = JudgeResult(
        score=score,
        passed=score >= pass_threshold,
        reason="Mock judge used answer length and non-empty relevance heuristics.",
        correctness=score,
        relevance=score,
        completeness=score,
        prompt_quality=_prompt_quality_score(prompt_template, reference)[0],
    )
    return _apply_prompt_quality_cap(result, prompt_template, reference, pass_threshold)


def _judge_prompt(
    input_text: str,
    output: str,
    reference: str | None,
    prompt_template: str | None,
) -> str:
    reference_text = reference or "(no reference answer provided)"
    prompt_text = prompt_template or "(prompt template not provided)"
    return (
        "Prompt template used to produce the answer:\n"
        f"{prompt_text}\n\n"
        "Question/input:\n"
        f"{input_text}\n\n"
        "Model answer:\n"
        f"{output}\n\n"
        "Required answer / grading reference:\n"
        f"{reference_text}\n\n"
        "If a grading reference is provided, treat it as the required behavior and "
        "required facts. Do not give a high score to an answer that only paraphrases "
        "the input while omitting the reference's required diagnosis, policy, actions, "
        "format, or safety constraints.\n\n"
        "Also judge whether the prompt template is fit for the task. If the prompt is "
        "hostile, insulting, unrelated, or tells the model to hide/avoid details that "
        "the task requires, the run should receive a low score even if the model tries "
        "to recover with a polite generic answer. Grade prompt_quality independently "
        "from the final answer: a strong prompt gives a clear task, useful constraints, "
        "and success criteria; a weak prompt is vague, generic, conflicting, or blocks "
        "facts/details/sources needed by the input task.\n\n"
        "Return only a valid JSON object like "
        '{"score": 0.8, "passed": true, "correctness": 0.8, '
        '"relevance": 0.9, "completeness": 0.7, "prompt_quality": 0.6, '
        '"reason": "short reason"}.'
    )


def _system_rubric(pass_threshold: float) -> str:
    return (
        "You are a strict evaluator of LLM answer quality. Judge factual "
        "correctness, relevance to the question, and completeness. If a reference "
        "answer is provided, it is the grading contract: required facts, required "
        "behavior, and required constraints must appear in the model answer. Penalize "
        "answers that ignore explicit instructions, omit required details, miss the "
        "requested format, or add unsupported facts. A fluent answer that merely "
        "summarizes or paraphrases the input but misses the reference's required "
        "diagnosis, policy, actions, customer-safe wording, or safety constraints "
        "must receive low completeness and usually a low overall score. Do not reward "
        "tone or style when required content is missing. The prompt template is part "
        "of what is being evaluated: hostile, insulting, unrelated, or intentionally "
        "detail-hiding prompts should be penalized as prompt failures. If a model "
        "refuses an insulting prompt and gives a polite generic answer, do not score "
        "it highly unless it still clearly fulfills the actual task and reference. "
        "Use this prompt_quality scale: 0.9-1.0 clear task plus useful constraints; "
        "0.7-0.8 clear but underspecified; 0.4-0.6 vague, generic, or missing success "
        "criteria; 0.0-0.3 hostile, unrelated, contradictory, or asks to hide facts, "
        "sources, steps, or explanations needed for the task. "
        "Return only valid JSON with score, passed, correctness, relevance, "
        "completeness, prompt_quality, and reason. prompt_quality evaluates the "
        "prompt template itself: task clarity, constraints, specificity, and whether "
        "it is aligned with the expected behavior. Vague prompts such as 'just saying' "
        "or 'no words' should have low prompt_quality even if the model guessed a "
        "reasonable answer. Each numeric score is from 0 to 1. "
        f"passed = score >= {pass_threshold}."
    )


def _apply_prompt_quality_cap(
    result: JudgeResult,
    prompt_template: str | None,
    reference: str | None,
    pass_threshold: float,
) -> JudgeResult:
    if not prompt_template:
        return result

    heuristic_quality, quality_reason = _prompt_quality_score(prompt_template, reference)
    if result.prompt_quality is None:
        prompt_quality = heuristic_quality
    elif heuristic_quality < 0.7:
        prompt_quality = min(result.prompt_quality, heuristic_quality)
    else:
        # Provider judges are good at grading the produced answer, but they can be
        # inconsistent at scoring the prompt template itself. Trust the local
        # prompt rubric once it sees a clear task plus constraints.
        prompt_quality = max(result.prompt_quality, heuristic_quality)

    updates: dict[str, Any] = {"prompt_quality": round(prompt_quality, 3)}
    if heuristic_quality >= 0.7:
        return result.model_copy(update=updates)

    cap = min(0.65, round(prompt_quality + 0.1, 3))
    if result.score <= cap:
        return result.model_copy(update=updates)

    score = min(result.score, cap)
    updates.update(
        {
            "score": score,
            "passed": score >= pass_threshold,
            "reason": (
                f"Prompt-quality cap: {quality_reason}. "
                f"Prompt quality {prompt_quality:.2f} capped final score. "
                f"Original judge: {result.reason}"
            ),
        }
    )
    return result.model_copy(
        update=updates
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
    prompt_template: str | None = None,
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
            prompt_template=prompt_template,
            pass_threshold=threshold,
        )

    if judge_provider == "anthropic":
        if settings.local_mock_without_keys and not settings.anthropic_api_key:
            return _mock_judge(
                input_text=input_text,
                output=output,
                reference=reference,
                prompt_template=prompt_template,
                pass_threshold=threshold,
            )
        return await _evaluate_with_anthropic(
            input_text=input_text,
            output=output,
            reference=reference,
            prompt_template=prompt_template,
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
                prompt_template=prompt_template,
                pass_threshold=threshold,
            )
        return await _evaluate_with_gemini(
            input_text=input_text,
            output=output,
            reference=reference,
            prompt_template=prompt_template,
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
                prompt_template=prompt_template,
                pass_threshold=threshold,
            )
        return await _evaluate_with_groq(
            input_text=input_text,
            output=output,
            reference=reference,
            prompt_template=prompt_template,
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
            prompt_template=prompt_template,
            pass_threshold=threshold,
        )
    return await _evaluate_with_openrouter(
        input_text=input_text,
        output=output,
        reference=reference,
        prompt_template=prompt_template,
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
    prompt_template: str | None,
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
                    prompt_template=prompt_template,
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
                        prompt_template=prompt_template,
                        pass_threshold=pass_threshold,
                        use_response_format=False,
                        throttle=close_client,
                    )
                response.raise_for_status()
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                data = _extract_json(content)
                result = JudgeResult.model_validate(data)
                result = _apply_prompt_quality_cap(result, prompt_template, reference, pass_threshold)
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
    prompt_template: str | None,
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
                "content": _judge_prompt(input_text, output, reference, prompt_template),
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
    prompt_template: str | None,
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
                    prompt_template=prompt_template,
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
                        prompt_template=prompt_template,
                        pass_threshold=pass_threshold,
                        use_response_format=False,
                        throttle=close_client,
                    )
                response.raise_for_status()
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                data = _extract_json(content)
                result = JudgeResult.model_validate(data)
                result = _apply_prompt_quality_cap(result, prompt_template, reference, pass_threshold)
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
    prompt_template: str | None,
    pass_threshold: float,
    use_response_format: bool,
    throttle: bool,
) -> httpx.Response:
    payload: dict[str, Any] = {
        "model": judge_model,
        "messages": [
            {"role": "system", "content": _system_rubric(pass_threshold)},
            {"role": "user", "content": _judge_prompt(input_text, output, reference, prompt_template)},
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
    prompt_template: str | None,
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
                                            f"{_judge_prompt(input_text, output, reference, prompt_template)}\n\n"
                                            "Return only valid JSON with score, passed, correctness, "
                                            "relevance, completeness, prompt_quality, and reason."
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
                    before_attempt=(
                        lambda: wait_for_provider_slot("gemini", settings.gemini_min_interval_seconds)
                    )
                    if close_client
                    else None,
                )
                response.raise_for_status()
                payload = response.json()
                candidate = payload.get("candidates", [{}])[0]
                content = candidate.get("content", {})
                text = _gemini_parts_to_text(content.get("parts"))
                data = _extract_json(text)
                result = JudgeResult.model_validate(data)
                result = _apply_prompt_quality_cap(result, prompt_template, reference, pass_threshold)
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
    prompt_template: str | None,
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
                "correctness": {"type": "number", "minimum": 0, "maximum": 1},
                "relevance": {"type": "number", "minimum": 0, "maximum": 1},
                "completeness": {"type": "number", "minimum": 0, "maximum": 1},
                "prompt_quality": {"type": "number", "minimum": 0, "maximum": 1},
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
                                "content": _judge_prompt(input_text, output, reference, prompt_template),
                            }
                        ],
                    },
                )
                response.raise_for_status()
                payload = response.json()
                tool_input = _find_anthropic_tool_input(payload)
                result = JudgeResult.model_validate(tool_input)
                result = _apply_prompt_quality_cap(result, prompt_template, reference, pass_threshold)
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
