"""The bounded action set the agent is allowed to choose from, plus a simulated executor.

The agent (LLM) never gets to invent an action - it must pick one of these names.
That's what makes the "bounded and gated" language in the brief real rather than
aspirational: the action space is a closed enum, not free-form tool use.

`execute` simulates the outcome (real Razorpay payment-link / retry calls can replace
the retry_at / send_payment_link branches later without touching the pipeline or
guardrail logic).
"""
import random

ACTION_SET = {
    "retry_at",
    "send_payment_link",
    "send_update_method_link",
    "personalized_reminder",
    "mark_promise_to_pay",
    "escalate_to_human",
    "stop_no_action",
}

# Rough outcome probabilities per action, used only to drive the simulated demo run.
_OUTCOME_WEIGHTS = {
    "retry_at": [("paid", 0.55), ("failed_again", 0.35), ("no_response", 0.10)],
    "send_payment_link": [("paid", 0.40), ("promised", 0.20), ("ignored", 0.40)],
    "send_update_method_link": [("paid", 0.30), ("promised", 0.25), ("ignored", 0.45)],
    "personalized_reminder": [("paid", 0.25), ("promised", 0.30), ("ignored", 0.45)],
    "mark_promise_to_pay": [("promise_kept", 0.60), ("promise_broken", 0.40)],
    "escalate_to_human": [("queued_for_human", 1.0)],
    "stop_no_action": [("no_action_taken", 1.0)],
}

# Rough real-world cost per action, in INR - gateway fees for retries, message costs
# for automated channels, and an estimated labor cost for a human touching the case.
# Used by the cost-aware guardrail (agent.guardrails) to avoid spending disproportionate
# effort recovering a small amount - a lookup table has no notion of this tradeoff at all.
ACTION_COST_INR = {
    "retry_at": 2,
    "send_payment_link": 3,
    "send_update_method_link": 3,
    "personalized_reminder": 1,
    "mark_promise_to_pay": 0,
    "escalate_to_human": 180,
    "stop_no_action": 0,
}


def recovery_probability(action: str) -> float:
    """Probability this action actually results in recovered money, taken from the
    same weights used to simulate outcomes - the expected-value estimate behind the
    cost-aware guardrail, not just "does this action fire".
    """
    weights = dict(_OUTCOME_WEIGHTS[action])
    return weights.get("paid", weights.get("promise_kept", 0.0))


def execute(case: dict, action: str, use_real_razorpay: bool = False) -> dict:
    if action not in ACTION_SET:
        raise ValueError(f"'{action}' is not in the bounded ACTION_SET")

    outcomes, weights = zip(*_OUTCOME_WEIGHTS[action])
    outcome = random.choices(outcomes, weights=weights, k=1)[0]
    recovered = case["amount_inr"] if outcome in ("paid", "promise_kept") else 0.0

    result = {
        "action": action,
        "outcome": outcome,
        "amount_recovered": recovered,
        "razorpay_link_url": None,
        "razorpay_link_id": None,
    }

    # send_payment_link gets a real (test-mode, sandboxed - no real money moves) Razorpay
    # payment link. We still simulate whether it gets paid, since there's no real
    # customer behind the synthetic data to actually click it - but the link itself
    # is genuine, not a placeholder, and could be opened and paid with Razorpay's test
    # card numbers to prove the whole loop for real.
    if use_real_razorpay and action == "send_payment_link":
        from . import razorpay_client
        try:
            link = razorpay_client.create_payment_link(case)
            result["razorpay_link_url"] = link["short_url"]
            result["razorpay_link_id"] = link["payment_link_id"]
        except Exception as e:
            result["razorpay_link_url"] = f"[razorpay call failed: {razorpay_client.friendly_error(e)}]"

    return result


# Same "will they actually pay" probability used for mark_promise_to_pay, reused here
# so any action that results in a "promised" outcome (send_payment_link,
# send_update_method_link, personalized_reminder) can be followed up and resolved.
_PROMISE_OUTCOME_WEIGHTS = _OUTCOME_WEIGHTS["mark_promise_to_pay"]


def resolve_promise(case: dict) -> dict:
    """Simulate whether a customer's promise-to-pay was honored by its due date."""
    outcomes, weights = zip(*_PROMISE_OUTCOME_WEIGHTS)
    outcome = random.choices(outcomes, weights=weights, k=1)[0]
    recovered = case["amount_inr"] if outcome == "promise_kept" else 0.0

    return {"outcome": outcome, "amount_recovered": recovered}
