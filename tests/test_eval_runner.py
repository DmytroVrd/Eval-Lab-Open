from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.eval_runner import run_eval
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
