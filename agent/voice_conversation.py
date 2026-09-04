"""Live turn generator for a real two-way voice call (Twilio ConversationRelay).

Deliberately separate from cart_llm_groq.py: that module does one structured,
single-shot diagnosis per case (JSON tool call, no back-and-forth). This module
generates one short spoken reply at a time in an ongoing conversation - plain
text, no tool schema, tuned for being spoken aloud and interrupted, not read.
"""
from groq import Groq

MODEL = "openai/gpt-oss-120b"

_SYSTEM_PROMPT_TEMPLATE = """You are a warm, brisk voice agent for {store_name}, calling
{customer_name} about their abandoned cart (₹{cart_value:.0f}: {items_summary}).

This is a REAL PHONE CALL, not a chat - the caller is listening, not reading:
- Keep every reply to one, at most two, short sentences. Long replies feel like
  being talked at, not talked to.
- Speak naturally in Hinglish (mixed Hindi/English), the way a helpful support
  agent actually sounds on a call in India - not textbook-formal Hindi, not
  pure English.
- If they agree to complete the order, tell them you're sending a payment link
  now and thank them - don't keep pitching after they've said yes.
- If they're not interested or ask to be left alone, acknowledge it warmly and
  end politely in one line - don't argue or re-pitch.
- Never invent details about the order beyond what's given above.
- {discount_line}

Respond with ONLY the words to say next - no stage directions, no quotes, no
"Agent:" prefix, nothing but the spoken sentence(s).
"""


def build_system_prompt(case_context: dict) -> str:
    items_summary = ", ".join(case_context.get("item_names", [])) or "their cart items"
    discount_pct = case_context.get("discount_pct")
    discount_line = (
        f"You're authorized to offer a {discount_pct}% discount if it helps them decide, "
        f"but only mention it if they hesitate on price - don't lead with it."
        if discount_pct else
        "No discount is authorized for this call - don't offer one."
    )
    return _SYSTEM_PROMPT_TEMPLATE.format(
        store_name=case_context.get("store_name", "Aura Store"),
        customer_name=case_context.get("customer_name", "there"),
        cart_value=case_context.get("cart_value", 0),
        items_summary=items_summary,
        discount_line=discount_line,
    )


def generate_reply(system_prompt: str, history: list[dict]) -> str:
    """history: list of {"role": "user"|"assistant", "content": "..."} turns,
    oldest first. Returns the next thing the agent should say."""
    client = Groq()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system_prompt}] + history,
        max_tokens=120,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()
