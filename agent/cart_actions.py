"""Bounded action set for cart/checkout abandonment recovery.

Same "closed enum, not free-form" philosophy as agent.actions - the agent proposes,
it never invents. This action set includes discounting, which is new: it's the first
action in the whole project that spends real merchant margin, not just effort - see
agent.cart_guardrails for the caps that keep it bounded.
"""

CART_ACTION_SET = {
    "send_reminder_no_offer",
    "send_reminder_with_discount",
    "send_reminder_free_shipping",
    "voice_call_high_value",
    "no_action",
}

# Conversion probability per action, used only to simulate the demo outcome when
# there's no real customer behind a synthetic event.
_CONVERSION_WEIGHTS = {
    "send_reminder_no_offer": [("converted", 0.20), ("ignored", 0.80)],
    "send_reminder_with_discount": [("converted", 0.45), ("ignored", 0.55)],
    "send_reminder_free_shipping": [("converted", 0.35), ("ignored", 0.65)],
    "voice_call_high_value": [("converted", 0.55), ("ignored", 0.45)],
    "no_action": [("no_action_taken", 1.0)],
}

# Rough cost per action in INR - message cost for automated channels, an estimated
# cost for a voice call, used by the EV guardrail alongside the discount itself.
CART_ACTION_COST_INR = {
    "send_reminder_no_offer": 1,
    "send_reminder_with_discount": 1,
    "send_reminder_free_shipping": 1,
    "voice_call_high_value": 20,
    "no_action": 0,
}


def simulate_outcome(action: str) -> str:
    import random
    outcomes, weights = zip(*_CONVERSION_WEIGHTS[action])
    return random.choices(outcomes, weights=weights, k=1)[0]
