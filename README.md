# AI Customer Support Agent (LangGraph, tool calling, human approval)

A support agent for an online shop: answers FAQs, looks up orders, issues refunds under business rules, asks a human to approve large refunds, and escalates. FastAPI + LangGraph + PostgreSQL + React/TypeScript.

**Live demo (free tier):** https://support-web-green.vercel.app  (click a suggestion, e.g. "I want a refund for A1005", then Approve in the queue)
API docs: https://support-api-liard.vercel.app/docs

![customer chat with orders and approval panel](docs/screenshot-chat.png)

Pages: Customer chat, Orders, Approval queue (refunds over $200 need a human), Tool log and cost, Classifier accuracy, How it works, with dark mode.

## System overview
```mermaid
flowchart TD
  M[Customer message] --> CL{Classify intent}
  CL -->|order status| OS[get_order]
  CL -->|faq| FQ[search_faq]
  CL -->|refund| CR[check_refund]
  CL -->|other| ES[escalate]
  CR -->|over limit| AP[request_approval: human decides]
  CR -->|eligible| EX[execute_refund]
  AP -->|approved| EA[execute_approved]
  OS & FQ & EX & EA & ES --> LOG[(PostgreSQL: messages, tool logs, approvals)]
```

**Tech stack:** LangGraph, FastAPI, PostgreSQL, React, TypeScript, Pytest, Docker.

## Architecture
```
classify -> order_status | faq | greeting | escalate
         -> check_refund -> needs human?  -> request_approval -> END  (human decides via API)
                         -> eligible?     -> execute_refund  -> END
resume (after approval) -> execute_approved -> END
```
- `support/graph.py`: the LangGraph state machine above (conditional entry point lets an approval re-enter the graph).
- `support/tools.py`: tools that enforce authorization and business rules, with retry + audit logging.
- `support/classify.py`: intent classifier (rules by default; LLM classifier written but not run) and cost tracking.
- `support/db.py`: PostgreSQL models: orders, conversations, messages, tool logs, approvals, LLM usage.
- Each visitor gets their own private copy of the synthetic orders (keyed by a browser id), so demos never collide.

## What is implemented
Tool calling (get_order, search_faq, check_refund, execute_refund, escalate), multi-step workflow, **human approval** (refund over $200 stops at `request_approval`, nothing happens until a human approves; a rejected request never refunds), **retry with exponential backoff** (3 tries, then a graceful message, all logged), conversation history in Postgres, per-call tool log with attempts and latency, LLM **cost tracking** table and endpoint, and a classification accuracy evaluation.

## Honest status
- **No LLM is used in the deployed demo.** The classifier is rule-based. The LLM classifier (`CLASSIFIER=llm` + `OPENAI_API_KEY`) and its token/cost tracking are written but were **never run**. The usage panel shows 0 calls / $0 for that reason; the price table is an assumption to verify against the provider.
- LangGraph is real and used (`langgraph` 1.x), but I did not use its checkpointer or `interrupt`; approval state is stored in my own `sup_approvals` table and resumes through a second graph entry. Redis is not used.
- Replies are templates, not generated text. The customer identity comes from an `X-Customer` header: a **demo shortcut**. In production it must come from authentication.
- Docker files are not verified (no Docker in the build environment). The live demo shares a free Neon database (tables prefixed `sup_`).

## Evaluation (real run, `python eval/run_eval.py`)
Intent classification of 63 labeled messages (`eval/classification_set.json`, written by the project author, not independent).
- First run: accuracy **0.937** (4 errors).
- After I fixed two rule gaps ("refund policy" questions are FAQs, not refund requests; "has my package shipped" is order status): accuracy **0.984** (1 error: "how fast is express delivery" is predicted order_status, true label faq).
- **The 0.984 is tuned on this same set, so it is optimistic.** Treat 0.937 as the untuned figure. Results in `eval/results.json`. The LLM classifier is not evaluated.

## Run
```bash
pip install -r requirements.txt pgserver
DATABASE_URL=postgresql+psycopg2://user:pw@host/db uvicorn support.main:app
cd frontend && npm i && npm run dev
pytest          # 14 tests on an embedded real PostgreSQL; frontend: cd frontend && npm test (2 tests)
python eval/run_eval.py
```

## 5 things to understand to explain this project
1. **The brain proposes, the tools decide.** Business rules (30-day window, delivered only, $200 approval, not-already-refunded) live in code, so even a manipulated classifier cannot break them. `execute_refund` re-checks everything at execution time.
2. **Graph = explicit workflow.** Each step is a node, routing is conditional edges, so behavior is inspectable and testable instead of hidden in a prompt.
3. **Human-in-the-loop**: the graph stops at `request_approval`; approval resumes it through a different entry point; double-approving returns 409.
4. **Reliability**: transient tool failures retry with backoff; permanent failure becomes a clear message plus a log row (`test_total_tool_outage_is_handled_and_logged`).
5. **Authorization and honesty**: the same "not found" answer for missing and not-yours orders (no data leak); and the evaluation numbers above say exactly how they were produced.
