import os
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func
from . import db as D
from .graph import GRAPH

CUSTOMERS = {"sara@example.com", "omar@example.com"}


def get_db():
    with D.Session() as s:
        yield s


def client(x_client_id: str = Header(default="")):
    if not (8 <= len(x_client_id) <= 64) or not x_client_id.replace("-", "").isalnum():
        raise HTTPException(400, "Missing or invalid X-Client-Id header")
    return x_client_id


def customer(x_customer: str = Header(default="sara@example.com")):
    # DEMO SHORTCUT: in production the customer comes from authentication, never from a client header.
    if x_customer not in CUSTOMERS:
        raise HTTPException(400, "Unknown demo customer")
    return x_customer


class ChatIn(BaseModel):
    message: str
    conversation_id: int | None = None


class Decision(BaseModel):
    approve: bool


def create_app():
    D.init()
    app = FastAPI(title="AI Customer Support Agent", version="2.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def cfg(db, cid):
        return {"configurable": {"db": db, "client_id": cid, "fault_rate": float(os.getenv("FAULT_RATE", "0"))}}

    @app.get("/health")
    def health():
        return {"status": "ok", "classifier": "llm" if os.getenv("CLASSIFIER") == "llm" and os.getenv("OPENAI_API_KEY") else "rules"}

    @app.post("/chat")
    def chat(body: ChatIn, cid: str = Depends(client), who: str = Depends(customer), db=Depends(get_db)):
        D.ensure_seed(db, cid)
        msg = body.message.strip()
        if not msg or len(msg) > 1000:
            raise HTTPException(422, "Message must be 1-1000 characters")
        conv = db.get(D.Conversation, body.conversation_id) if body.conversation_id else None
        if conv and (conv.client_id != cid or conv.customer != who):
            raise HTTPException(404, "Conversation not found")
        if not conv:
            conv = D.Conversation(client_id=cid, customer=who); db.add(conv); db.commit()
        db.add(D.Message(conversation_id=conv.id, role="user", content=msg)); db.commit()
        out = GRAPH.invoke({"message": msg, "customer": who, "conversation_id": conv.id}, cfg(db, cid))
        db.add(D.Message(conversation_id=conv.id, role="assistant", content=out["reply"], intent=out.get("intent", ""))); db.commit()
        return {"conversation_id": conv.id, "reply": out["reply"], "intent": out.get("intent"), "pending_approval_id": out.get("pending_approval_id")}

    @app.get("/conversations/{conv_id}")
    def conversation(conv_id: int, cid: str = Depends(client), db=Depends(get_db)):
        c = db.get(D.Conversation, conv_id)
        if not c or c.client_id != cid:
            raise HTTPException(404, "Not found")
        return [{"role": m.role, "content": m.content, "intent": m.intent}
                for m in db.query(D.Message).filter_by(conversation_id=conv_id).order_by(D.Message.id)]

    @app.get("/orders")
    def orders(cid: str = Depends(client), who: str = Depends(customer), db=Depends(get_db)):
        D.ensure_seed(db, cid)
        return [{"order_no": o.order_no, "status": o.status, "total": o.total, "items": o.items, "refunded": o.refunded}
                for o in db.query(D.Order).filter_by(client_id=cid, customer=who).order_by(D.Order.order_no)]

    @app.get("/approvals")
    def approvals(cid: str = Depends(client), db=Depends(get_db)):
        return [{"id": a.id, "customer": a.customer, "order_no": a.order_no, "amount": a.amount, "status": a.status}
                for a in db.query(D.Approval).filter_by(client_id=cid).order_by(D.Approval.id.desc())]

    @app.post("/approvals/{aid}/decision")
    def decide(aid: int, body: Decision, cid: str = Depends(client), db=Depends(get_db)):
        a = db.get(D.Approval, aid)
        if not a or a.client_id != cid:
            raise HTTPException(404, "Not found")
        if a.status != "pending":
            raise HTTPException(409, f"Already {a.status}")
        a.status = "approved" if body.approve else "rejected"; db.commit()
        if body.approve:
            out = GRAPH.invoke({"resume_approval_id": a.id}, cfg(db, cid))
            reply = out["reply"]
        else:
            reply = f"A human reviewed refund request #{a.id} for order {a.order_no} and could not approve it. We will email you the details."
        db.add(D.Message(conversation_id=a.conversation_id, role="assistant", content=reply, intent="approval_" + a.status)); db.commit()
        return {"id": a.id, "status": a.status, "message": reply}

    @app.get("/logs")
    def logs(cid: str = Depends(client), db=Depends(get_db)):
        rows = db.query(D.ToolLog).filter_by(client_id=cid).order_by(D.ToolLog.id.desc()).limit(50).all()
        return [{"tool": r.tool, "args": r.args, "result": r.result, "attempts": r.attempts, "ok": r.ok, "latency_ms": r.latency_ms} for r in rows]

    @app.get("/usage")
    def usage(cid: str = Depends(client), db=Depends(get_db)):
        n, tin, tout, cost = db.query(func.count(D.LlmUsage.id), func.coalesce(func.sum(D.LlmUsage.tokens_in), 0),
                                      func.coalesce(func.sum(D.LlmUsage.tokens_out), 0), func.coalesce(func.sum(D.LlmUsage.cost_usd), 0.0)
                                      ).filter(D.LlmUsage.client_id == cid).one()
        return {"llm_calls": n, "tokens_in": int(tin), "tokens_out": int(tout), "cost_usd": round(float(cost), 6),
                "note": "0 calls means the rule-based classifier handled everything (no LLM key configured)" if n == 0 else ""}

    @app.post("/demo/reset", status_code=204)
    def reset(cid: str = Depends(client), db=Depends(get_db)):
        for M in (D.Order, D.Approval, D.ToolLog, D.LlmUsage):
            db.query(M).filter_by(client_id=cid).delete()
        for c in db.query(D.Conversation).filter_by(client_id=cid).all():
            db.delete(c)
        db.commit()

    return app


app = create_app()
