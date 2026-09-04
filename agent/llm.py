"""Claude-backed diagnosis + decision step.

Given a failed-payment case, ask Claude to (1) classify the root cause by reading the
raw bank_decline_message (not just the failure_code enum), (2) propose one action from
the bounded ACTION_SET, (3) report a confidence score, and (4) draft the customer-facing
message if the action involves contact. `agent.guardrails` has final say over whether the
proposed action is actually allowed to run - this module only proposes.
"""
import json

from anthropic import Anthropic

from .actions import ACTION_SET

MODEL = "claude-sonnet-5"

_HIDDEN_FIELDS = {"customer_id", "customer_reply", "true_reply_intent", "true_bank_message_severity"}

_SYSTEM_PROMPT = f"""You are a revenue-recovery agent for a payments company. You are given
one failed recurring payment case (subscription/mandate/card).

The most important signal is `bank_decline_message` - the actual raw text the bank or
payment gateway sent back. Do NOT rely on `failure_code` alone: it is a coarse category
that can hide very different real situations. In particular, failure_code=bank_declined
covers both routine, retry-safe declines (e.g. "Do not honor", "temporary hold") AND
card-compromise situations (e.g. "reported lost or stolen", "restricted card",
"suspected compromised card") where retrying or contacting the customer about payment is
the wrong move entirely - read the actual message to tell these apart.

Diagnose the root cause by reading bank_decline_message (not just failure_code), then
propose exactly one recovery action from this fixed set: {sorted(ACTION_SET)}.

Rules of thumb (a separate guardrail layer enforces the hard version of these strictly -
you don't need to be perfect, but reason like this):
- If bank_decline_message indicates the card/mandate is compromised, lost, stolen, or
  restricted for suspected unauthorized use, set root_cause=card_compromised and propose
  escalate_to_human - never retry_at or any customer contact action, regardless of what
  failure_code says.
- If the customer has already ignored multiple prior contacts, don't propose another
  automated nudge - propose escalate_to_human.
- Prefer retry_at for transient/technical failures and routine (non-compromised) declines.
- Prefer send_update_method_link for expired cards/mandates.
- Prefer send_payment_link or personalized_reminder for insufficient_funds.
- Use mark_promise_to_pay only if the case already indicates the customer committed to a date.

Also report your confidence (0.0-1.0) in this diagnosis and action choice - lower when
the bank message is ambiguous or conflicts with other signals, higher when it's clear.

Respond only by calling the submit_decision tool.
"""

_TOOL = {
    "name": "submit_decision",
    "description": "Submit the root-cause diagnosis and proposed recovery action for this case.",
    "input_schema": {
        "type": "object",
        "properties": {
            "root_cause": {
                "type": "string",
                "enum": [
                    "transient_technical",
                    "insufficient_funds",
                    "card_or_mandate_expired",
                    "hard_decline_or_revoked",
                    "card_compromised",
                    "suspected_fraud",
                ],
            },
            "proposed_action": {"type": "string", "enum": sorted(ACTION_SET)},
            "confidence": {
                "type": "number",
                "description": "0.0 to 1.0 confidence in this diagnosis and action choice.",
            },
            "reasoning": {
                "type": "string",
                "description": "One or two sentences explaining the diagnosis and choice, "
                                "citing the bank_decline_message where relevant.",
            },
            "customer_message": {
                "type": ["string", "null"],
                "description": "Drafted customer-facing message in Hinglish if the action "
                                "contacts the customer, else null.",
            },
        },
        "required": ["root_cause", "proposed_action", "confidence", "reasoning", "customer_message"],
    },
}


def diagnose_and_decide(case: dict) -> dict:
    client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    case_for_model = {k: v for k, v in case.items() if k not in _HIDDEN_FIELDS}

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=_SYSTEM_PROMPT,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "submit_decision"},
        messages=[{"role": "user", "content": json.dumps(case_for_model, indent=2)}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_decision":
            return block.input

    raise RuntimeError("Claude did not return a submit_decision tool call")
