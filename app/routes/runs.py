from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.eval_runner import run_eval
from app.models import Result, Run, RunStatus, TestCase, TestSet
from app.schemas import (
    ResultRead,
    RunCompareMeta,
    RunCompareRead,
    RunCompareRow,
    RunCreate,
    RunQueued,
    RunRead,
)

router = APIRouter(tags=["runs"])


@router.post("/runs", response_model=RunQueued, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: RunCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> RunQueued:
    settings = get_settings()
    test_set = await session.get(TestSet, payload.test_set_id)
    if test_set is None:
        raise HTTPException(status_code=404, detail="Test set not found.")

    case_count = await session.scalar(
        select(func.count(TestCase.id)).where(TestCase.test_set_id == payload.test_set_id)
    )
    if not case_count:
        raise HTTPException(status_code=400, detail="Add at least one test case before running evals.")

    judge_model = payload.judge_model or settings.default_judge_model
    judge_provider = payload.judge_provider or _infer_judge_provider(
        judge_model,
        settings.default_judge_provider,
    )
    if judge_model.startswith("mock/"):
        judge_provider = "mock"

    run = Run(
        test_set_id=payload.test_set_id,
        target_model=payload.target_model or settings.default_target_model,
        judge_model=judge_model,
        judge_provider=judge_provider,
        prompt_template=payload.prompt_template or "Answer the question clearly:\n\n{input}",
        temperature=payload.temperature,
        max_cases=payload.max_cases,
        status=RunStatus.pending,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    background_tasks.add_task(run_eval, run.id)
    return RunQueued(run_id=run.id)


def _infer_judge_provider(judge_model: str, default_provider: str) -> str:
    if judge_model.startswith("mock/"):
        return "mock"
    if judge_model.startswith("gemini/"):
        return "gemini"
    if judge_model.startswith("groq/"):
        return "groq"
    return default_provider


@router.get("/runs/compare", response_model=RunCompareRead)
async def compare_runs(
    a: int,
    b: int,
    session: AsyncSession = Depends(get_session),
) -> RunCompareRead:
    run_a = await _get_run(session, a)
    run_b = await _get_run(session, b)
    if run_a.test_set_id != run_b.test_set_id:
        raise HTTPException(status_code=400, detail="Runs must belong to the same test set.")

    rows = await session.execute(
        select(TestCase, Result)
        .join(Result, Result.test_case_id == TestCase.id)
        .where(Result.run_id.in_([a, b]))
        .order_by(TestCase.id)
    )

    by_case: dict[int, tuple[TestCase, dict[int, Result]]] = {}
    for case, result in rows.all():
        _, results_by_run = by_case.setdefault(case.id, (case, {}))
        results_by_run[result.run_id] = result

    compare_rows: list[RunCompareRow] = []
    for case_id, (case, results_by_run) in by_case.items():
        result_a = results_by_run.get(a)
        result_b = results_by_run.get(b)
        compare_rows.append(
            RunCompareRow(
                test_case_id=case_id,
                input=case.input,
                reference=case.reference,
                output_a=result_a.output if result_a else "",
                output_b=result_b.output if result_b else "",
                score_a=result_a.score if result_a else None,
                score_b=result_b.score if result_b else None,
                delta_score=_delta(result_a.score if result_a else None, result_b.score if result_b else None),
                correctness_a=result_a.correctness_score if result_a else None,
                correctness_b=result_b.correctness_score if result_b else None,
                delta_correctness=_delta(
                    result_a.correctness_score if result_a else None,
                    result_b.correctness_score if result_b else None,
                ),
                relevance_a=result_a.relevance_score if result_a else None,
                relevance_b=result_b.relevance_score if result_b else None,
                delta_relevance=_delta(
                    result_a.relevance_score if result_a else None,
                    result_b.relevance_score if result_b else None,
                ),
                completeness_a=result_a.completeness_score if result_a else None,
                completeness_b=result_b.completeness_score if result_b else None,
                delta_completeness=_delta(
                    result_a.completeness_score if result_a else None,
                    result_b.completeness_score if result_b else None,
                ),
                prompt_quality_a=result_a.prompt_quality_score if result_a else None,
                prompt_quality_b=result_b.prompt_quality_score if result_b else None,
                delta_prompt_quality=_delta(
                    result_a.prompt_quality_score if result_a else None,
                    result_b.prompt_quality_score if result_b else None,
                ),
                passed_a=result_a.passed if result_a else None,
                passed_b=result_b.passed if result_b else None,
                reason_a=result_a.judge_reason if result_a else None,
                reason_b=result_b.judge_reason if result_b else None,
                error_a=result_a.error if result_a else None,
                error_b=result_b.error if result_b else None,
            )
        )

    return RunCompareRead(
        run_a=_compare_meta(run_a),
        run_b=_compare_meta(run_b),
        avg_delta_score=_delta(run_a.avg_score, run_b.avg_score),
        rows=compare_rows,
    )


@router.get("/runs/{run_id}", response_model=RunRead)
async def read_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> RunRead:
    run = await _get_run(session, run_id)
    return await _run_to_read(session, run)


@router.get("/runs/{run_id}/results", response_model=list[ResultRead])
async def list_run_results(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[ResultRead]:
    await _get_run(session, run_id)
    rows = await session.execute(
        select(Result, TestCase)
        .join(TestCase, TestCase.id == Result.test_case_id)
        .where(Result.run_id == run_id)
        .order_by(TestCase.id)
    )
    return [
        ResultRead(
            id=result.id,
            run_id=result.run_id,
            test_case_id=result.test_case_id,
            input=case.input,
            reference=case.reference,
            output=result.output,
            score=result.score,
            correctness_score=result.correctness_score,
            relevance_score=result.relevance_score,
            completeness_score=result.completeness_score,
            prompt_quality_score=result.prompt_quality_score,
            passed=result.passed,
            judge_reason=result.judge_reason,
            latency_ms=result.latency_ms,
            error=result.error,
        )
        for result, case in rows.all()
    ]


@router.get("/test-sets/{test_set_id}/runs", response_model=list[RunRead])
async def list_runs_for_test_set(
    test_set_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[RunRead]:
    test_set = await session.get(TestSet, test_set_id)
    if test_set is None:
        raise HTTPException(status_code=404, detail="Test set not found.")

    rows = await session.execute(
        select(Run)
        .where(Run.test_set_id == test_set_id)
        .order_by(Run.created_at.desc(), Run.id.desc())
    )
    return [await _run_to_read(session, run) for run in rows.scalars().all()]


async def _get_run(session: AsyncSession, run_id: int) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(right - left, 3)


def _compare_meta(run: Run) -> RunCompareMeta:
    return RunCompareMeta(
        id=run.id,
        target_model=run.target_model,
        judge_model=run.judge_model,
        judge_provider=run.judge_provider,
        prompt_template=run.prompt_template,
        avg_score=run.avg_score,
        pass_rate=run.pass_rate,
        created_at=run.created_at,
    )


async def _run_to_read(session: AsyncSession, run: Run) -> RunRead:
    total_count = await session.scalar(
        select(func.count(TestCase.id)).where(TestCase.test_set_id == run.test_set_id)
    )
    if run.max_cases is not None:
        total_count = min(total_count or 0, run.max_cases)
    done_count = await session.scalar(
        select(func.count(Result.id)).where(Result.run_id == run.id)
    )
    return RunRead(
        id=run.id,
        test_set_id=run.test_set_id,
        target_model=run.target_model,
        judge_model=run.judge_model,
        judge_provider=run.judge_provider,
        prompt_template=run.prompt_template,
        temperature=run.temperature,
        max_cases=run.max_cases,
        status=run.status,
        avg_score=run.avg_score,
        pass_rate=run.pass_rate,
        error=run.error,
        created_at=run.created_at,
        finished_at=run.finished_at,
        done_count=done_count or 0,
        total_count=total_count or 0,
        model=run.target_model,
        score=run.avg_score,
        completed=done_count or 0,
        total=total_count or 0,
    )
