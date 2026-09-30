from prism.engines.evidence import portfolio_evidence, project_evidence
from prism.engines.llm import Assistant, deterministic_answer, validate

EV = {"scope": "project", "items": [
    {"id": "E1", "category": "facts", "label": "cost", "value": 1807.4, "text": "Revised cost is Rs 1,807.4 Cr, growth 12.5%."},
    {"id": "E2", "category": "risk", "label": "risk", "value": 75.6, "text": "Composite risk score is 75.6/100."},
]}


def test_validator_accepts_grounded_answer():
    r = validate("The revised cost is Rs 1,807.4 Cr [E1] and risk is 75.6/100 [E2].", EV)
    assert r["grounded"] and r["citations"] == ["E1", "E2"]


def test_validator_rejects_hallucinated_number_and_citation():
    r = validate("Cost may reach Rs 2,400 Cr [E1][E9].", EV)
    assert not r["grounded"]
    assert 2400.0 in r["ungrounded_numbers"] and r["invalid_citations"] == ["E9"]


def test_validator_requires_citations():
    assert validate("Risk is 75.6.", EV)["missing_citations"]


def test_rounding_tolerance():
    assert validate("Growth is about 12.5% [E1] and risk 76 [E2].", EV)["grounded"]


class FakeClient:
    model = "fake"

    def __init__(self, replies):
        self.replies = list(replies)

    def status(self):
        return {"available": True, "model": "fake"}

    def chat(self, messages):
        return self.replies.pop(0)


def test_llm_retry_then_accept():
    a = Assistant(FakeClient(["Risk is 99.9 [E2].", "Risk is 75.6/100 [E2]."]))
    r = a.answer("What is the risk?", EV)
    assert r["engine"] == "ollama:fake" and r["attempts"] == 2 and r["grounding"]["grounded"]


def test_llm_rejected_falls_back_to_deterministic():
    a = Assistant(FakeClient(["Risk is 99.9 [E2].", "Still 88.8 [E2]."]))
    r = a.answer("What is the risk?", EV)
    assert r["engine"].startswith("deterministic") and r["grounding"]["grounded"]


def test_deterministic_answers_are_grounded(state):
    pid = state.latest.sort_values("priority_index", ascending=False)["project_id"].iloc[0]
    ev = project_evidence(state, pid)
    for q in ["Why is it risky?", "What should we do next?", "When will it complete?", "Is the data reliable?",
              "What are the cost risks?", "Any similar past projects?", "what bottlenecks?"]:
        ans = deterministic_answer(q, ev)
        assert validate(ans, ev, q)["grounded"], (q, ans)
    pev = portfolio_evidence(state)
    for q in ["Which projects need attention?", "Top bottlenecks?", "Which sector is riskiest?", "Summary"]:
        assert validate(deterministic_answer(q, pev), pev, q)["grounded"]
