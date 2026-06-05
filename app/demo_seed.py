from __future__ import annotations

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models import TestCase, TestSet

DEMO_SET_NAME = "AI Incident Response Live Demo"

GOOD_PROMPT = """You are an incident-support assistant for an AI product.
Use only the provided incident note. Return:
1. severity
2. likely cause
3. immediate next actions
4. customer-safe update

Be specific, concise, and do not invent missing facts.

Incident note:
{input}"""

BAD_PROMPT = """Write one cheerful, reassuring sentence.
Do not mention severity, root cause, metrics, policy rules, customer risk, or next actions.

{input}"""

DEMO_CASES = [
    {
        "input": (
            "EU customers report 40% slower AI search responses after the 09:10 UTC deploy. "
            "Logs show vector DB p95 latency rose from 220ms to 2.8s. No data loss observed."
        ),
        "reference": (
            "Severity should be elevated but not data-loss critical. Likely cause is vector DB "
            "latency after the deploy. Actions: rollback or isolate deploy, inspect vector DB, "
            "monitor EU latency, and send a transparent customer update."
        ),
    },
    {
        "input": (
            "A support agent says the chatbot suggested deleting a workspace to fix billing sync. "
            "The approved playbook says never recommend destructive actions; escalate billing sync "
            "issues to Tier 2 and provide the invoice ID."
        ),
        "reference": (
            "The answer must flag unsafe guidance, state that destructive actions are not allowed, "
            "and instruct escalation to Tier 2 with invoice ID."
        ),
    },
    {
        "input": (
            "A new moderation model blocks 18% of legitimate Ukrainian-language help requests. "
            "False positives started after threshold changed from 0.72 to 0.61. No abuse spike found."
        ),
        "reference": (
            "The answer should identify false-positive moderation regression, connect it to threshold "
            "change, recommend rollback/recalibration and sampling, and mention no abuse spike found."
        ),
    },
    {
        "input": (
            "Internal RAG answers cite an outdated SOC2 policy from 2023. The current policy is dated "
            "2025-04 and says customer exports require manager approval plus audit logging."
        ),
        "reference": (
            "The answer should identify stale retrieval/citation, use current 2025-04 policy, and state "
            "manager approval plus audit logging for exports."
        ),
    },
]


async def seed_demo_data() -> None:
    async with AsyncSessionLocal() as session:
        existing = await session.scalar(select(TestSet).where(TestSet.name == DEMO_SET_NAME))
        if existing is not None:
            return

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
