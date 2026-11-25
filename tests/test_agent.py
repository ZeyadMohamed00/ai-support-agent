import pytest
from agent.agent import SupportAgent
from agent.tools import Store


@pytest.fixture()
def store():
    return Store()


def test_order_status(store):
    a = SupportAgent("sara@example.com", store)
    assert "A1002" in a.handle("Where is my order A1002?") and "shipped" in a.handle("status of A1002")


def test_cannot_read_other_customers_order(store):
    a = SupportAgent("sara@example.com", store)
    assert a.handle("where is order A1003") == "I couldn't find that order on your account."
    assert store.get_order("sara@example.com", "A9999") == {"error": "order_not_found"}


def test_refund_approved_and_recorded(store):
    a = SupportAgent("sara@example.com", store)
    assert "refunded 49.90" in a.handle("I want a refund for A1001")
    assert store.refunds == [{"customer": "sara@example.com", "order_id": "A1001", "amount": 49.9}]


def test_refund_rules(store):
    omar = SupportAgent("omar@example.com", store)
    assert "outside the refund window" in omar.handle("refund A1003")
    assert "not been delivered" in omar.handle("refund A1004")
    sara = SupportAgent("sara@example.com", store)
    assert "not been delivered" in sara.handle("refund A1002")
    assert store.refunds == []


def test_big_refund_needs_human(store):
    s = Store()
    s.orders["A2000"] = {"customer": "sara@example.com", "status": "delivered", "delivered_days_ago": 1, "total": 500.0, "items": ["TV"]}
    a = SupportAgent("sara@example.com", s)
    assert "human" in a.handle("refund A2000")
    assert s.refunds == [] and len(s.tickets) == 1


def test_asks_for_order_number_then_remembers(store):
    a = SupportAgent("sara@example.com", store)
    assert "order number" in a.handle("I want a refund")
    a.handle("where is order A1001")
    assert "refunded" in a.handle("ok refund it")  # uses last_order from state


def test_faq_and_unknown_escalates(store):
    a = SupportAgent("sara@example.com", store)
    assert "3 to 5 business days" in a.handle("How long does shipping take?")
    assert "Ticket #1" in a.handle("zxqv blorp")


def test_human_request_escalates(store):
    a = SupportAgent("sara@example.com", store)
    assert "Ticket" in a.handle("let me talk to a human")


def test_guardrail_blocks_invented_tools(store):
    class Rogue:
        def decide(self, m, s):
            return {"tool": "delete_database", "args": {}}
    a = SupportAgent("sara@example.com", store, brain=Rogue())
    assert "human" in a.handle("hi")
    assert a.log[0]["tool"] == "escalate"


def test_api_requires_known_customer():
    from fastapi.testclient import TestClient
    from agent.api import app
    c = TestClient(app)
    assert c.post("/chat", json={"message": "hi"}).status_code == 401
    r = c.post("/chat", json={"message": "where is order A1002"}, headers={"X-Customer": "sara@example.com"})
    assert r.status_code == 200 and "shipped" in r.json()["reply"]
