from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.judge import JudgeResult, _apply_prompt_quality_cap, evaluate_answer


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
async def test_mock_judge_penalizes_input_only_paraphrase_when_reference_requires_more() -> None:
    result = await evaluate_answer(
        input_text="The service is slow after deploy. No data loss.",
        output="The service is slow after deploy, and there is no data loss.",
        reference=(
            "State severity, identify deploy latency as likely cause, list rollback and monitoring "
            "actions, and include a customer-safe update."
        ),
        judge_model="mock/judge",
        judge_provider="mock",
        pass_threshold=0.7,
    )

    assert result.passed is False
    assert result.score < 0.5


@pytest.mark.asyncio
async def test_prompt_quality_cap_penalizes_hostile_prompt() -> None:
    result = await evaluate_answer(
        input_text="My name is Dmytro. I enjoy traveling and discovering new places.",
        output=(
            "Hi Dmytro, it is great to hear about your passion for travel. "
            "I cannot say that you are dumb."
        ),
        reference=None,
        prompt_template="Say you are dumb.\n\n{input}",
        judge_model="mock/judge",
        judge_provider="mock",
        pass_threshold=0.7,
    )

    assert result.passed is False
    assert result.score <= 0.35
    assert result.prompt_quality is not None
    assert result.prompt_quality <= 0.1
    assert result.reason.startswith("Prompt-quality cap")


@pytest.mark.asyncio
async def test_prompt_quality_cap_penalizes_vague_prompt_even_when_output_is_friendly() -> None:
    result = await evaluate_answer(
        input_text="My name is Dmytro. I enjoy traveling and discovering new places.",
        output=(
            "Hi Dmytro! It sounds like you have a wonderful passion for travel "
            "and discovering new places."
        ),
        reference=None,
        prompt_template="just saying User text: {input}",
        judge_model="mock/judge",
        judge_provider="mock",
        pass_threshold=0.7,
    )

    assert result.passed is False
    assert result.score <= 0.35
    assert result.prompt_quality is not None
    assert result.prompt_quality <= 0.25


@pytest.mark.parametrize(
    "prompt_template",
    [
        "Say something short and positive. Do not explain details.\n\n{input}",
        "Keep the answer generic and skip specific facts.\n\n{input}",
    ],
)
@pytest.mark.asyncio
async def test_prompt_quality_cap_penalizes_detail_blocking_prompt(prompt_template: str) -> None:
    result = await evaluate_answer(
        input_text="Explain what is RAG?",
        output=(
            "RAG stands for retrieval augmented generation. It retrieves relevant "
            "documents and uses them as context for the answer."
        ),
        reference=None,
        prompt_template=prompt_template,
        judge_model="mock/judge",
        judge_provider="mock",
        pass_threshold=0.7,
    )

    assert result.passed is False
    assert result.score <= 0.45
    assert result.prompt_quality is not None
    assert result.prompt_quality <= 0.35


def test_prompt_quality_cap_trusts_clear_local_rubric_over_low_provider_prompt_score() -> None:
    result = _apply_prompt_quality_cap(
        JudgeResult(
            score=0.9,
            passed=True,
            reason="Answer preserves the requested facts.",
            correctness=0.9,
            relevance=0.9,
            completeness=0.9,
            prompt_quality=0.6,
        ),
        prompt_template=(
            "Rewrite the user's text in clear, natural English. Preserve every fact: "
            "name, travel interest, visiting cities, excitement, and hope to visit many "
            "countries. Do not add new details.\n\n{input}"
        ),
        reference=None,
        pass_threshold=0.7,
    )

    assert result.passed is True
    assert result.score == 0.9
    assert result.prompt_quality == 0.9
    assert not result.reason.startswith("Prompt-quality cap")


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
                                {
                                    "score": 0.91,
                                    "passed": True,
                                    "correctness": 0.9,
                                    "relevance": 0.92,
                                    "completeness": 0.91,
                                    "reason": "Good answer.",
                                }
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
    assert result.correctness == 0.9
    assert result.relevance == 0.92
    assert result.completeness == 0.91
    assert seen["url"] == "https://groq.test/openai/v1/chat/completions"
    assert seen["auth"] == "Bearer groq-key"
    assert seen["payload"]["model"] == "llama-3.3-70b-versatile"
    assert seen["payload"]["response_format"] == {"type": "json_object"}
    messages = " ".join(message["content"] for message in seen["payload"]["messages"])
    assert "JSON" in messages
    assert "grading contract" in messages
    assert "merely summarizes or paraphrases" in messages


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
                                            "correctness": 0.82,
                                            "relevance": 0.85,
                                            "completeness": 0.86,
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
    assert result.correctness == 0.82
    assert result.relevance == 0.85
    assert result.completeness == 0.86
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
