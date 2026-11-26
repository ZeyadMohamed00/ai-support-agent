"""Tools: the only way the agent touches data. They enforce authorization and business rules themselves."""

import json
import random
import re
import time
from pathlib import Path

from .db import Order, ToolLog

FAQ = json.loads((Path(__file__).resolve().parent.parent / "data" / "faq.json").read_text())
REFUND_WINDOW_DAYS = 30
HUMAN_APPROVAL_OVER = 200.0
STOP = set("a an the of to in on for and or is are do does how what i you my can your it".split())
words = lambda s: {w for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP}


class TransientError(Exception):
    """A failure worth retrying (network blip, DB timeout)."""


def with_retry(fn, *, attempts=3, base_delay=0.05):
    """Run fn, retrying TransientError with exponential backoff. Returns (result, attempts_used)."""
    for i in range(1, attempts + 1):
        try:
            return fn(), i
        except TransientError:
            if i == attempts:
                raise
            time.sleep(base_delay * 2 ** (i - 1))


def logged(db, client_id, conv_id, tool, args, fn, fault_rate=0.0, rng=random.random):
    """Call a tool with retry + audit log. A permanent failure is logged and returned as an error result."""
    t0 = time.perf_counter()
    attempts, ok = 1, True

    def call():
        if fault_rate and rng() < fault_rate:
            raise TransientError("simulated transient failure")
        return fn()

    try:
        result, attempts = with_retry(call)
    except TransientError as e:
        result, ok, attempts = {"error": "tool_unavailable", "detail": str(e)}, False, 3
    db.add(
        ToolLog(
            client_id=client_id,
            conversation_id=conv_id,
            tool=tool,
            args=json.dumps(args),
            result=json.dumps(result),
            attempts=attempts,
            ok=ok and "error" not in result,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
    )
    db.commit()
    return result


def get_order(db, client_id, customer, order_no):
    o = db.query(Order).filter_by(client_id=client_id, order_no=order_no.upper()).first()
    if not o or o.customer != customer:
        return {"error": "order_not_found"}  # identical answer for missing and not-yours
    return {
        "order_no": o.order_no,
        "status": o.status,
        "total": o.total,
        "items": o.items,
        "delivered_days_ago": o.delivered_days_ago,
        "eta_days": o.eta_days,
        "refunded": o.refunded,
    }


def search_faq(query):
    q = words(query)
    best, score = None, 0.0
    for f in FAQ:
        d = words(f["q"] + " " + f["a"])
        s = len(q & d) / (len(q) or 1)
        if s > score:
            best, score = f, s
    return (
        {"found": True, "question": best["q"], "answer": best["a"]}
        if best and score >= 0.34
        else {"found": False}
    )


def check_refund(db, client_id, customer, order_no):
    o = get_order(db, client_id, customer, order_no)
    if "error" in o:
        return o
    if o["refunded"]:
        return {"eligible": False, "reason": "already_refunded"}
    if o["status"] != "delivered":
        return {"eligible": False, "reason": "not_delivered"}
    if o["delivered_days_ago"] > REFUND_WINDOW_DAYS:
        return {"eligible": False, "reason": "outside_window"}
    return {
        "eligible": True,
        "amount": o["total"],
        "needs_human": o["total"] > HUMAN_APPROVAL_OVER,
        "order_no": o["order_no"],
    }


def execute_refund(db, client_id, customer, order_no):
    r = check_refund(db, client_id, customer, order_no)  # re-validate: never trust an earlier check
    if not r.get("eligible"):
        return r
    db.query(Order).filter_by(client_id=client_id, order_no=order_no.upper()).update(
        {"refunded": True}
    )
    db.commit()
    return {"refunded": True, "amount": r["amount"], "order_no": r["order_no"]}
