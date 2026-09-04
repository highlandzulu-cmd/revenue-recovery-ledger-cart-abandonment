"""Deterministic abandonment_stage -> action baseline for the cart-recovery agent.

Same purpose as agent.reply_rules_baseline: not part of the live decision path
(cart_llm_groq is), it exists purely so the admin feed can show what a simple
if/else rules engine would have done next to what the AI actually did. This is
the same evidentiary pattern already proven on the failed-payment agent, applied
to the second agent in the project.

The baseline is deliberately naive about one thing on purpose: it maps
otp_pending -> a discount, same as payment_page_opened, because a stage-only
lookup has no way to know an OTP stall is a friction problem, not price
hesitation. That's exactly the case where cart_llm_groq's live diagnosis
(reads abandonment_stage semantics, not just the label) should visibly diverge
from it - the same "reads context, not the enum" story as the bank-decline-text
diagnosis, on a different signal.
"""
_STAGE_ACTION = {
    "cart_only": "no_action",
    "checkout_started": "send_reminder_no_offer",
    "payment_page_opened": "send_reminder_with_discount",
    "otp_pending": "send_reminder_with_discount",
}

_BASELINE_DISCOUNT_PCT = 10


def decide(case: dict) -> dict:
    """Minimal decision shape - proposed_action and a fixed discount guess. No
    reasoning field: a lookup table doesn't have any, which is the point."""
    stage = case.get("abandonment_stage", "checkout_started")
    action = _STAGE_ACTION.get(stage, "send_reminder_no_offer")
    return {
        "proposed_action": action,
        "discount_pct": _BASELINE_DISCOUNT_PCT if action == "send_reminder_with_discount" else None,
    }
