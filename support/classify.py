"""Intent classification. Default: deterministic keyword scoring (no LLM, no cost).
Gemini classifier is selected with CLASSIFIER=llm and GEMINI_API_KEY; it falls back to the rules on any error."""

import os
import re

INTENTS = ["order_status", "refund", "faq", "human", "greeting"]
RULES = {
    "human": [
        "human",
        "real person",
        "manager",
        "supervisor",
        "complaint",
        "complain",
        "lawyer",
        "speak to someone",
        "talk to someone",
    ],
    "refund": [
        "refund",
        "money back",
        "reimburse",
        "return this",
        "return my",
        "return it",
        "send it back",
        "cancel and get",
    ],
    "order_status": [
        "where is",
        "where's",
        "status",
        "track",
        "tracking",
        "my order",
        "has it shipped",
        "has my package",
        "has my order",
        "delivery",
        "when will",
        "arrive",
        "delivered yet",
        "order a",
    ],
    "greeting": ["hello", "hi", "hey", "good morning", "good evening", "thanks", "thank you"],
}
ORDER_RE = re.compile(r"\b[Aa]\d{4}\b")


def rule_classify(message: str) -> str:
    m = " " + re.sub(r"[^a-z0-9' ]", " ", message.lower()) + " "
    scores = {
        k: sum(1 for w in ws if (" " + w) in m or w in m and len(w) > 5) for k, ws in RULES.items()
    }
    if scores["human"]:
        return "human"
    if any(w in m for w in (" policy", " policies", " window ")):
        return "faq"  # questions ABOUT the policy are FAQs, not refund requests
    if scores["refund"]:
        return "refund"
    if ORDER_RE.search(message) and not any(
        w in m for w in ("policy", "how long", "how do", "how can")
    ):
        return "order_status"
    if scores["order_status"]:
        return "order_status"
    if scores["greeting"] and len(m.split()) <= 4:
        return "greeting"
    return "faq"


def llm_enabled() -> bool:
    return os.getenv("CLASSIFIER") == "llm" and bool(os.getenv("GEMINI_API_KEY"))


def llm_classify(message: str, on_usage=None) -> str:
    """Gemini classifier. Any failure falls back to the rule classifier."""
    import httpx

    model = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")
    try:
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            timeout=15,
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            json={
                "systemInstruction": {
                    "parts": [
                        {
                            "text": "You classify customer-support messages. Labels: "
                            "order_status (asks where an order is or its status), "
                            "refund (wants money back, return or cancel an order), "
                            "faq (general policy question: shipping, returns, payment, warranty), "
                            "human (wants a person, manager, or is making a complaint or legal threat), "
                            "greeting (hello or thanks only). Reply with exactly one label."
                        }
                    ]
                },
                "contents": [{"role": "user", "parts": [{"text": message}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 12},
            },
        )
        r.raise_for_status()
        j = r.json()
        if on_usage:
            u = j.get("usageMetadata", {})
            on_usage(model, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0))
        label = j["candidates"][0]["content"]["parts"][0]["text"].strip().lower()
        label = re.sub(r"[^a-z_]", "", label)
        if label in INTENTS:
            return label
    except Exception:
        pass
    return rule_classify(message)


def classify(message: str, on_usage=None) -> str:
    if llm_enabled():
        return llm_classify(message, on_usage)
    return rule_classify(message)


PRICES_PER_M = {"gemini-3.1-flash-lite": (0.0, 0.0), "gpt-4o-mini": (0.15, 0.60)}  # free tier; USD per 1M tokens (input, output); check provider pricing before relying on it


def cost_usd(model: str, tin: int, tout: int) -> float:
    pi, po = PRICES_PER_M.get(model, (0.0, 0.0))
    return (tin * pi + tout * po) / 1_000_000
