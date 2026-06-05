from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_and_config(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}

    config = client.get("/api/config")
    assert config.status_code == 200
    payload = config.json()
    assert payload["pass_threshold"] == 0.7
    assert payload["max_concurrency"] == 2
    for key in (
        "openrouter_min_interval_seconds",
        "gemini_min_interval_seconds",
        "groq_min_interval_seconds",
    ):
        assert isinstance(payload[key], int | float)
        assert payload[key] >= 0
    assert payload["fallback_to_mock_judge_on_error"] is True
    assert "mock/target" in payload["models"]
    assert any(model.startswith("gemini/") for model in payload["models"])
    assert any(model.startswith("groq/") for model in payload["models"])
    assert any(model.startswith("gemini/") for model in payload["judge_models"])
    assert any(model.startswith("groq/") for model in payload["judge_models"])
    assert "openrouter/free" in payload["judge_models"]
    assert "mock/judge" in payload["judge_models"]
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


def test_clear_cases_removes_cases_and_run_history(client: TestClient) -> None:
    test_set_id = client.post("/test-sets", json={"name": "Cleanup cases"}).json()["id"]
    client.post(
        f"/test-sets/{test_set_id}/cases/bulk",
        json=[
            {"input": "What is RAG?", "reference": "Retrieval augmented generation."},
            {"input": "Name one FastAPI advantage."},
        ],
    )
    client.post(
        "/runs",
        json={
            "test_set_id": test_set_id,
            "target_model": "mock/target",
            "judge_model": "mock/judge",
            "judge_provider": "mock",
            "prompt_template": "Answer clearly: {input}",
        },
    )

    response = client.delete(f"/test-sets/{test_set_id}/cases")
    assert response.status_code == 204

    detail = client.get(f"/test-sets/{test_set_id}").json()
    assert detail["cases"] == []
    history = client.get(f"/test-sets/{test_set_id}/runs").json()
    assert history == []
    listed = client.get("/test-sets").json()
    cleaned = next(item for item in listed if item["id"] == test_set_id)
    assert cleaned["case_count"] == 0


def test_delete_test_set_removes_set(client: TestClient) -> None:
    test_set_id = client.post("/test-sets", json={"name": "Delete me"}).json()["id"]
    client.post(
        f"/test-sets/{test_set_id}/cases/bulk",
        json=[{"input": "Question", "reference": "Answer"}],
    )
    client.post(
        "/runs",
        json={
            "test_set_id": test_set_id,
            "target_model": "mock/target",
            "judge_model": "mock/judge",
            "judge_provider": "mock",
            "prompt_template": "Answer clearly: {input}",
        },
    )

    response = client.delete(f"/test-sets/{test_set_id}")
    assert response.status_code == 204
    assert client.get(f"/test-sets/{test_set_id}").status_code == 404
    assert all(item["id"] != test_set_id for item in client.get("/test-sets").json())


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
    assert all(result["correctness_score"] is not None for result in results)
    assert all(result["relevance_score"] is not None for result in results)
    assert all(result["completeness_score"] is not None for result in results)
    assert all(result["prompt_quality_score"] is not None for result in results)

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


def test_compare_runs_endpoint(client: TestClient) -> None:
    test_set_id = client.post("/test-sets", json={"name": "Compare runs"}).json()["id"]
    client.post(
        f"/test-sets/{test_set_id}/cases/bulk",
        json=[
            {"input": "What is RAG?", "reference": "RAG combines retrieval with generation."},
            {"input": "Name one eval metric.", "reference": "Accuracy."},
        ],
    )

    run_a = client.post(
        "/runs",
        json={
            "test_set_id": test_set_id,
            "target_model": "mock/target",
            "judge_model": "mock/judge",
            "judge_provider": "mock",
            "prompt_template": "Answer vaguely: {input}",
        },
    ).json()["run_id"]
    run_b = client.post(
        "/runs",
        json={
            "test_set_id": test_set_id,
            "target_model": "mock/target",
            "judge_model": "mock/judge",
            "judge_provider": "mock",
            "prompt_template": "Answer with the reference terms: {input}",
        },
    ).json()["run_id"]

    response = client.get(f"/runs/compare?a={run_a}&b={run_b}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_a"]["id"] == run_a
    assert payload["run_b"]["id"] == run_b
    assert len(payload["rows"]) == 2
    assert "delta_score" in payload["rows"][0]
    assert "delta_prompt_quality" in payload["rows"][0]
