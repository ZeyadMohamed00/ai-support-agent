import pytest
from fastapi.testclient import TestClient

from support import tools as T
from support.classify import cost_usd, rule_classify
from support.main import app

c = TestClient(app)
H = lambda n="clienttest-1", who="sara@example.com": {"X-Client-Id": n, "X-Customer": who}


def chat(msg, conv=None, **kw):
    r = c.post("/chat", headers=H(**kw), json={"message": msg, "conversation_id": conv})
    assert r.status_code == 200, r.text
    return r.json()


def test_order_status_and_followup_uses_conversation_memory():
    a = (
        chat("where is order A1002?", client_id=None)
        if False
        else chat("where is order A1002?", n="mem-client-01")
    )
    assert "A1002" in a["reply"] and "2 days" in a["reply"]
    b = chat("and what is its status", conv=a["conversation_id"], n="mem-client-01")
    assert "A1002" in b["reply"]


def test_cannot_read_other_customers_order():
    r = chat("status of A1003", n="authz-client-01")
    assert "could not find" in r["reply"]
    assert "USB" not in r["reply"]
    assert "USB" in chat("status of A1003", n="authz-client-01", who="omar@example.com")["reply"]


def test_small_refund_executes_and_second_is_blocked():
    r = chat("refund A1001", n="refund-client-1")
    assert "refunded $49.90" in r["reply"]
    assert "already refunded" in chat("refund A1001", n="refund-client-1")["reply"]
    assert [
        o for o in c.get("/orders", headers=H("refund-client-1")).json() if o["order_no"] == "A1001"
    ][0]["refunded"] is True


def test_refund_rules_denied():
    assert "not been delivered" in chat("refund A1002", n="rules-client-01")["reply"]
    assert "outside" in chat("refund A1003", n="rules-client-01", who="omar@example.com")["reply"]


def test_large_refund_needs_human_and_approval_resumes_graph():
    n = "approve-client-1"
    r = chat("I want a refund for A1005", n=n)
    assert r["pending_approval_id"] and "need a human" in r["reply"]
    orders = {o["order_no"]: o for o in c.get("/orders", headers=H(n)).json()}
    assert orders["A1005"]["refunded"] is False  # nothing happens before approval
    d = c.post(
        f"/approvals/{r['pending_approval_id']}/decision", headers=H(n), json={"approve": True}
    ).json()
    assert d["status"] == "approved" and "refunded" in d["message"]
    assert {o["order_no"]: o for o in c.get("/orders", headers=H(n)).json()}["A1005"][
        "refunded"
    ] is True
    assert (
        c.post(
            f"/approvals/{r['pending_approval_id']}/decision", headers=H(n), json={"approve": True}
        ).status_code
        == 409
    )
    msgs = c.get(f"/conversations/{r['conversation_id']}", headers=H(n)).json()
    assert msgs[-1]["role"] == "assistant" and "approved" in msgs[-1]["content"]


def test_rejected_approval_never_refunds():
    n = "reject-client-1"
    r = chat("refund A1005", n=n)
    c.post(f"/approvals/{r['pending_approval_id']}/decision", headers=H(n), json={"approve": False})
    assert {o["order_no"]: o for o in c.get("/orders", headers=H(n)).json()}["A1005"][
        "refunded"
    ] is False


def test_approval_isolated_between_clients():
    r = chat("refund A1005", n="iso-client-0001")
    assert (
        c.post(
            f"/approvals/{r['pending_approval_id']}/decision",
            headers=H("iso-client-0002"),
            json={"approve": True},
        ).status_code
        == 404
    )


def test_escalate_and_faq_and_unknown():
    assert "human agent" in chat("I want to talk to a manager", n="misc-client-01")["reply"]
    assert (
        "3 to 5 business days" in chat("How long does shipping take?", n="misc-client-01")["reply"]
    )
    assert (
        "will not guess" in chat("what is the airspeed of a swallow", n="misc-client-01")["reply"]
    )


def test_logging_and_zero_llm_cost():
    chat("where is order A1001", n="log-client-001")
    logs = c.get("/logs", headers=H("log-client-001")).json()
    assert logs[0]["tool"] == "get_order" and logs[0]["ok"] and logs[0]["latency_ms"] >= 0
    u = c.get("/usage", headers=H("log-client-001")).json()
    assert u["llm_calls"] == 0 and u["cost_usd"] == 0


def test_cost_math():
    assert cost_usd("gpt-4o-mini", 1_000_000, 1_000_000) == pytest.approx(0.75)
    assert cost_usd("unknown-model", 10, 10) == 0.0


def test_retry_recovers_then_gives_up():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise T.TransientError("blip")
        return {"ok": 1}

    res, attempts = T.with_retry(flaky, base_delay=0)
    assert res == {"ok": 1} and attempts == 3

    def dead():
        raise T.TransientError("down")

    with pytest.raises(T.TransientError):
        T.with_retry(dead, base_delay=0)


def test_total_tool_outage_is_handled_and_logged(monkeypatch):
    monkeypatch.setenv("FAULT_RATE", "1.0")
    r = chat("where is order A1001", n="outage-client-01")
    assert "not responding" in r["reply"]
    logs = c.get("/logs", headers=H("outage-client-01")).json()
    assert logs[0]["ok"] is False and logs[0]["attempts"] == 3


def test_classifier_basics():
    assert rule_classify("I want my money back") == "refund"
    assert rule_classify("What is your refund policy?") == "faq"
    assert rule_classify("get me a manager") == "human"


def test_validation():
    assert c.post("/chat", headers=H("val-client-01"), json={"message": "  "}).status_code == 422
    assert c.post("/chat", json={"message": "hi"}).status_code == 400
