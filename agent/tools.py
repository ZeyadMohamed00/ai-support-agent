"""Tools the agent may call. They are plain functions over a data store, so they are easy to test.
Every tool that touches an order checks the order belongs to the verified customer."""
import json
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer

DATA = Path(__file__).resolve().parent.parent / "data"
REFUND_WINDOW_DAYS = 30
HUMAN_APPROVAL_OVER = 200.0


class Store:
    def __init__(self, orders=None, faq=None):
        self.orders = orders if orders is not None else json.loads((DATA / "orders.json").read_text())
        self.faq = faq if faq is not None else json.loads((DATA / "faq.json").read_text())
        self.refunds: list[dict] = []
        self.tickets: list[dict] = []
        self._vec = TfidfVectorizer(stop_words="english")
        self._m = self._vec.fit_transform([f["q"] + " " + f["a"] for f in self.faq])

    # -- tools
    def get_order(self, customer: str, order_id: str) -> dict:
        o = self.orders.get(order_id.upper())
        if not o or o["customer"] != customer:
            return {"error": "order_not_found"}  # same answer for 'missing' and 'not yours'
        return {"order_id": order_id.upper(), **o}

    def search_faq(self, query: str) -> dict:
        sims = (self._m @ self._vec.transform([query]).T).toarray().ravel()
        i = int(sims.argmax())
        if sims[i] < 0.12:
            return {"found": False}
        return {"found": True, "answer": self.faq[i]["a"], "question": self.faq[i]["q"]}

    def request_refund(self, customer: str, order_id: str) -> dict:
        o = self.get_order(customer, order_id)
        if "error" in o:
            return o
        if o["status"] != "delivered":
            return {"approved": False, "reason": "not_delivered"}
        if o["delivered_days_ago"] > REFUND_WINDOW_DAYS:
            return {"approved": False, "reason": "outside_window"}
        if o["total"] > HUMAN_APPROVAL_OVER:
            return {"approved": False, "reason": "needs_human"}
        self.refunds.append({"customer": customer, "order_id": o["order_id"], "amount": o["total"]})
        return {"approved": True, "amount": o["total"]}

    def escalate(self, customer: str, reason: str) -> dict:
        t = {"id": len(self.tickets) + 1, "customer": customer, "reason": reason}
        self.tickets.append(t)
        return {"ticket_id": t["id"]}
