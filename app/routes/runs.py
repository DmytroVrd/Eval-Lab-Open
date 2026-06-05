from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.eval_runner import run_eval
from app.models import Result, Run, RunStatus, TestCase, TestSet
from app.schemas import ResultRead, RunCreate, RunQueued, RunRead

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
