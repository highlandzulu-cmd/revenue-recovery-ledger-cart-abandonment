"""Groq-backed decision step for cart/checkout abandonment.

Same structured tool-calling pattern as agent.llm_groq, adapted for a different
signal set: no failure_code/bank text here, instead the stage the customer reached
before abandoning, which is itself informative (otp_pending usually means friction,
not price hesitation - a discount doesn't fix a friction problem).
"""
import json

from groq import Groq

from .cart_actions import CART_ACTION_SET

MODEL = "openai/gpt-oss-120b"

_SYSTEM_PROMPT = f"""You are a cart-abandonment recovery agent for an e-commerce merchant.
You are given one abandoned cart/checkout event. Diagnose why the customer likely left,
then propose exactly one action from this fixed set: {sorted(CART_ACTION_SET)}.

The abandonment_stage is the most informative signal:
- cart_only: customer never even started checkout - usually just early browsing, often
  not worth aggressive recovery effort.
- checkout_started: engaged but stopped - a plain reminder often works.
- payment_page_opened: got to the price/payment step and stopped - classic price
  hesitation, a discount is more likely to help here.
- otp_pending: got all the way to verification and stalled - usually a friction/delivery
  problem (OTP didn't arrive, etc.), NOT price hesitation. A discount doesn't fix a
  friction problem - a plain reminder or, for a high-value cart, a voice call to help
  them through it is more appropriate than a discount.

contact_count tells you how many times this customer has already been reached out to
about this cart. A separate guardrail layer strictly enforces this, but reason like it
too: contact_count=0 (first touch) should always get send_reminder_no_offer - never a
discount or a voice call on the first nudge, no matter how promising the cart looks.
Discounts and calls are only appropriate once a plain reminder has already gone
unanswered.

Rules of thumb (a separate guardrail layer enforces hard caps on discounts and reserves
voice calls for high-value carts strictly - you don't need to be perfect):
- Prefer send_reminder_no_offer for cart_only or low-value carts, and always on first contact.
- Prefer send_reminder_with_discount for payment_page_opened, price-hesitation cases.
- Prefer voice_call_high_value only for high-value carts stuck at otp_pending or
  payment_page_opened, not for early-stage cart_only abandonment.
- Repeat customers with a strong purchase history need less incentive to convert than
  first-time customers - consider a smaller or no discount for them.
- If discount_pct is proposed, keep it modest (a starting suggestion, not a final
  number - the guardrail layer clamps it).

Also report your confidence (0.0-1.0) in this diagnosis and action choice.

Respond only by calling the submit_decision tool.
"""

_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_decision",
        "description": "Submit the diagnosis and proposed recovery action for this abandoned cart.",
        "parameters": {
            "type": "object",
            "properties": {
                "likely_reason": {
                    "type": "string",
                    "enum": ["early_browsing", "price_hesitation", "checkout_friction", "unclear"],
                },
                "proposed_action": {"type": "string", "enum": sorted(CART_ACTION_SET)},
                "discount_pct": {
                    "type": ["number", "null"],
                    "description": "Suggested discount percentage if proposed_action is "
                                    "send_reminder_with_discount, else null. The guardrail layer "
                                    "enforces the actual cap.",
                },
                "confidence": {
                    "type": "number",
                    "description": "0.0 to 1.0 confidence in this diagnosis and action choice.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "One or two sentences explaining the diagnosis and choice.",
                },
                "customer_message": {
                    "type": "string",
                    "description": "Drafted customer-facing message in Hinglish for this action.",
                },
            },
            "required": [
                "likely_reason", "proposed_action", "discount_pct", "confidence",
                "reasoning", "customer_message",
            ],
        },
    },
}


def diagnose_and_decide(case: dict) -> dict:
    client = Groq()  # reads GROQ_API_KEY from env

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(case, indent=2)},
        ],
        tools=[_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_decision"}},
    )

    message = response.choices[0].message
    if not message.tool_calls:
        raise RuntimeError("Groq did not return a submit_decision tool call")

    return json.loads(message.tool_calls[0].function.arguments)
