"""The agent as a LangGraph state machine.

start -> (resume? execute_approved) | classify -> route:
   order_status -> reply            refund -> check_refund -> [needs human? -> request_approval -> END]
   faq -> reply                                              [eligible?    -> execute_refund -> END]
   human -> escalate -> END         greeting -> END
A refund over the approval limit STOPS at request_approval. A human approves through the API, which re-enters the
graph at execute_approved. The refund tool re-checks every rule at execution time.
"""

from typing import TypedDict

from langgraph.graph import END, StateGraph

from . import tools as T
from .classify import classify, cost_usd
from .db import Approval, LlmUsage, Message, ToolLog


class State(TypedDict, total=False):
    message: str
    customer: str
    conversation_id: int
    intent: str
    order_no: str | None
    reply: str
    pending_approval_id: int | None
    resume_approval_id: int | None


def _ctx(config):
    c = config["configurable"]
    return c["db"], c["client_id"], c.get("fault_rate", 0.0)


def last_order(db, conv_id):
    for m in reversed(
        db.query(Message).filter_by(conversation_id=conv_id, role="user").order_by(Message.id).all()
    ):
        found = T.re.search(r"\b[Aa]\d{4}\b", m.content)
        if found:
            return found.group(0).upper()
    return None


def entry(state: State):
    return "execute_approved" if state.get("resume_approval_id") else "classify"


def n_classify(state: State, config):
    db, cid, _ = _ctx(config)

    def usage(model, tin, tout):
        db.add(
            LlmUsage(
                client_id=cid,
                conversation_id=state["conversation_id"],
                purpose="classify",
                model=model,
                tokens_in=tin,
                tokens_out=tout,
                cost_usd=cost_usd(model, tin, tout),
            )
        )
        db.commit()

    intent = classify(state["message"], usage)
    found = T.re.search(r"\b[Aa]\d{4}\b", state["message"])
    order_no = found.group(0).upper() if found else last_order(db, state["conversation_id"])
    return {"intent": intent, "order_no": order_no}


def route(state: State):
    return state["intent"]


def n_order_status(state: State, config):
    db, cid, fr = _ctx(config)
    if not state.get("order_no"):
        return {"reply": "Which order? Please give me the order number (for example A1001)."}
    r = T.logged(
        db,
        cid,
        state["conversation_id"],
        "get_order",
        {"order_no": state["order_no"]},
        lambda: T.get_order(db, cid, state["customer"], state["order_no"]),
        fr,
    )
    if r.get("error") == "tool_unavailable":
        return {
            "reply": "Our order system is not responding right now. I could not look that up; please try again shortly."
        }
    if "error" in r:
        return {"reply": f"I could not find order {state['order_no']} on your account."}
    extra = {
        "delivered": f"delivered {r['delivered_days_ago']} days ago",
        "shipped": f"on its way, expected in {r['eta_days']} days",
        "processing": "being prepared",
    }.get(r["status"], r["status"])
    return {
        "reply": f"Order {r['order_no']} ({r['items']}, ${r['total']:.2f}) is {extra}."
        + (" It has been refunded." if r["refunded"] else "")
    }


def n_faq(state: State, config):
    db, cid, fr = _ctx(config)
    r = T.logged(
        db,
        cid,
        state["conversation_id"],
        "search_faq",
        {"query": state["message"]},
        lambda: T.search_faq(state["message"]),
        fr,
    )
    if r.get("found"):
        return {"reply": r["answer"]}
    return {
        "reply": 'I am not sure about that, so I will not guess. Type "talk to a human" and I will open a ticket.'
    }


def n_greeting(state: State, config):
    return {
        "reply": "Hi! I can check an order, handle a refund, or answer questions about shipping and returns."
    }


def n_escalate(state: State, config):
    db, cid, _ = _ctx(config)
    db.add(
        ToolLog(
            client_id=cid,
            conversation_id=state["conversation_id"],
            tool="escalate",
            args="{}",
            result='{"ticket":"opened"}',
            attempts=1,
            ok=True,
        )
    )
    db.commit()
    return {"reply": "I have passed this to a human agent. They will contact you by email."}


def n_check_refund(state: State, config):
    db, cid, fr = _ctx(config)
    if not state.get("order_no"):
        return {
            "reply": "Which order would you like refunded? Please give me the order number.",
            "intent": "refund_need_order",
        }
    r = T.logged(
        db,
        cid,
        state["conversation_id"],
        "check_refund",
        {"order_no": state["order_no"]},
        lambda: T.check_refund(db, cid, state["customer"], state["order_no"]),
        fr,
    )
    if r.get("error") == "tool_unavailable":
        return {
            "reply": "Our order system is not responding right now, so I cannot process a refund yet. Please try again shortly.",
            "intent": "refund_failed",
        }
    if "error" in r:
        return {
            "reply": f"I could not find order {state['order_no']} on your account.",
            "intent": "refund_failed",
        }
    if not r["eligible"]:
        why = {
            "not_delivered": "it has not been delivered yet",
            "outside_window": f"it is outside the {T.REFUND_WINDOW_DAYS}-day refund window",
            "already_refunded": "it was already refunded",
        }[r["reason"]]
        return {"reply": f"I cannot refund {state['order_no']}: {why}.", "intent": "refund_denied"}
    return {"intent": "refund_needs_human" if r["needs_human"] else "refund_ok", "reply": ""}


def after_check(state: State):
    return {"refund_needs_human": "request_approval", "refund_ok": "execute_refund"}.get(
        state["intent"], END
    )


def n_request_approval(state: State, config):
    db, cid, _ = _ctx(config)
    o = T.get_order(db, cid, state["customer"], state["order_no"])
    # One open request per order: asking twice must not queue two approvals for the same refund.
    existing = (
        db.query(Approval)
        .filter_by(client_id=cid, customer=state["customer"], order_no=o["order_no"], status="pending")
        .first()
    )
    if existing:
        return {
            "pending_approval_id": existing.id,
            "reply": f"Refund request #{existing.id} for order {o['order_no']} is already waiting for a human. I will confirm once it is decided.",
        }
    a = Approval(
        client_id=cid,
        conversation_id=state["conversation_id"],
        customer=state["customer"],
        order_no=o["order_no"],
        amount=o["total"],
    )
    db.add(a)
    db.commit()
    db.add(
        ToolLog(
            client_id=cid,
            conversation_id=state["conversation_id"],
            tool="request_approval",
            args=f'{{"order_no":"{o["order_no"]}"}}',
            result=f'{{"approval_id":{a.id}}}',
            attempts=1,
            ok=True,
        )
    )
    db.commit()
    return {
        "pending_approval_id": a.id,
        "reply": f"Refunds over ${T.HUMAN_APPROVAL_OVER:.0f} need a human to approve. I sent request #{a.id} for ${o['total']:.2f} to our team. I will confirm once it is decided.",
    }


def n_execute_refund(state: State, config):
    db, cid, fr = _ctx(config)
    r = T.logged(
        db,
        cid,
        state["conversation_id"],
        "execute_refund",
        {"order_no": state["order_no"]},
        lambda: T.execute_refund(db, cid, state["customer"], state["order_no"]),
        fr,
    )
    if r.get("refunded"):
        return {"reply": f"Done. I refunded ${r['amount']:.2f} for order {r['order_no']}."}
    return {"reply": "The refund could not be completed. A human will follow up."}


def n_execute_approved(state: State, config):
    db, cid, fr = _ctx(config)
    a = db.get(Approval, state["resume_approval_id"])
    r = T.logged(
        db,
        cid,
        a.conversation_id,
        "execute_refund",
        {"order_no": a.order_no, "approval_id": a.id},
        lambda: T.execute_refund(db, cid, a.customer, a.order_no),
        fr,
    )
    if r.get("refunded"):
        return {
            "reply": f"Good news: a human approved your refund. ${r['amount']:.2f} for order {a.order_no} has been refunded.",
            "conversation_id": a.conversation_id,
        }
    return {
        "reply": "The approved refund could not be completed; the team will follow up.",
        "conversation_id": a.conversation_id,
    }


def build():
    g = StateGraph(State)
    for name, fn in [
        ("classify", n_classify),
        ("order_status", n_order_status),
        ("faq", n_faq),
        ("greeting", n_greeting),
        ("escalate", n_escalate),
        ("check_refund", n_check_refund),
        ("request_approval", n_request_approval),
        ("execute_refund", n_execute_refund),
        ("execute_approved", n_execute_approved),
    ]:
        g.add_node(name, fn)
    g.set_conditional_entry_point(
        entry, {"classify": "classify", "execute_approved": "execute_approved"}
    )
    g.add_conditional_edges(
        "classify",
        route,
        {
            "order_status": "order_status",
            "refund": "check_refund",
            "faq": "faq",
            "human": "escalate",
            "greeting": "greeting",
        },
    )
    g.add_conditional_edges(
        "check_refund",
        after_check,
        {"request_approval": "request_approval", "execute_refund": "execute_refund", END: END},
    )
    for n in (
        "order_status",
        "faq",
        "greeting",
        "escalate",
        "request_approval",
        "execute_refund",
        "execute_approved",
    ):
        g.add_edge(n, END)
    return g.compile()


GRAPH = build()
