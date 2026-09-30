"""Grounded LLM assistant: local Ollama (Qwen 2.5 3B) + Grounding Validator.

Flow for every question:
  1. The Evidence Packager builds citable items E1..En (project or portfolio scope).
  2. If a local Ollama server is reachable, Qwen is asked to answer using ONLY
     those items and to cite them as [E#].
  3. The Grounding Validator checks every number in the answer against the
     evidence (with rounding tolerance) and every citation against the item ids.
     One corrective retry is allowed; if it still fails, or no LLM is available,
     a deterministic evidence-composed answer is returned instead.

Project data never leaves the machine: the only network call is to the local
Ollama host, which makes the assistant usable in air-gapped deployments.
"""
from __future__ import annotations

import json
import logging
import re
import time

import httpx

from prism.config import settings

log = logging.getLogger("prism.llm")

SYSTEM_PROMPT = """You are PRISM, a decision-support assistant for MoSPI's PAIMANA infrastructure project monitoring.
Rules you must follow:
1. Use ONLY the facts in the EVIDENCE list. Never invent numbers, dates, names or causes.
2. After every sentence that states a fact, cite the evidence id(s) in square brackets, e.g. [E3] or [E2][E7].
3. Copy numbers exactly as they appear in the evidence. Do not compute new numbers.
4. If the evidence does not answer the question, say "The available evidence does not cover this." and stop.
5. Be concise (at most 6 sentences). Write for a senior government administrator.
6. Frame suggestions as review pathways for the administrator to consider, not as decisions."""

_NUM = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?")
_CITE = re.compile(r"\[(E\d+)\]")
_IDS = re.compile(r"\bPRJ-\d+\b")


# --------------------------------------------------------------------------- validator
def _numbers(text: str) -> list[float]:
    text = _IDS.sub(" ", _CITE.sub(" ", text))
    out = []
    for m in _NUM.findall(text):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def allowed_numbers(evidence: dict, question: str = "") -> set[float]:
    nums: set[float] = set()
    for it in evidence["items"]:
        nums.update(_numbers(it["text"]))
        if isinstance(it.get("value"), (int, float)) and it["value"] is not None:
            nums.add(float(it["value"]))
    nums.update(_numbers(question))
    derived = set()
    for v in nums:
        for d in (0, 1, 2):
            derived.add(round(v, d))
        derived.add(abs(v))
    return nums | derived | {3.0, 6.0, 12.0}


def validate(answer: str, evidence: dict, question: str = "") -> dict:
    ids = {it["id"] for it in evidence["items"]}
    cites = _CITE.findall(answer)
    invalid = sorted(set(c for c in cites if c not in ids))
    allowed = allowed_numbers(evidence, question)
    found = _numbers(answer)
    ungrounded = []
    for n in found:
        if n.is_integer() and 0 <= n <= 10:  # small ordinals / counts ("two", "3 options")
            continue
        if not any(abs(n - a) <= max(0.051, 0.0005 * abs(a)) for a in allowed):
            ungrounded.append(n)
    needs_cite = bool(found) and not cites
    grounded = not ungrounded and not invalid and not needs_cite
    return {"grounded": grounded, "numbers_checked": len(found), "ungrounded_numbers": ungrounded,
            "invalid_citations": invalid, "citations": sorted(set(cites), key=lambda c: int(c[1:])),
            "missing_citations": needs_cite}


# --------------------------------------------------------------------------- ollama
class OllamaClient:
    def __init__(self, host: str | None = None, model: str | None = None):
        self.host = (host or settings.ollama_host).rstrip("/")
        self.model = model or settings.ollama_model
        self._status: tuple[float, dict] | None = None

    def status(self, refresh: bool = False) -> dict:
        """Where the local LLM stands, with the next setup step in plain English."""
        if not settings.llm_enabled:
            return {"available": False, "model": self.model, "host": self.host, "step": "disabled",
                    "installed_models": [], "reason": "disabled by configuration",
                    "hint": "The LLM is switched off (PRISM_LLM_ENABLED=0). Remove that setting to use Ollama."}
        if not refresh and self._status and time.time() - self._status[0] < 30:
            return self._status[1]
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=2.0)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            ok = self.model in models or f"{self.model}:latest" in models
            st = {"available": ok, "model": self.model, "host": self.host, "installed_models": models,
                  "step": "ready" if ok else "model_missing",
                  "reason": None if ok else f"model {self.model} not pulled (run: ollama pull {self.model})",
                  "hint": f"Ollama is running and {self.model} is loaded: answers are written by the LLM and checked by the grounding validator."
                  if ok else f"Ollama is running but the {self.model} model is not downloaded yet. Click Download model or run: ollama pull {self.model}"}
        except Exception as e:  # noqa: BLE001
            st = {"available": False, "model": self.model, "host": self.host, "installed_models": [],
                  "step": "not_running", "reason": f"Ollama not reachable at {self.host}: {type(e).__name__}",
                  "hint": f"Ollama is not running at {self.host}. Install it from ollama.com/download and start it "
                          "(on Windows it runs from the system tray; otherwise run: ollama serve)."}
        self._status = (time.time(), st)
        return st

    def pull(self, on_progress=None) -> None:
        """Download the model through Ollama, reporting (status, percent) as it goes."""
        with httpx.stream("POST", f"{self.host}/api/pull", json={"model": self.model, "name": self.model, "stream": True},
                          timeout=httpx.Timeout(30.0, read=None)) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("error"):
                    raise RuntimeError(msg["error"])
                pct = round(100 * msg["completed"] / msg["total"]) if msg.get("total") and msg.get("completed") else None
                if on_progress:
                    on_progress(msg.get("status", ""), pct)
        self._status = None

    def warm(self) -> None:
        """Load the model into memory so the first real question is not the slow one."""
        httpx.post(f"{self.host}/api/generate", json={"model": self.model, "prompt": "ok", "stream": False,
                                                      "options": {"num_predict": 1}}, timeout=settings.ollama_timeout_s)

    def chat(self, messages: list[dict]) -> str:
        r = httpx.post(f"{self.host}/api/chat", timeout=settings.ollama_timeout_s, json={
            "model": self.model, "messages": messages, "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 4096},
        })
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


def _evidence_block(evidence: dict) -> str:
    return "\n".join(f"[{it['id']}] ({it['category']}) {it['text']}" for it in evidence["items"])


# --------------------------------------------------------------------------- deterministic answers
_INTENTS = [
    ("changes", r"chang|latest|this month|last month|new report|what happened|update"),
    ("drivers", r"\bwhy\b|driver|cause|reason|explain|factor"),
    ("actions", r"action|recommend|intervention|should|what next|what's next|review|pathway|do about"),
    ("forecast", r"forecast|when|complet|finish|predict|future|expect"),
    ("cost", r"cost|overrun|budget|expenditure|escalat|spend"),
    ("schedule", r"delay|schedule|slip|time overrun|late"),
    ("analogues", r"similar|analog|past|histor|precedent"),
    ("trust", r"data|quality|trust|reliab|confiden|stale"),
    ("bottlenecks", r"bottleneck|issue|remark|problem|constraint|block"),
    ("warnings", r"warning|alert|risk|red|amber"),
    ("priority", r"priorit|attention|top|worst|which projects|focus"),
    ("sectors", r"sector|ministr|department"),
]


def _intent(q: str) -> str:
    ql = q.lower()
    for name, pat in _INTENTS:
        if re.search(pat, ql):
            return name
    return "summary"


def _cite(ev: dict, *cats: str, limit: int = 6) -> list[dict]:
    """Evidence items of the given categories, in the order the categories are listed."""
    return [it for c in cats for it in ev["items"] if it["category"] == c][:limit]


_LEADS = {
    "drivers": "Here is why the models rate this risk the way they do:",
    "actions": "The current warnings and the factors behind them:",
    "forecast": "What the forecasts say:",
    "cost": "On cost:",
    "schedule": "On schedule:",
    "analogues": "How comparable projects turned out:",
    "trust": "On the quality of the underlying data:",
    "bottlenecks": "The issues on record:",
    "warnings": "Current risk status and early warnings:",
    "priority": "Projects that need attention first (highest Priority Attention Index):",
    "sectors": "By sector / ministry:",
    "changes": "What the latest report changed:",
    "summary": "Summary:",
}


def _compose(items: list[dict], intent: str = "summary") -> str:
    """A lead sentence followed by one cited bullet per evidence item."""
    return _LEADS.get(intent, "Summary:") + "\n" + "\n".join(f"- {it['text']} [{it['id']}]" for it in items)


def deterministic_answer(question: str, ev: dict) -> str:
    intent = _intent(question)
    if ev["scope"] == "project":
        by = {
            "drivers": ("drivers", "risk"), "cost": ("facts", "forecast", "drivers"), "schedule": ("facts", "forecast"),
            "forecast": ("forecast",), "analogues": ("analogues",), "trust": ("trust",),
            "bottlenecks": ("remarks",), "warnings": ("risk", "warning"), "priority": ("risk", "warning"),
            "sectors": ("facts",), "actions": ("warning", "drivers"), "summary": ("facts", "risk", "warning"),
            "changes": ("facts", "forecast"),
        }[intent]
        items = _cite(ev, *by, limit=8)
        if intent == "cost":
            items = [i for i in items if any(k in i["label"].lower() for k in ("cost", "expenditure"))] + \
                    [i for i in items if i["category"] == "drivers" and "Cost" in i["label"]]
        if intent == "schedule":
            items = [i for i in items if any(k in i["label"].lower() for k in ("schedule", "velocity", "completion", "time"))]
        text = _compose(items, intent) if items else "The available evidence does not cover this."
        if intent == "actions" and ev.get("pathways"):
            text += "\n\nReview pathways for consideration:\n" + "\n".join(
                f"{i + 1}. {p['text']} (because {p['because']})" for i, p in enumerate(ev["pathways"]))
        return text
    by = {"priority": ("priority",), "warnings": ("warnings", "portfolio"), "bottlenecks": ("bottlenecks", "patterns"),
          "sectors": ("sectors", "ministries"), "cost": ("portfolio", "sectors"), "trust": ("portfolio",),
          "changes": ("changes",), "schedule": ("changes", "warnings"), "drivers": ("patterns", "bottlenecks"),
          }.get(intent, ("portfolio", "warnings", "patterns"))
    items = _cite(ev, *by, limit=8)
    return _compose(items, intent) if items else "The available evidence does not cover this."


# --------------------------------------------------------------------------- entry point
class Assistant:
    def __init__(self, client: OllamaClient | None = None):
        self.client = client or OllamaClient()

    def answer(self, question: str, evidence: dict, history: list[dict] | None = None) -> dict:
        t0 = time.time()
        st = self.client.status()
        engine, attempts, answer, report = "deterministic", 0, None, None
        if st["available"]:
            msgs = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "system", "content": "EVIDENCE:\n" + _evidence_block(evidence)}]
            for h in (history or [])[-4:]:
                msgs.append({"role": h["role"], "content": h["content"]})
            msgs.append({"role": "user", "content": question})
            for attempts in (1, 2):
                try:
                    cand = self.client.chat(msgs)
                except Exception as e:  # noqa: BLE001
                    log.warning("Ollama call failed: %s", e)
                    break
                report = validate(cand, evidence, question)
                if report["grounded"]:
                    answer, engine = cand, f"ollama:{self.client.model}"
                    break
                msgs += [{"role": "assistant", "content": cand},
                         {"role": "user", "content": "Your answer failed grounding validation: " + json.dumps({
                             k: report[k] for k in ("ungrounded_numbers", "invalid_citations", "missing_citations")})
                          + ". Rewrite it using only numbers that appear in the evidence and cite every fact."}]
        if answer is None:
            answer = deterministic_answer(question, evidence)
            report = validate(answer, evidence, question)
            if st["available"]:
                engine = "deterministic (LLM answer rejected by grounding validator)" if attempts else engine
        cited = {c for c in report["citations"]}
        return {
            "answer": answer, "engine": engine, "llm": st, "grounding": report, "attempts": attempts,
            "evidence_used": [it for it in evidence["items"] if it["id"] in cited],
            "latency_ms": int((time.time() - t0) * 1000),
        }
