"""Deterministic rule-based stand-in for agent.llm.diagnose_and_decide.

Same input/output shape as the real Claude call, so the rest of the pipeline
(guardrails, actions, dashboard) can be built and demoed today without an
ANTHROPIC_API_KEY. Swap in agent.llm once a key is available - nothing else changes.

Deliberately does NOT read bank_decline_message - it's the honest "dumb baseline":
failure_code -> root_cause -> action, a lookup table with nothing else. Every
bank_declined case maps to escalate_to_human regardless of severity, which means it
never misses a genuinely compromised card, but it also escalates every routine soft
decline unnecessarily - wasted human review time the free-text-reading agent avoids.
"""

_ROOT_CAUSE_BY_FAILURE_CODE = {
    "technical_timeout": "transient_technical",
    "issuer_down": "transient_technical",
    "insufficient_funds": "insufficient_funds",
    "card_expired": "card_or_mandate_expired",
    "bank_declined": "hard_decline_or_revoked",
    "mandate_revoked": "hard_decline_or_revoked",
    "fraud_suspected": "suspected_fraud",
}

_ACTION_BY_ROOT_CAUSE = {
    "transient_technical": "retry_at",
    "insufficient_funds": "send_payment_link",
    "card_or_mandate_expired": "send_update_method_link",
    "hard_decline_or_revoked": "escalate_to_human",
    "suspected_fraud": "escalate_to_human",
}

_MESSAGE_TEMPLATES = {
    "retry_at": "Hi {name}, aapka payment thoda technical issue ki wajah se fail ho gaya "
                "tha. Hum ise dobara try kar rahe hain.",
    "send_payment_link": "Hi {name}, aapka payment insufficient balance ki wajah se fail "
                          "ho gaya. Yeh raha ek naya link - jab convenient ho, complete kar "
                          "dijiye: [link]",
    "send_update_method_link": "Hi {name}, lagta hai aapka card/mandate expire ho gaya hai. "
                                "Please apna payment method update kar dijiye: [link]",
}


def diagnose_and_decide(case: dict) -> dict:
    root_cause = _ROOT_CAUSE_BY_FAILURE_CODE[case["failure_code"]]
    action = _ACTION_BY_ROOT_CAUSE[root_cause]
    template = _MESSAGE_TEMPLATES.get(action)
    message = template.format(name=case["customer_name"].split()[0]) if template else None

    return {
        "root_cause": root_cause,
        "proposed_action": action,
        "confidence": 0.9,  # fixed - a lookup table has no real notion of uncertainty
        "reasoning": f"[mock] failure_code='{case['failure_code']}' maps to "
                     f"root_cause='{root_cause}', default playbook action='{action}'. "
                     f"(bank_decline_message not read - enum lookup only.)",
        "customer_message": message,
    }
