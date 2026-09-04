"""LLM-backed interpreter for a customer's free-text reply to an outreach message.

This is the piece that a keyword baseline (agent.reply_rules_baseline) structurally
cannot match: understanding a paraphrased claim ("mera card kisi aur ne use kiya
lagta hai" - no "fraud" keyword anywhere) as a dispute, and resolving a relative
date ("agle Monday tak", "salary ayegi 1st ko") against today's date - not pattern
matching a fixed string list.

A dispute_fraud_claim verdict is treated as a hard signal by agent.guardrails: it
halts all further automated contact on the case, regardless of what the earlier
recovery-action decision was.
"""
import json
from datetime import date

from groq import Groq

MODEL = "openai/gpt-oss-120b"

_SYSTEM_PROMPT = """You are reading a customer's free-text reply (often Hinglish -
mixed Hindi/English) to a payment-recovery outreach message. Classify their intent
and, if they committed to a date, resolve it to an actual calendar date.

Intents:
- promise_to_pay: they committed to paying, with or without a specific date.
- dispute_fraud_claim: they are saying THIS SPECIFIC CHARGE is not theirs /
  unauthorized / they don't recognize it - even if they never use the words "fraud"
  or "dispute". Read for the underlying claim, not specific vocabulary - e.g. "mera
  card kisi aur ne use kiya lagta hai" (seems like someone else used my card) IS a
  dispute claim.
- wrong_number: they say the message itself reached the wrong person entirely - they
  don't have any account/subscription with us at all, not just disputing one charge.
  Distinct from dispute_fraud_claim: a dispute is "I have an account but didn't make
  THIS charge"; wrong_number is "I don't have any relationship with you at all."
- claims_already_paid: they say they already paid.
- refuses_hostile: they're refusing to engage or asking to stop contact, without
  disputing the charge itself.
- unclear: none of the above fits (off-topic, ambiguous, or too little information).

If intent is promise_to_pay and they gave any time reference (a weekday, "next week",
"salary ayegi 1st ko", "kal", "is weekend"), resolve it to a YYYY-MM-DD date using
today's date as the reference point. If no time reference was given, leave it null.

Respond only by calling the submit_interpretation tool.
"""

_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_interpretation",
        "description": "Submit the classified intent and any resolved promise date.",
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [
                        "promise_to_pay",
                        "dispute_fraud_claim",
                        "wrong_number",
                        "claims_already_paid",
                        "refuses_hostile",
                        "unclear",
                    ],
                },
                "extracted_promise_date": {
                    "type": ["string", "null"],
                    "description": "YYYY-MM-DD if a date was resolved, else null.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "One sentence explaining the classification.",
                },
            },
            "required": ["intent", "extracted_promise_date", "reasoning"],
        },
    },
}


def interpret(reply_text: str, today: date | None = None) -> dict:
    today = today or date.today()
    client = Groq()

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Today's date: {today.isoformat()}\n\n"
                                         f"Customer reply: \"{reply_text}\""},
        ],
        tools=[_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_interpretation"}},
    )

    message = response.choices[0].message
    if not message.tool_calls:
        raise RuntimeError("Groq did not return a submit_interpretation tool call")

    return json.loads(message.tool_calls[0].function.arguments)
