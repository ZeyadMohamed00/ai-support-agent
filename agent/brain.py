"""The 'brain' decides which tool to call. Two interchangeable implementations:
- RuleBrain: deterministic intent rules (default, runs offline, fully tested).
- LLMBrain: OpenAI-compatible function calling (needs LLM_API_KEY; written but NOT run/tested here).
"""
import os, re, json

ORDER_RE = re.compile(r"\b[Aa]\d{4}\b")


class RuleBrain:
    def decide(self, message: str, state: dict) -> dict:
        m = message.lower()
        order = ORDER_RE.search(message)
        oid = order.group(0).upper() if order else state.get("last_order")
        if any(w in m for w in ("human", "agent", "manager", "complain", "lawyer")):
            return {"tool": "escalate", "args": {"reason": message[:200]}}
        if any(w in m for w in ("refund", "money back", "return")):
            return {"tool": "request_refund", "args": {"order_id": oid}} if oid else {"tool": "ask", "args": {"need": "order_id"}}
        if any(w in m for w in ("where", "status", "track", "order")) and (oid or "order" in m):
            return {"tool": "get_order", "args": {"order_id": oid}} if oid else {"tool": "ask", "args": {"need": "order_id"}}
        return {"tool": "search_faq", "args": {"query": message}}


class LLMBrain:
    TOOLS = [
        {"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object", "properties": p, "required": list(p)}}}
        for n, d, p in [
            ("get_order", "Look up an order", {"order_id": {"type": "string"}}),
            ("request_refund", "Refund a delivered order", {"order_id": {"type": "string"}}),
            ("search_faq", "Search help articles", {"query": {"type": "string"}}),
            ("escalate", "Hand over to a human", {"reason": {"type": "string"}}),
        ]
    ]

    def decide(self, message: str, state: dict) -> dict:
        import httpx
        r = httpx.post(
            os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1") + "/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
            json={"model": os.environ.get("LLM_MODEL", "gpt-4o-mini"), "temperature": 0, "tools": self.TOOLS,
                  "messages": [{"role": "system", "content": "You are a support agent. Pick one tool."},
                               {"role": "user", "content": message}]},
            timeout=60)
        r.raise_for_status()
        calls = r.json()["choices"][0]["message"].get("tool_calls")
        if not calls:
            return {"tool": "search_faq", "args": {"query": message}}
        c = calls[0]["function"]
        return {"tool": c["name"], "args": json.loads(c["arguments"])}
