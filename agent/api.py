from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from .agent import SupportAgent
from .tools import Store

app = FastAPI(title="Support Agent")
store = Store()
sessions: dict[str, SupportAgent] = {}


class Msg(BaseModel):
    message: str


@app.post("/chat")
def chat(body: Msg, x_customer: str = Header(default="")):
    # DEMO ONLY: a real deployment must derive the customer from an authenticated session/JWT.
    if x_customer not in {o["customer"] for o in store.orders.values()}:
        raise HTTPException(401, "unknown customer")
    a = sessions.setdefault(x_customer, SupportAgent(x_customer, store))
    return {"reply": a.handle(body.message), "tool_calls": a.log[-1:]}
