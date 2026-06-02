from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Integer, cast, func, select

from app.config import Settings, get_settings
from app.db import AsyncSessionLocal
from app.judge import JudgeError, evaluate_answer
from app.models import Result, Run, RunStatus, TestCase
from app.targets import LLMCallError, call_target_model


@dataclass(frozen=True)
class CaseSnapshot:
    id: int
    input: str
    reference: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _render_prompt(template: str, input_text: str) -> str:
    try:
        return template.format(input=input_text)
    except KeyError as exc:
        missing = exc.args[0]
        raise ValueError(f"Unknown prompt placeholder: {{{missing}}}") from exc


async def run_eval(run_id: int, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    try:
        async with AsyncSessionLocal() as session:
            run = await session.get(Run, run_id)
            if run is None:
                return
            run.status = RunStatus.running
            run.error = None
            await session.commit()

            cases_result = await session.execute(
                select(TestCase)
                .where(TestCase.test_set_id == run.test_set_id)
                .order_by(TestCase.id)
            )
            cases = [
                CaseSnapshot(id=case.id, input=case.input, reference=case.reference)
                for case in cases_result.scalars().all()
            ]
            prompt_template = run.prompt_template
            target_model = run.target_model
            judge_model = run.judge_model
            judge_provider = run.judge_provider
            temperature = run.temperature
            max_cases = run.max_cases

            if max_cases is not None:
                cases = cases[:max_cases]

        if not cases:
            await _finalize_run(run_id, status=RunStatus.done, avg_score=0.0, pass_rate=0.0)
            return

        semaphore = asyncio.Semaphore(settings.max_concurrency)

        async def guarded(case: CaseSnapshot) -> None:
            async with semaphore:
                await _process_case(
                    run_id=run_id,
                    case=case,
                    prompt_template=prompt_template,
                    target_model=target_model,
                    judge_model=judge_model,
                    judge_provider=judge_provider,
                    temperature=temperature,
                    settings=settings,
                )

        await asyncio.gather(*(guarded(case) for case in cases))
        await _aggregate_run(run_id)
    except Exception as exc:  # pragma: no cover - defensive background boundary
        await _finalize_run(run_id, status=RunStatus.failed, error=str(exc))


async def _process_case(
    *,
    run_id: int,
    case: CaseSnapshot,
    prompt_template: str,
    target_model: str,
    judge_model: str,
    judge_provider: str,
    temperature: float | None,
    settings: Settings,
) -> None:
    output = ""
    score = 0.0
    passed = False
    reason = ""
    latency_ms = 0
    error: str | None = None

    try:
        prompt = _render_prompt(prompt_template, case.input)
        output, latency_ms = await call_target_model(
            prompt=prompt,
            model=target_model,
            temperature=temperature,
            settings=settings,
        )
    except (LLMCallError, ValueError) as exc:
        error = str(exc)
        reason = "Target model call failed; the case was scored as 0."
    except Exception as exc:  # pragma: no cover - defensive per-case boundary
        error = f"Unexpected target error: {exc}"
        reason = "Unexpected target error; the case was scored as 0."

    if output and not error:
        try:
            judge_result = await evaluate_answer(
                input_text=case.input,
                output=output,
                reference=case.reference,
                judge_model=judge_model,
                judge_provider=judge_provider,
                pass_threshold=settings.pass_threshold,
                settings=settings,
            )
            score = judge_result.score
            passed = judge_result.passed
            reason = judge_result.reason
        except JudgeError as exc:
            error = str(exc)
            reason = "Judge call failed; the case was scored as 0."
        except Exception as exc:  # pragma: no cover - defensive per-case boundary
            error = f"Unexpected judge error: {exc}"
            reason = "Unexpected judge error; the case was scored as 0."

    async with AsyncSessionLocal() as session:
        session.add(
            Result(
                run_id=run_id,
                test_case_id=case.id,
                output=output,
                score=score,
                passed=passed,
                judge_reason=reason,
                latency_ms=latency_ms,
                error=error,
            )
        )
        await session.commit()


async def _aggregate_run(run_id: int) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                func.count(Result.id),
                func.coalesce(func.avg(Result.score), 0.0),
                func.coalesce(func.avg(cast(Result.passed, Integer)), 0.0),
            ).where(Result.run_id == run_id)
        )
        count, avg_score, pass_rate = result.one()
        await _finalize_run(
            run_id,
            status=RunStatus.done,
            avg_score=float(avg_score or 0.0) if count else 0.0,
            pass_rate=float(pass_rate or 0.0) if count else 0.0,
        )


async def _finalize_run(
    run_id: int,
    *,
    status: RunStatus,
    avg_score: float | None = None,
    pass_rate: float | None = None,
    error: str | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        run.status = status
        run.avg_score = avg_score
        run.pass_rate = pass_rate
        run.error = error
        run.finished_at = _now()
        await session.commit()
