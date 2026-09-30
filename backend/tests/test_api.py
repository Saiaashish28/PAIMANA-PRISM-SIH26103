import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(state):
    from prism.api import main

    main.rt.state = state
    main.rt.store.seed_historical(state.historical_interventions)
    main.rt.build_async = lambda *a, **k: None  # never retrain inside tests
    with TestClient(main.app) as c:
        yield c


def test_health_and_meta(client):
    assert client.get("/api/health").json()["status"] == "ready"
    assert "ministries" in client.get("/api/meta").json()


@pytest.mark.parametrize("path", ["/api/portfolio/summary", "/api/portfolio/intelligence", "/api/map", "/api/warnings",
                                  "/api/trust", "/api/models/benchmark", "/api/interventions"])
def test_portfolio_endpoints(client, path):
    assert client.get(path).status_code == 200


def test_project_endpoints(client):
    items = client.get("/api/projects?limit=5").json()["items"]
    assert items and items[0]["priority_index"] >= items[-1]["priority_index"]
    pid = items[0]["project_id"]
    for sub in ["", "/timeseries", "/forecast", "/explain", "/analogues", "/scenarios", "/trust", "/evidence"]:
        assert client.get(f"/api/projects/{pid}{sub}").status_code == 200, sub
    assert client.get("/api/projects/NOPE").status_code == 404


def test_assistant_and_interventions(client):
    pid = client.get("/api/projects?limit=1").json()["items"][0]["project_id"]
    r = client.post("/api/assistant/ask", json={"question": f"Why is {pid} at risk?"}).json()
    assert r["project_id"] == pid and r["grounding"]["grounded"]
    created = client.post("/api/interventions", json={"project_id": pid, "action_type": "pmg_review",
                                                      "description": "Taken up in PMG review"})
    assert created.status_code == 201
    iid = created.json()["id"]
    listed = client.get(f"/api/interventions?project_id={pid}").json()["items"]
    assert any(i["id"] == iid and i["outcome"].startswith("Pending") for i in listed)
    assert client.delete(f"/api/interventions/{iid}").status_code == 200


def test_portfolio_questions_are_not_scoped_to_a_project(state):
    from prism.api.main import _project_from_question

    for q in ("What changed in the latest report?", "Which projects need attention first?",
              "Give me a portfolio summary", "Which sector is riskiest?", "What issues keep recurring?"):
        assert _project_from_question(state, q) is None, q
