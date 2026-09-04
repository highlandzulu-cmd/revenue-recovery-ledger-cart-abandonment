# The Recovery Ledger — talk script

~2.5 min straight through. Cut the bracketed asides if you need it shorter.

---

Every subscription business loses money in two places: people who never finish
checkout, and people whose recurring payment just... fails. Most systems either
ignore both, or throw the exact same generic "your payment failed" message at
everyone. We built something that actually looks at *why*, for both.

That's the Recovery Ledger. Two agents, one system: one catches lost revenue
*before* checkout even completes — cart abandonment — and the other recovers it
*after* a recurring charge fails — subscriptions, UPI AutoPay, cards. Same
architecture both places: an LLM reads the actual signal and diagnoses what's
really going on, hard-coded guardrails always get the final say over what the
AI proposes, and every AI decision gets checked against a naive rules-only
baseline — so we're not just claiming this is smarter, we're measuring it.

[Here's the moment that matters most.] A bank decline code like
`bank_declined` covers two completely different situations — a routine
temporary hold, and a card that's been reported stolen. Same code. A rules
engine can't tell them apart. Ours reads the actual bank message —
*"restricted card, possible unauthorized use"* — and correctly escalates it to
a human instead of retrying a compromised card. We show that disagreement
side-by-side on the dashboard, every time it happens, not just in the pitch.

Same idea on the cart side. Someone stuck at OTP verification and someone
stuck at the payment page look similar on paper, but one's a technical
hiccup and the other's price hesitation — and only one of those should get a
discount. The agent tells them apart from the abandonment stage itself, and
we show a baseline getting it wrong right next to the AI getting it right.

None of this runs unchecked. Guardrails are hard-coded Python, not a prompt
the model could talk itself out of — a compromised card is *always* escalated,
never retried, no matter what the model proposes. A discount can never exceed
its cap. The first contact with anyone is always the gentlest option
available, full stop — no exceptions, because a discount or a phone call on
the very first nudge just trains people to abandon carts on purpose.

[Live moment:] Watch this — I abandon a cart right here, and the recovery
agent doesn't just draft a message, it actually calls me. Real two-way voice,
Twilio ConversationRelay under the hood, and once the call ends I get a real
text with a real, working Razorpay payment link — pay it, and the dashboard
picks that up on its own within five seconds, no refresh, because it's
actually checking Razorpay's API, not just simulating an outcome.

And we're upfront about what's real and what isn't. Live LLM diagnosis: real.
Guardrails: real. Razorpay links: real, live, test-mode. Message and call
dispatch: fully drafted, shown in full, genuinely not transmitted yet — Twilio
trial restrictions blocked that, and we'd rather tell you that plainly than
fake it. That's the whole point of this project: prove the value, don't just
assert it.

---

## Q&A prep — what went wrong, why this matters, what's next

**What broke, and how it got fixed** — real bugs, not hypotheticals:
- A cost-saving guardrail rule was quietly overriding the compliance rule for
  compromised cards — should never happen, found by running a real batch and
  reading the output, not by reading the code. Fixed, and locked in with a
  regression test so it can't come back silently.
- A live model once wrote `"confidence": 0. nine` — looked fine, wasn't valid
  JSON, and used to crash the entire 60-case batch on one bad response. Now
  it retries once and falls back to a safe default, and always says so in the
  log rather than pretending nothing happened.
- Twilio's trial account has no phone number and needs WhatsApp Content
  Template approval for any business-initiated message — genuinely blocked,
  so we built the real two-way voice path (ConversationRelay) anyway and are
  shipping it pending that unlock, rather than faking a "sent" status.
- Razorpay's test mode caps out at 30 payment links per account, hit twice
  tonight from our own testing. Rather than let the demo break on that, it
  now falls back to reusing one of the account's own still-unpaid links —
  still real, still genuinely payable, and labeled honestly as reused.

**Why this is worth building**, not just a hackathon toy:
- Failed recurring payments and cart abandonment are measurable, ongoing
  revenue leaks for every subscription or D2C business on Razorpay — this
  isn't a made-up problem.
- It uses AI exactly where a rules engine genuinely can't — reading
  unstructured text to tell two situations apart that share the same status
  code — and keeps AI *out* of the parts that need to be non-negotiable
  (compliance, spend caps), which is the harder and more honest design choice.
- It fits straight into Razorpay's own surface area: a merchant needs to hand
  over one API key, nothing else, because the whole loop — detect, diagnose,
  act, create the payment link — already runs on Razorpay's own APIs.
- The value isn't just claimed, it's measured inside the product itself —
  every AI decision sits next to what a naive baseline would have done.

**With more time and a production budget:**
- Real WhatsApp/SMS/voice dispatch — needs a paid Twilio number (or MSG91 /
  Meta's WhatsApp Cloud API directly) instead of a trial account.
- Sarvam AI's Hinglish TTS is already wired for the demo call UI — the
  natural next step is using it (or a comparable Indic voice model) for the
  real outbound voice-call path too, not just the browser fallback.
- Multi-tenant onboarding — `/connect` demonstrates the pitch (one Razorpay
  key, nothing else needed); real OAuth and per-merchant guardrail
  configuration is the next build, not a redesign.
- A real automated test suite and concurrent batch processing, for handling
  a merchant's actual case volume instead of a 60-case demo batch.
- Confidence calibration proven at real scale — Groq's free tier caps daily
  volume, so the calibration chart in the dashboard is honest but small-
  sample; a paid tier or a larger model budget would make that a much
  stronger, more statistically real signal.
