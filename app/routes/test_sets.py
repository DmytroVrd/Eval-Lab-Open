from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.models import Result, Run, RunStatus, TestCase, TestSet
from app.schemas import TestCaseCreate, TestCaseRead, TestSetCreate, TestSetRead, TestSetSummary

router = APIRouter(prefix="/test-sets", tags=["test sets"])


@router.post("", response_model=TestSetRead, status_code=status.HTTP_201_CREATED)
async def create_test_set(
    payload: TestSetCreate,
    session: AsyncSession = Depends(get_session),
) -> TestSet:
    test_set = TestSet(name=payload.name.strip())
    session.add(test_set)
    await session.commit()
    await session.refresh(test_set, attribute_names=["cases"])
    return test_set


@router.get("", response_model=list[TestSetSummary])
async def list_test_sets(session: AsyncSession = Depends(get_session)) -> list[TestSetSummary]:
    result = await session.execute(
        select(TestSet, func.count(TestCase.id).label("case_count"))
        .outerjoin(TestCase)
        .group_by(TestSet.id)
        .order_by(TestSet.created_at.desc(), TestSet.id.desc())
    )
    return [
        TestSetSummary(
            id=test_set.id,
            name=test_set.name,
            created_at=test_set.created_at,
            case_count=case_count,
        )
        for test_set, case_count in result.all()
    ]


@router.get("/{test_set_id}", response_model=TestSetRead)
async def read_test_set(
    test_set_id: int,
    session: AsyncSession = Depends(get_session),
) -> TestSet:
    test_set = await _get_test_set(session, test_set_id)
    return test_set


@router.delete("/{test_set_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_test_set(
    test_set_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _get_test_set(session, test_set_id)
    await _ensure_no_active_runs(session, test_set_id)
    await _delete_set_data(session, test_set_id)
    await session.execute(delete(TestSet).where(TestSet.id == test_set_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{test_set_id}/cases", response_model=TestCaseRead, status_code=status.HTTP_201_CREATED)
async def create_case(
    test_set_id: int,
    payload: TestCaseCreate,
    session: AsyncSession = Depends(get_session),
) -> TestCase:
    await _get_test_set(session, test_set_id)
    case = TestCase(
        test_set_id=test_set_id,
        input=payload.input.strip(),
        reference=payload.reference.strip() if payload.reference else None,
    )
    session.add(case)
    await session.commit()
    await session.refresh(case)
    return case


@router.get("/{test_set_id}/cases", response_model=list[TestCaseRead])
async def list_cases(
    test_set_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[TestCase]:
    await _get_test_set(session, test_set_id)
    rows = await session.execute(
        select(TestCase)
        .where(TestCase.test_set_id == test_set_id)
        .order_by(TestCase.id)
    )
    return list(rows.scalars().all())


@router.delete("/{test_set_id}/cases", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def clear_cases(
    test_set_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _get_test_set(session, test_set_id)
    await _ensure_no_active_runs(session, test_set_id)
    await _delete_set_data(session, test_set_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{test_set_id}/cases/bulk",
    response_model=list[TestCaseRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_cases_bulk(
    test_set_id: int,
    payload: list[TestCaseCreate],
    session: AsyncSession = Depends(get_session),
) -> list[TestCase]:
    await _get_test_set(session, test_set_id)
    if not payload:
        raise HTTPException(status_code=400, detail="Bulk payload must contain at least one case.")

    cases = [
        TestCase(
            test_set_id=test_set_id,
            input=item.input.strip(),
            reference=item.reference.strip() if item.reference else None,
        )
        for item in payload
    ]
    session.add_all(cases)
    await session.commit()
    for case in cases:
        await session.refresh(case)
    return cases


async def _ensure_no_active_runs(session: AsyncSession, test_set_id: int) -> None:
    active_run = await session.scalar(
        select(Run.id)
        .where(Run.test_set_id == test_set_id)
        .where(Run.status.in_([RunStatus.pending, RunStatus.running]))
        .limit(1)
    )
    if active_run is not None:
        raise HTTPException(
            status_code=409,
            detail="Wait for the active run to finish before deleting this set.",
        )


async def _delete_set_data(session: AsyncSession, test_set_id: int) -> None:
    run_ids = select(Run.id).where(Run.test_set_id == test_set_id)
    case_ids = select(TestCase.id).where(TestCase.test_set_id == test_set_id)
    await session.execute(
        delete(Result).where(
            or_(
                Result.run_id.in_(run_ids),
                Result.test_case_id.in_(case_ids),
            )
        )
    )
    await session.execute(delete(Run).where(Run.test_set_id == test_set_id))
    await session.execute(delete(TestCase).where(TestCase.test_set_id == test_set_id))


async def _get_test_set(session: AsyncSession, test_set_id: int) -> TestSet:
    result = await session.execute(
        select(TestSet)
        .where(TestSet.id == test_set_id)
        .options(selectinload(TestSet.cases))
    )
    test_set = result.scalar_one_or_none()
    if test_set is None:
        raise HTTPException(status_code=404, detail="Test set not found.")
    return test_set
