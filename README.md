# AI Customer Support Agent (tool-calling, with guardrails)

A support agent for an online shop. It answers FAQs, looks up orders, issues refunds under business rules, and escalates to a human. The interesting part is not the chat, it is **how the agent is kept safe**: it can only call a fixed set of tools, those tools enforce the rules, and every call is logged.

> Honest scope
> - The default "brain" is **rule-based** (keyword intents), so the project runs offline and is fully tested. An `LLMBrain` using OpenAI-style function calling is included, but it was **never run** (no API key available). Treat it as untested.
> - Data is a small JSON file (4 orders, 5 FAQs), not a real database. The API takes the customer from an `X-Customer` header, which is a **demo shortcut**: in production the identity must come from authentication.
> - Docker files were **not built or run** (Docker unavailable). Tests were run locally on Python 3.10.

## Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                          # 10 tests
uvicorn agent.api:app --reload
curl -X POST localhost:8000/chat -H 'X-Customer: sara@example.com' \
  -H 'Content-Type: application/json' -d '{"message":"where is order A1002"}'
```

## Architecture
```
message -> Brain.decide() -> {tool, args} -> allow-list check -> Store tool (enforces rules) -> reply
                                                        \-> audit log (agent.log)
```
- `agent/brain.py`: decides the tool (RuleBrain or LLMBrain, same interface).
- `agent/tools.py`: `get_order`, `search_faq` (TF-IDF), `request_refund`, `escalate`.
- `agent/agent.py`: orchestration, allow-list, conversation state, wording of replies.

## How it works / key decisions
1. **Brain vs tools split**: the brain only *proposes* an action; the tools *decide* what is allowed. Even a confused or manipulated LLM cannot refund a 45-day-old order, because `request_refund` checks the rules itself.
2. **Allow-list guardrail**: any tool name outside the list is replaced with an escalation (`test_guardrail_blocks_invented_tools`).
3. **Authorization**: tools take the customer from the session, not from the message, and return the same "not found" for missing and not-yours orders, so nothing leaks (`test_cannot_read_other_customers_order`).
4. **Business rules in code**: refund only if delivered, within 30 days, and a human must approve orders over 200 dollars (the agent opens a ticket).
5. **Memory and fallbacks**: it remembers the last order in the conversation ("refund it"), asks for the order number when missing, and escalates when it has no answer instead of guessing.

## Limitations / next steps
Real database and auth, multi-turn LLM planning, evaluation on real conversations, prompt-injection tests for the LLM path, rate limits.

## Interview questions to prepare
Why not let the LLM call tools directly with no allow-list? Where must authorization live? How would you test an LLM-based agent deterministically? What is prompt injection and how does this design limit its impact?

## CI
A GitHub Actions workflow is in `ci/github-actions-ci.yml`. Move it to `.github/workflows/ci.yml` to enable it. It is not enabled because the push token had no `workflow` scope, and it has not been run on GitHub.
