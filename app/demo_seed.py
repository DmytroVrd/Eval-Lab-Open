from __future__ import annotations

from sqlalchemy import delete, func, select

from app.db import AsyncSessionLocal
from app.models import Run, TestCase, TestSet

DEMO_SET_NAME = "AI Concepts Prompt Demo"
LEGACY_DEMO_SET_NAME = "AI Incident Response Live Demo"

GOOD_PROMPT = """You are a patient AI tutor.
Explain the concept for a beginner in 3-4 sentences.
Define key terms, use one simple analogy, and avoid unsupported claims.

{input}"""

BAD_PROMPT = """Say something impressive and positive.
Keep the answer generic.

{input}"""

DEMO_CASES = [
    {
        "input": "What is retrieval-augmented generation (RAG), and why is it useful?",
        "reference": None,
    },
    {
        "input": "Why can large language models hallucinate?",
        "reference": None,
    },
    {
        "input": "What is the difference between an embedding and a token?",
        "reference": None,
    },
]


async def seed_demo_data() -> None:
    async with AsyncSessionLocal() as session:
        existing = await session.scalar(select(TestSet).where(TestSet.name == DEMO_SET_NAME))
        if existing is not None:
            return

        legacy = await session.scalar(
            select(TestSet).where(TestSet.name == LEGACY_DEMO_SET_NAME)
        )
        if legacy is not None:
            run_count = await session.scalar(
                select(func.count(Run.id)).where(Run.test_set_id == legacy.id)
            )
            if not run_count:
                await session.execute(
                    delete(TestCase).where(TestCase.test_set_id == legacy.id)
                )
                legacy.name = DEMO_SET_NAME
                test_set = legacy
            else:
                test_set = TestSet(name=DEMO_SET_NAME)
                session.add(test_set)
                await session.flush()
        else:
            test_set = TestSet(name=DEMO_SET_NAME)
            session.add(test_set)
            await session.flush()

        for item in DEMO_CASES:
            case = TestCase(
                test_set_id=test_set.id,
                input=item["input"],
                reference=item["reference"],
            )
            session.add(case)

        await session.commit()
