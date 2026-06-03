from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_and_config(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}

    config = client.get("/api/config")
    assert config.status_code == 200
    payload = config.json()
    assert payload["pass_threshold"] == 0.7
    assert payload["max_concurrency"] == 2
    assert "mock/target" in payload["models"]
    assert any(model.startswith("gemini/") for model in payload["models"])
    assert any(model.startswith("groq/") for model in payload["models"])
    assert payload["judge_models"] in (["openrouter/free", "mock/judge"], ["mock/judge"])
    assert "meta-llama/llama-3.3-8b-instruct:free" not in payload["models"]
    assert "google/gemma-3-12b-it:free" not in payload["models"]
    assert "meta-llama/llama-3.3-8b-instruct:free" not in payload["judge_models"]
    assert "google/gemma-3-12b-it:free" not in payload["judge_models"]
    assert payload["local_mock_without_keys"] is True


def test_test_set_crud_and_bulk_cases(client: TestClient) -> None:
    created = client.post("/test-sets", json={"name": "CV assistant evals"})
    assert created.status_code == 201
    test_set_id = created.json()["id"]

    bulk = client.post(
        f"/test-sets/{test_set_id}/cases/bulk",
        json=[
            {"input": "What is RAG?", "reference": "Retrieval augmented generation."},
            {"input": "Name one FastAPI advantage."},
        ],
    )
    assert bulk.status_code == 201
    assert len(bulk.json()) == 2

    listed = client.get("/test-sets").json()
    assert listed[0]["case_count"] == 2

    detail = client.get(f"/test-sets/{test_set_id}").json()
    assert detail["name"] == "CV assistant evals"
    assert len(detail["cases"]) == 2


def test_run_executes_in_mock_mode(client: TestClient) -> None:
    test_set_id = client.post("/test-sets", json={"name": "Mock run"}).json()["id"]
    client.post(
        f"/test-sets/{test_set_id}/cases/bulk",
        json=[
            {"input": "Explain FastAPI in one sentence.", "reference": "FastAPI Python web framework."},
            {"input": "What does LLM-as-judge mean?"},
        ],
    )

    queued = client.post(
        "/runs",
        json={
            "test_set_id": test_set_id,
            "target_model": "mock/target",
            "judge_model": "mock/judge",
            "judge_provider": "mock",
            "prompt_template": "Answer clearly: {input}",
        },
    )
    assert queued.status_code == 202
    run_id = queued.json()["run_id"]

    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "done"
    assert run["done_count"] == 2
    assert run["total_count"] == 2
    assert run["avg_score"] is not None
    assert run["pass_rate"] is not None

    results = client.get(f"/runs/{run_id}/results").json()
    assert len(results) == 2
    assert all(result["output"] for result in results)
    assert all(result["judge_reason"] for result in results)

    history = client.get(f"/test-sets/{test_set_id}/runs").json()
    assert history[0]["id"] == run_id


def test_run_respects_max_cases(client: TestClient) -> None:
    test_set_id = client.post("/test-sets", json={"name": "Max cases"}).json()["id"]
    client.post(
        f"/test-sets/{test_set_id}/cases/bulk",
        json=[
            {"input": "Case 1"},
            {"input": "Case 2"},
            {"input": "Case 3"},
        ],
    )

    run_id = client.post(
        "/runs",
        json={
            "test_set_id": test_set_id,
            "target_model": "mock/target",
            "judge_model": "mock/judge",
            "judge_provider": "mock",
            "prompt_template": "Answer: {input}",
            "temperature": 0.4,
            "max_cases": 1,
        },
    ).json()["run_id"]

    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "done"
    assert run["done_count"] == 1
    assert run["total_count"] == 1
    assert run["temperature"] == 0.4
    assert run["max_cases"] == 1

    results = client.get(f"/runs/{run_id}/results").json()
    assert len(results) == 1
