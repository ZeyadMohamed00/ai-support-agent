import os
from .tools import Store
from .brain import RuleBrain, LLMBrain

ALLOWED = {"get_order", "request_refund", "search_faq", "escalate", "ask"}
REASONS = {
    "not_delivered": "That order has not been delivered yet, so it can't be refunded.",
    "outside_window": "That order was delivered more than 30 days ago, so it is outside the refund window.",
    "needs_human": "Orders over 200 dollars need a human to approve the refund. I've opened a ticket for you.",
}


class SupportAgent:
    """One agent per verified customer. The customer identity comes from the session (auth), never from
    the message text, so a user cannot ask about someone else's order by typing an email."""

    def __init__(self, customer: str, store: Store | None = None, brain=None):
        self.customer, self.store = customer, store or Store()
        self.brain = brain or (LLMBrain() if os.getenv("LLM_API_KEY") else RuleBrain())
        self.state: dict = {}
        self.log: list[dict] = []  # audit trail of tool calls

    def handle(self, message: str) -> str:
        d = self.brain.decide(message, self.state)
        tool, args = d["tool"], d.get("args", {})
        if tool not in ALLOWED:  # guardrail: never run a tool the brain made up
            tool, args = "escalate", {"reason": "unsupported tool requested"}
        self.log.append({"tool": tool, "args": args})
        if tool == "ask":
            return "Could you share your order number (like A1001)?"
        if tool == "search_faq":
            r = self.store.search_faq(args["query"])
            return r["answer"] if r["found"] else self._escalate("no FAQ match: " + message[:100], "I'm not sure about that, so I've passed it to a human.")
        if tool == "escalate":
            return self._escalate(args.get("reason", ""), "I've passed this to a human agent.")
        oid = args.get("order_id")
        if tool == "get_order":
            o = self.store.get_order(self.customer, oid)
            if "error" in o:
                return "I couldn't find that order on your account."
            self.state["last_order"] = o["order_id"]
            extra = f"arrives in {o['eta_days']} days" if o["status"] == "shipped" else ""
            return f"Order {o['order_id']} ({', '.join(o['items'])}) is {o['status']}" + (f", {extra}." if extra else ".")
        if tool == "request_refund":
            r = self.store.request_refund(self.customer, oid)
            if r.get("error"):
                return "I couldn't find that order on your account."
            self.state["last_order"] = oid.upper()
            if r["approved"]:
                return f"Done. I've refunded {r['amount']:.2f} for order {oid.upper()}."
            if r["reason"] == "needs_human":
                self.store.escalate(self.customer, f"refund approval for {oid}")
            return REASONS[r["reason"]]

    def _escalate(self, reason, text):
        t = self.store.escalate(self.customer, reason)
        return f"{text} Ticket #{t['ticket_id']}."
