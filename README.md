# The Recovery Ledger

**Razorpay Buildathon — Track 03: AI Revenue Recovery**

Two agents that close the loop on lost revenue: one recovers **failed recurring
payments** (subscriptions, UPI AutoPay, cards), the other recovers **abandoned
carts** in real time on a live storefront. Both follow the same architecture:
an LLM diagnoses and proposes, hard-coded guardrails have the final say, and
every decision is logged with its reasoning — nothing about what shipped, what
was blocked, or what a message says is invented for the demo.

## Why this isn't just if/else with extra steps

The obvious critique of an "AI" recovery agent: `failure_code=insufficient_funds`
→ `send_payment_link` is a lookup table, not intelligence. So every diagnosis in
this project is checked against a naive baseline that only sees the coarse label,
and the disagreements are the actual evidence:

- **Failed payments**: `failure_code=bank_declined` covers both a routine decline
  *and* a compromised card flagged for unauthorized use — same label, opposite
  correct response. The baseline can't tell them apart; the agent reads the raw
  `bank_decline_message` text and does.
- **Cart abandonment**: a stall at OTP verification and a stall at the payment
  page share no stage-only lookup could distinguish correctly — one is checkout
  friction, the other is price hesitation, and only one of them should get a
  discount. The agent reads `abandonment_stage` semantics, not just its label,
  to tell them apart; a stage-only baseline gets `otp_pending` wrong on purpose
  so the two are directly comparable.
- **Customer replies**: free-text replies ("paid already yesterday, check again"
  vs. "this isn't me, I never bought this") are classified by intent and routed
  differently — a keyword baseline runs alongside the AI classifier on every
  reply so the gap is measured, not asserted.

Every one of these comparisons is rendered live in the dashboard / admin view,
not just described in this README.

## What's real vs. simulated (stated plainly, not left ambiguous)

| | Real | Simulated |
|---|---|---|
| Diagnosis + decision | ✅ live LLM call (Groq `openai/gpt-oss-120b`, or Anthropic Claude) | — |
| Guardrails | ✅ hard-coded Python, not prompted | — |
| Payment links | ✅ real Razorpay test-mode `payment_link.create` | — |
| Promise-to-pay / conversion outcome | — | simulated (no real customer behind synthetic/demo events) |
| WhatsApp / SMS / voice dispatch | — | drafted and shown, not transmitted (Twilio trial-account restrictions blocked real send; see Roadmap) |

## The two agents

### 1. Failed-payment recovery agent
`data → diagnose root cause → decide → guardrail-check → act → track promise-to-pay → report`

- `agent/llm_groq.py` / `agent/llm.py` — reads the actual bank decline text, not just the failure code
- `agent/guardrails.py` — compliance always outranks cost, hard stop on card-compromise, DND, retry caps, daily contact caps
- `agent/actions.py` — bounded action set, real Razorpay payment links
- `agent/pipeline.py` — orchestrates a batch; resilient to a bad model response (retries once, then falls back to a deterministic decision for just that case — logged, never silent, never crashes the batch)
- `dashboard/` — custom FastAPI ops console: recovery-rate stats, AI-vs-baseline evidence, confidence-vs-outcome calibration, guardrail intervention log, full per-case drill-down, and a scripted "connect your store" onboarding demo at `/connect`

### 2. Cart-abandonment recovery agent + live storefront
A real tracking snippet (`storefront/static/recovery-agent.js`) watches a real
checkout flow and fires on genuine inactivity/tab-close — this isn't a replayed
log, it's a live event pipeline:

- `agent/cart_llm_groq.py` — diagnoses *why* someone stalled (early browsing vs.
  price hesitation vs. checkout friction) from the abandonment stage, not a fixed rule
- `agent/cart_guardrails.py` — caps discount %, reserves discounts/voice for a
  second confirmed non-response (never the first touch), reserves voice calls
  for high-value carts only
- `agent/cart_rules_baseline.py` — the naive stage-only comparison baseline
- `storefront/` — a full demo storefront ("Aura Store") + `/admin`, a live
  operations feed: every abandonment event, the AI's reasoning, the guardrail
  trace, the baseline comparison, the drafted Hinglish message, the real
  Razorpay link, and an ROI ledger (spent vs. recovered)

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add GROQ_API_KEY at minimum
```

The repo ships with a populated `data/failed_payments.json` and
`data/results.json` (synthetic, Faker-generated, no real PII) so the dashboard
has something to show immediately — no live run required to explore it.

## Running it

```bash
# Dashboard (failed-payment agent)
uvicorn dashboard.main:app --reload --port 8502
# -> http://localhost:8502  (re-run a batch live from the "Re-run (live Groq)" button)

# Storefront + live cart-recovery agent
uvicorn storefront.main:app --reload --port 8000
# -> http://localhost:8000        the store
# -> http://localhost:8000/admin  the live recovery feed (auto-refreshes)
```

Or from the CLI directly:

```bash
python -m agent.pipeline                          # offline, deterministic, no API key
python -m agent.pipeline --live-groq               # live Groq, free tier
python -m agent.pipeline --live-groq --with-razorpay  # + real test-mode payment links
```

## Deploying

`render.yaml` in this repo is a Render blueprint for both services — see
**New → Blueprint** on render.com, point it at this repo, fill in the API keys
it asks for (never committed), deploy. Free plan is enough for a demo.

## Guardrails, concretely

Guardrails are hard-coded checks the model's proposal passes through, not a
prompt instruction the model could ignore — e.g. `card_compromised` cases are
hard-stopped from any further automated contact regardless of what the model
proposes; a discount can never exceed its cap regardless of what the model
suggests; the first contact on any case is always the gentlest option available,
full stop. This was validated the hard way: a real bug was found where a
cost-aware downgrade rule could override a correct compliance escalation, caught
by running a live batch and reading the output, then fixed and covered by a
regression test.

## Roadmap (explicitly not attempted tonight, and why)

- **Real WhatsApp/SMS/voice dispatch** — messages are drafted and shown in full,
  but not transmitted. Twilio's trial-account restrictions (WhatsApp Business
  Content Template approval, sandbox limits) blocked this; MSG91 and Meta's
  WhatsApp Cloud API are the next things to try, deliberately not started under
  deadline pressure rather than shipped half-working.
- **Hinglish TTS / voice synthesis** — the voice-call action is guardrail-gated
  and its script is drafted; no TTS engine is wired up yet.
- **Multi-tenant onboarding** — `/connect` demonstrates the pitch (a merchant
  only ever hands over one Razorpay key) as a scripted flow; a real OAuth
  connection and per-merchant data isolation is architecture, not yet code.
