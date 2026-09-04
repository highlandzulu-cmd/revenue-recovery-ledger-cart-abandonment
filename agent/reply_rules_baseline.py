"""Naive keyword-matching baseline for interpreting a customer's free-text reply.

This is the explicit "if/else can do this too" strawman - the honest version of it,
not a weakened one. A real ops team would plausibly ship exactly this list. It exists
so the dashboard can show, concretely, where keyword matching breaks and where an LLM
reading the same text does not - rather than just asserting the LLM is "smarter".
"""

_KEYWORDS = {
    "dispute_fraud_claim": [
        "fraud", "unauthorized", "unauthorised", "dispute", "did not authorize",
        "didn't authorize", "block my card", "block card", "not authorize",
    ],
    "wrong_number": [
        "wrong number", "galat number", "mera koi subscription nahi",
        "no subscription", "don't have an account", "not my account",
    ],
    "claims_already_paid": [
        "already paid", "already pay", "payment done", "ho chuka hai", "kar diya tha",
    ],
    "promise_to_pay": [
        "will pay", "pay kar dunga", "kar dunga payment", "next week", "agle",
        "salary", "weekend tak", "monday tak", "kal tak",
    ],
    "refuses_hostile": [
        "stop messaging", "stop calling", "mat karo", "not interested",
    ],
}


def interpret(reply_text: str) -> dict:
    text = reply_text.lower()

    for intent, keywords in _KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return {
                "intent": intent,
                "extracted_promise_date": None,
                "reasoning": f"[keyword baseline] matched on a configured keyword for '{intent}'.",
            }

    return {
        "intent": "unclear",
        "extracted_promise_date": None,
        "reasoning": "[keyword baseline] no configured keyword matched.",
    }
