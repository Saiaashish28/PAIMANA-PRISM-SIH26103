import asyncio
import json
import threading

import pytest


def test_event_bus_roundtrip_and_fanout(tmp_path):
    from prism.events import EventBus

    bus = EventBus(tmp_path / "ev.db", cache_size=3)
    for i in range(5):
        bus.publish("report", f"e{i}", severity="notice", month="2026-08", data={"i": i})
    bus.publish("system", "state_updated", persist=False)
    assert bus.count() == 5
    hist = bus.history(limit=4)
    assert [e["title"] for e in hist] == ["e4", "e3", "e2", "e1"]  # newest first, beyond the cache
    assert hist[0]["data"] == {"i": 4}
    assert bus.history(0) == []  # replay=0 must not replay everything
    assert [e["title"] for e in EventBus(tmp_path / "ev.db").history(2)] == ["e4", "e3"]  # survives restart

    async def listen():
        sub = bus.subscribe()
        t = threading.Thread(target=bus.publish, args=("warning", "from a thread"))
        t.start()
        ev = await asyncio.wait_for(sub[1].get(), 5)
        t.join()
        bus.unsubscribe(sub)
        return ev

    ev = asyncio.run(listen())
    assert ev["title"] == "from a thread" and ev["id"] == 6
    assert bus.subscriber_count == 0


def test_month_changes_and_diff(state):
    from prism.engines.analytics import change_events, month_changes, state_diff

    ch = month_changes(state.panel, state.latest)
    s = ch["summary"]
    assert ch["previous_month"] and ch["month"] > ch["previous_month"]
    assert s["reported"] > 0 and len(ch["schedule_slips"]) == min(s["schedule_slips"], 40)
    assert all(r["months"] > 0 for r in ch["schedule_slips"])
    assert all(r["to_cr"] > r["from_cr"] for r in ch["cost_revisions"])
    evs = change_events(ch)
    assert evs and all(e["month"] == ch["month"] for e in evs)

    old = state.latest.reset_index(drop="project_id" in state.latest.columns)
    new = old.copy()
    i = new.index[(new["status"] == "Ongoing") & (new["rag"] != "Red")][0]
    pid = new.at[i, "project_id"]
    new.loc[i, "rag"] = "Red"
    diff = state_diff(old, new, state.warnings, state.warnings)
    assert any(e.get("project_id") == pid and e["severity"] == "critical" for e in diff)


@pytest.fixture(scope="module")
def client(state):
    from fastapi.testclient import TestClient
    from prism.api import main

    main.rt.state = state
    main.rt.build_async = lambda *a, **k: None
    with TestClient(main.app) as c:
        yield c


def test_event_endpoints(client):
    from prism.api import main

    main.rt.events.publish("data", "hello feed", severity="notice")
    items = client.get("/api/events?limit=5").json()
    assert items[0]["title"] == "hello feed"
    ch = client.get("/api/changes/latest").json()
    assert "summary" in ch and "watching" in ch
    assert isinstance(client.get("/api/interventions/queue?limit=5").json(), list)


def test_sse_stream_replays_history():
    from prism.api import main

    async def first_event():
        resp = await main.events_stream(_FakeRequest(), replay=20)
        async for chunk in resp.body_iterator:
            text = chunk if isinstance(chunk, str) else chunk.decode()
            if "event: feed" in text:
                return json.loads(text.split("data: ", 1)[1])

    main.rt.events.publish("data", "streamed", severity="info")
    ev = asyncio.run(asyncio.wait_for(first_event(), 5))
    assert ev["kind"] in {"data", "report", "warning", "decision", "system"}


class _FakeRequest:
    async def is_disconnected(self):
        return False


def test_watcher_detects_new_file(monkeypatch, tmp_path):
    from prism.api import main

    from dataclasses import replace

    monkeypatch.setattr(main, "settings", replace(main.settings, data_dir=tmp_path))
    (tmp_path / "real").mkdir()
    calls = []
    fake = type("R", (), {"building": False, "importing": False, "events": main.rt.events,
                          "build": lambda self, force=False, reason=None: calls.append(("build", reason)),
                          "import_and_build": lambda self, reason=None: calls.append(("import", reason))})()
    w = main.FolderWatcher(fake, 5)
    assert w.check() == []
    (tmp_path / "real" / "paimana_2026-09.csv").write_text("project_id\nX\n")
    assert w.check() == ["real/paimana_2026-09.csv"]
    assert calls[-1][0] == "build"
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "FlashReport_Sep2026.pdf").write_bytes(b"%PDF")
    w.check()
    assert calls[-1][0] == "import"
    assert w.check() == []
