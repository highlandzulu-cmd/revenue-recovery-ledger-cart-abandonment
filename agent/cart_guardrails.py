"""Hard-coded caps on the cart-recovery agent's discounting power.

Same philosophy as agent.guardrails: the agent proposes, code has final say. A
discount is the first action in this project that spends real merchant margin by
design, not just effort - these caps exist so a model having a generous day can
never actually cost the merchant more than intended.
"""
from dataclasses import dataclass

from . import cart_actions

MAX_DISCOUNT_PCT = 10
REPEAT_CUSTOMER_MAX_DISCOUNT_PCT = 5  # loyal customers shouldn't learn to expect a deal
OFFER_EXPIRY_MINUTES = 120
MIN_CART_VALUE_FOR_DISCOUNT_INR = 300  # below this, discount cost isn't worth it
VOICE_CALL_MIN_CART_VALUE_INR = 3000  # the AI's own voice_call_high_value proposal is
                                       # allowed to stand at this value or above
VOICE_CALL_FORCE_THRESHOLD_INR = 4000  # at or above this, a call is forced - not just
                                       # allowed if the model happens to propose one


@dataclass
class CartGuardrailResult:
    allowed_action: str
    allowed_discount_pct: float
    overridden: bool
    reason: str


def check(case: dict, decision: dict) -> CartGuardrailResult:
    proposed_action = decision["proposed_action"]
    proposed_discount_pct = decision.get("discount_pct") or 0
    cart_value = case["cart_value"]
    is_repeat = case.get("is_repeat_customer", False)
    contact_count = case.get("contact_count", 0)

    # First contact is always a plain reminder - no discount, no voice call, no
    # exceptions, regardless of cart value or what the model proposes. This is the
    # "less pushy" half of the design: a discount on the very first nudge trains
    # customers to abandon carts on purpose to get a deal, and a voice call on the
    # first touch is just aggressive. Escalation is only earned by a second
    # confirmed non-response, not the first sign of hesitation.
    if contact_count == 0 and proposed_action in ("send_reminder_with_discount", "voice_call_high_value"):
        return CartGuardrailResult(
            allowed_action="send_reminder_no_offer",
            allowed_discount_pct=0,
            overridden=True,
            reason=f"contact_count=0 (first touch); proposed '{proposed_action}' downgraded to "
                   f"a plain reminder - discounts and calls are reserved for a second "
                   f"confirmed non-response, not the first sign of hesitation.",
        )

    # High-value stragglers past the first touch get a call, full stop - not left
    # to whatever the model happens to propose that run. The AI's own diagnosis
    # (why they stalled, what to say) still drives everything else about the
    # case; this only fixes the channel decision itself so it's a deterministic
    # guarantee instead of a maybe, exactly like every other guardrail here.
    if contact_count >= 1 and cart_value >= VOICE_CALL_FORCE_THRESHOLD_INR:
        return CartGuardrailResult(
            allowed_action="voice_call_high_value",
            allowed_discount_pct=0,
            overridden=(proposed_action != "voice_call_high_value"),
            reason=f"cart value Rs{cart_value:.2f} is at or above "
                   f"VOICE_CALL_FORCE_THRESHOLD_INR={VOICE_CALL_FORCE_THRESHOLD_INR} on a repeat "
                   f"contact (contact_count={contact_count}); escalating straight to a call "
                   f"regardless of what was proposed.",
        )

    # Voice calls are reserved for high-value carts - same "high-value stragglers"
    # principle as the original track brief's voice-recovery idea.
    if proposed_action == "voice_call_high_value" and cart_value < VOICE_CALL_MIN_CART_VALUE_INR:
        return CartGuardrailResult(
            allowed_action="send_reminder_with_discount",
            allowed_discount_pct=min(proposed_discount_pct or 5, MAX_DISCOUNT_PCT),
            overridden=True,
            reason=f"voice_call_high_value proposed for a Rs{cart_value:.2f} cart, below "
                   f"VOICE_CALL_MIN_CART_VALUE_INR={VOICE_CALL_MIN_CART_VALUE_INR}; "
                   f"downgraded to a text reminder with a discount instead.",
        )

    if proposed_action != "send_reminder_with_discount":
        return CartGuardrailResult(
            allowed_action=proposed_action,
            allowed_discount_pct=0,
            overridden=False,
            reason="no discount proposed, nothing to cap",
        )

    # Repeat customers get a lower ceiling - a hard rule, not left to model judgment,
    # so the agent can't accidentally train loyal customers to expect a discount
    # every time they hesitate at checkout.
    cap = REPEAT_CUSTOMER_MAX_DISCOUNT_PCT if is_repeat else MAX_DISCOUNT_PCT

    if cart_value < MIN_CART_VALUE_FOR_DISCOUNT_INR:
        return CartGuardrailResult(
            allowed_action="send_reminder_no_offer",
            allowed_discount_pct=0,
            overridden=True,
            reason=f"cart value Rs{cart_value:.2f} is below "
                   f"MIN_CART_VALUE_FOR_DISCOUNT_INR={MIN_CART_VALUE_FOR_DISCOUNT_INR}; "
                   f"discount cost isn't justified, sending a plain reminder instead.",
        )

    if proposed_discount_pct > cap:
        return CartGuardrailResult(
            allowed_action="send_reminder_with_discount",
            allowed_discount_pct=cap,
            overridden=True,
            reason=f"proposed discount {proposed_discount_pct}% exceeds the cap for this "
                   f"customer ({cap}%, {'repeat' if is_repeat else 'new'} customer); "
                   f"clamped to {cap}%.",
        )

    return CartGuardrailResult(
        allowed_action=proposed_action,
        allowed_discount_pct=proposed_discount_pct,
        overridden=False,
        reason="no guardrail triggered",
    )
