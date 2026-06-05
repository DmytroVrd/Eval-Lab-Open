from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db import AsyncSessionLocal
from app.eval_runner import run_eval
from app.judge import JudgeError, JudgeResult
from app.models import Result, Run, RunStatus, TestCase as DbTestCase, TestSet as DbTestSet


@pytest.mark.asyncio
async def test_eval_runner_records_failed_case_when_prompt_template_is_invalid() -> None:
    async with AsyncSessionLocal() as session:
        test_set = DbTestSet(name="Bad prompt")
        session.add(test_set)
        await session.flush()
        session.add(DbTestCase(test_set_id=test_set.id, input="Input", reference=None))
        await session.flush()
        run = Run(
            test_set_id=test_set.id,
            target_model="mock/target",
            judge_model="mock/judge",
            judge_provider="mock",
            prompt_template="Broken {unknown}",
            status=RunStatus.pending,
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    await run_eval(run_id)

    async with AsyncSessionLocal() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == RunStatus.done
        assert run.avg_score == 0
        result = (await session.execute(select(Result).where(Result.run_id == run_id))).scalar_one()
        assert result.score == 0
        assert "Unknown prompt placeholder" in (result.error or "")


@pytest.mark.asyncio
async def test_eval_runner_falls_back_to_mock_judge_when_provider_judge_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_target_model(**_: object) -> tuple[str, int]:
        return "FastAPI is an async Python web framework.", 12

    async def fake_evaluate_answer(**kwargs: object) -> JudgeResult:
        if kwargs["judge_provider"] == "mock":
            return JudgeResult(
                score=1.0,
                passed=True,
                reason="Mock judge compared lexical overlap with the reference answer.",
            )
        raise JudgeError("OpenRouter judge stayed unavailable after retries (429): rate limit")

    monkeypatch.setattr("app.eval_runner.call_target_model", fake_target_model)
    monkeypatch.setattr("app.eval_runner.evaluate_answer", fake_evaluate_answer)

    async with AsyncSessionLocal() as session:
        test_set = DbTestSet(name="Judge fallback")
        session.add(test_set)
        await session.flush()
        session.add(
            DbTestCase(
                test_set_id=test_set.id,
                input="What is FastAPI?",
                reference="Python web framework",
            )
        )
        await session.flush()
        run = Run(
            test_set_id=test_set.id,
            target_model="mock/target",
            judge_model="openrouter/free",
            judge_provider="openrouter",
            prompt_template="Answer: {input}",
            status=RunStatus.pending,
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    await run_eval(run_id, settings=Settings(fallback_to_mock_judge_on_error=True))

    async with AsyncSessionLocal() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == RunStatus.done
        assert run.avg_score == 1.0
        result = (await session.execute(select(Result).where(Result.run_id == run_id))).scalar_one()
        assert result.score == 1.0
        assert result.passed is True
        assert "Judge fallback used after provider error" in result.judge_reason
        assert "OpenRouter judge stayed unavailable" in (result.error or "")
