"""Groq-backed diagnosis + decision step - free-tier drop-in for agent.llm.

Same input/output contract as agent.llm.diagnose_and_decide, so it's a straight swap
in pipeline.py. Uses openai/gpt-oss-120b on Groq's free plan (llama-3.3-70b-versatile
was deprecated by Groq in June 2026; this is their recommended replacement).

Free plan limits for this model (check console.groq.com/docs/models for current
numbers - these move): 30 RPM, 1K requests/day, 8K tokens/min, 200K tokens/day.
At ~700 tokens/case that's roughly 4-5 full 60-case batch runs per day, and callers
should pace requests to stay under 8K TPM - see PACING_SECONDS below and how
agent.pipeline uses it for the --live-groq path.
"""
import json

from groq import Groq

from .actions import ACTION_SET

MODEL = "openai/gpt-oss-120b"

# Stay under the 8K tokens/min free-tier cap at ~700 tokens/request.
PACING_SECONDS = 5.5

# Fields the model should never see: ground-truth labels planted for scoring
# (would make the diagnosis trivial), and fields owned by a different stage.
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
Reflect genuine uncertainty in the score rather than defaulting to a high number.

Respond only by calling the submit_decision tool. Always call it, even if unsure - pick
your best judgment call and let the confidence score carry the uncertainty.
"""

_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_decision",
        "description": "Submit the root-cause diagnosis and proposed recovery action for this case.",
        "parameters": {
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
    },
}


def diagnose_and_decide(case: dict) -> dict:
    client = Groq()  # reads GROQ_API_KEY from env
    case_for_model = {k: v for k, v in case.items() if k not in _HIDDEN_FIELDS}

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(case_for_model, indent=2)},
        ],
        tools=[_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_decision"}},
    )

    message = response.choices[0].message
    if not message.tool_calls:
        raise RuntimeError("Groq did not return a submit_decision tool call")

    return json.loads(message.tool_calls[0].function.arguments)
