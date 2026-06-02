from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_eval_lab.db")
os.environ.setdefault("LOCAL_MOCK_WITHOUT_KEYS", "true")

from app.db import Base, engine
from app.main import app
from app import models  # noqa: F401


async def reset_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        asyncio.run(reset_db())
        yield test_client
