"""Live event feed: what changed, as it happens.

Events are stored in SQLite (so the feed survives restarts) and pushed to every connected
dashboard over Server-Sent Events. Publishing is thread-safe because pipeline builds and the
folder watcher run in background threads while subscribers live on the asyncio event loop.

Event kinds
  data      a new report/file was detected, imported or loaded
  report    what the latest monthly report says changed (cost revision, slip, completion, new project)
  warning   model-side escalations after a retrain (became Red, new Critical warning, ...)
  decision  an administrative action was recorded
  system    retrain started / finished / failed; ``state_updated`` tells dashboards to refresh
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    project_id TEXT,
    month TEXT,
    data TEXT
);
"""
SEVERITIES = ("info", "notice", "high", "critical")


class EventBus:
    def __init__(self, db_path: Path, cache_size: int = 500):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c:
            c.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._cache: deque[dict] = deque(self._load(cache_size), maxlen=cache_size)

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _load(self, n: int) -> list[dict]:
        with closing(self._conn()) as c:
            rows = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [self._row(r) for r in reversed(rows)]

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        d["data"] = json.loads(d["data"]) if d.get("data") else None
        return d

    # ------------------------------------------------------------------ publish
    def publish(self, kind: str, title: str, *, severity: str = "info", detail: str | None = None,
                project_id: str | None = None, month: str | None = None, data: dict | None = None,
                persist: bool = True) -> dict:
        ev = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind,
              "severity": severity if severity in SEVERITIES else "info", "title": title, "detail": detail,
              "project_id": project_id, "month": month, "data": data}
        with self._lock:
            if persist:
                with closing(self._conn()) as c:
                    cur = c.execute(
                        "INSERT INTO events (ts, kind, severity, title, detail, project_id, month, data)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (ev["ts"], kind, ev["severity"], title, detail, project_id, month,
                         json.dumps(data) if data is not None else None))
                    c.commit()
                    ev["id"] = cur.lastrowid
                self._cache.append(ev)
            else:
                ev["id"] = None
            subscribers = list(self._subscribers)
        for loop, q in subscribers:
            try:
                loop.call_soon_threadsafe(q.put_nowait, ev)
            except RuntimeError:  # loop closed: the client went away
                self.unsubscribe((loop, q))
        return ev

    def publish_many(self, events: list[dict]) -> None:
        for e in events:
            self.publish(**e)

    # ------------------------------------------------------------------ read
    def history(self, limit: int = 100, kind: str | None = None) -> list[dict]:
        if limit <= 0:
            return []
        with self._lock:
            items = [e for e in self._cache if kind is None or e["kind"] == kind]
        if len(items) < limit and len(self._cache) == self._cache.maxlen:  # older than the cache
            with closing(self._conn()) as c:
                q = "SELECT * FROM events" + (" WHERE kind=?" if kind else "") + " ORDER BY id DESC LIMIT ?"
                rows = c.execute(q, ((kind, limit) if kind else (limit,))).fetchall()
            items = [self._row(r) for r in reversed(rows)]
        return list(reversed(items[-limit:]))

    def count(self) -> int:
        with closing(self._conn()) as c:
            return int(c.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    # ------------------------------------------------------------------ subscribe
    def subscribe(self) -> tuple[asyncio.AbstractEventLoop, asyncio.Queue]:
        sub = (asyncio.get_running_loop(), asyncio.Queue(maxsize=1000))
        with self._lock:
            self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub) -> None:
        with self._lock:
            self._subscribers.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
