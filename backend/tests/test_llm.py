import json
from dataclasses import replace

import httpx
import pytest

from prism.config import normalise_host
from prism.engines import llm


@pytest.mark.parametrize("raw,url", [
    ("0.0.0.0", "http://127.0.0.1:11434"),
    ("localhost:11434", "http://localhost:11434"),
    ("http://gpu-box:8080/", "http://gpu-box:8080"),
    ("", "http://127.0.0.1:11434"),
])
def test_host_normalisation(raw, url):
    assert normalise_host(raw) == url


def fake_ollama(models, chat_reply="The revised cost is Rs 1,807.4 Cr [E1]."):
    def handler(req: httpx.Request):
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in models]})
        if req.url.path == "/api/chat":
            return httpx.Response(200, json={"message": {"content": chat_reply}})
        if req.url.path == "/api/pull":
            lines = [{"status": "pulling", "total": 100, "completed": 50}, {"status": "success"}]
            return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines))
        if req.url.path == "/api/generate":
            return httpx.Response(200, json={"response": "ok"})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(llm, "settings", replace(llm.settings, llm_enabled=True))


def _patch(monkeypatch, client):
    monkeypatch.setattr(llm.httpx, "get", client.get)
    monkeypatch.setattr(llm.httpx, "post", client.post)
    monkeypatch.setattr(llm.httpx, "stream", client.stream)


def test_status_steps(monkeypatch, enabled):
    c = llm.OllamaClient(host="http://127.0.0.1:9", model="qwen2.5:3b")
    assert c.status(refresh=True)["step"] == "not_running"
    _patch(monkeypatch, fake_ollama(["llama3:8b"]))
    st = c.status(refresh=True)
    assert st["step"] == "model_missing" and st["installed_models"] == ["llama3:8b"] and "ollama pull" in st["hint"]
    _patch(monkeypatch, fake_ollama(["qwen2.5:3b"]))
    assert c.status()["step"] == "model_missing"  # cached ...
    assert c.status(refresh=True)["step"] == "ready"  # ... until re-checked


def test_pull_reports_progress(monkeypatch, enabled):
    _patch(monkeypatch, fake_ollama([]))
    seen = []
    llm.OllamaClient(model="qwen2.5:3b").pull(lambda s, p: seen.append((s, p)))
    assert seen == [("pulling", 50), ("success", None)]


EV = {"scope": "project", "items": [
    {"id": "E1", "category": "facts", "label": "cost", "value": 1807.4, "text": "Revised cost is Rs 1,807.4 Cr."}]}


def test_llm_answer_used_when_grounded(monkeypatch, enabled):
    _patch(monkeypatch, fake_ollama(["qwen2.5:3b"]))
    res = llm.Assistant(llm.OllamaClient(model="qwen2.5:3b")).answer("What is the cost?", EV)
    assert res["engine"] == "ollama:qwen2.5:3b" and res["grounding"]["grounded"]


def test_ungrounded_llm_answer_falls_back(monkeypatch, enabled):
    _patch(monkeypatch, fake_ollama(["qwen2.5:3b"], chat_reply="Cost will hit Rs 9,999 Cr [E1]."))
    res = llm.Assistant(llm.OllamaClient(model="qwen2.5:3b")).answer("What is the cost?", EV)
    assert res["engine"].startswith("deterministic") and res["attempts"] == 2
