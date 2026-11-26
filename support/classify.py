"""Intent classification. Default: deterministic keyword scoring (no LLM, no cost).
LLM classifier (written, NOT run: no API key) is selected with CLASSIFIER=llm."""
import os, re, json

INTENTS = ["order_status", "refund", "faq", "human", "greeting"]
RULES = {
    "human": ["human", "real person", "manager", "supervisor", "complaint", "complain", "lawyer", "speak to someone", "talk to someone"],
    "refund": ["refund", "money back", "reimburse", "return this", "return my", "return it", "send it back", "cancel and get"],
    "order_status": ["where is", "where's", "status", "track", "tracking", "my order", "has it shipped", "has my package", "has my order", "delivery", "when will", "arrive", "delivered yet", "order a"],
    "greeting": ["hello", "hi", "hey", "good morning", "good evening", "thanks", "thank you"],
}
ORDER_RE = re.compile(r"\b[Aa]\d{4}\b")


def rule_classify(message: str) -> str:
    m = " " + re.sub(r"[^a-z0-9' ]", " ", message.lower()) + " "
    scores = {k: sum(1 for w in ws if (" " + w) in m or w in m and len(w) > 5) for k, ws in RULES.items()}
    if scores["human"]:
        return "human"
    if any(w in m for w in (" policy", " policies", " window ")):
        return "faq"  # questions ABOUT the policy are FAQs, not refund requests
    if scores["refund"]:
        return "refund"
    if ORDER_RE.search(message) and not any(w in m for w in ("policy", "how long", "how do", "how can")):
        return "order_status"
    if scores["order_status"]:
        return "order_status"
    if scores["greeting"] and len(m.split()) <= 4:
        return "greeting"
    return "faq"


def llm_classify(message: str, on_usage=None) -> str:  # pragma: no cover - needs API key
    import httpx
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=30,
                   headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                   json={"model": model, "temperature": 0, "messages": [
                       {"role": "system", "content": "Classify the customer message into exactly one of: " + ", ".join(INTENTS) + ". Reply with the label only."},
                       {"role": "user", "content": message}]})
    r.raise_for_status()
    j = r.json()
    if on_usage:
        on_usage(model, j["usage"]["prompt_tokens"], j["usage"]["completion_tokens"])
    label = j["choices"][0]["message"]["content"].strip().lower()
    return label if label in INTENTS else "faq"


def classify(message: str, on_usage=None) -> str:
    if os.getenv("CLASSIFIER") == "llm" and os.getenv("OPENAI_API_KEY"):
        return llm_classify(message, on_usage)
    return rule_classify(message)


PRICES_PER_M = {"gpt-4o-mini": (0.15, 0.60)}  # USD per 1M tokens (input, output); check provider pricing before relying on it


def cost_usd(model: str, tin: int, tout: int) -> float:
    pi, po = PRICES_PER_M.get(model, (0.0, 0.0))
    return (tin * pi + tout * po) / 1_000_000
