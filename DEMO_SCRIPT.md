# Demo recording shot list (~3 min)

Not a word-for-word script — beats to hit, in order. Record with QuickTime
(File → New Screen Recording) so audio + screen are one file.

## 1. Hook (10s)
State the problem in one line: recurring payments fail constantly (card
expired, insufficient funds, bank hiccup) and most businesses either do
nothing or blast the same generic retry at everyone — including cases where
retrying is actively the wrong move.

## 2. Failed-payment dashboard (~70s) — `localhost:8502`
- Point at the stat strip: cases, at-risk, recovered, recovery rate.
- **The one moment that matters most**: scroll to "Root-cause diagnosis — AI
  vs. enum-only baseline." Read the RCV-0008 example out loud: bank message
  says "Restricted card - possible unauthorized use flagged by issuer,"
  `failure_code` is the same generic `bank_declined` as a routine decline —
  baseline says `hard_decline_or_revoked`, AI correctly says `card_compromised`.
  Say explicitly: *this is the difference between retrying a stolen card and
  correctly escalating it — a label-only system can't tell these apart.*
- Scroll to "Confidence vs. outcome" — say what it is in one sentence: does the
  AI's own confidence number mean anything, or is it noise.
- Scroll to "Guardrail interventions" — one example of the AI's proposal getting
  overridden by hard-coded compliance code. Say: *guardrails, not the model,
  have final say.*
- Click "See the merchant onboarding demo" (`/connect`) briefly — let the
  checklist animate through. Say: *the entire integration story is one
  Razorpay key.*

## 3. Live cart-abandonment agent (~70s) — `localhost:8000`
This is the "it's alive" moment — do it with two windows/tabs visible if you can.
- Browse the store for a second, add an item, go to checkout. Don't click Pay.
- While it's "thinking" (a few seconds), talk over it: explain the tracking
  snippet just watched you go idle — this is a real event pipeline, not a
  replayed log.
- Switch to `/admin` — a new event card should have landed. Point at: the
  diagnosis reasoning, the drafted Hinglish WhatsApp message, the guardrail
  trace, and the baseline-comparison line ("baseline would've said X — AI
  disagreed").
- Point at the real Razorpay link — click it once to prove it's genuine, not
  a placeholder string.
- Point at the ROI stat row: recovered vs. spent.

## 4. Close (15s)
One line on what's real vs. simulated (say it, don't dodge it): live LLM
diagnosis and real Razorpay links, yes; message dispatch is drafted and shown
but not transmitted (Twilio trial restrictions), and outcomes are simulated
since there's no real customer behind a demo event. Then one line on what's
next: real WhatsApp/SMS dispatch via MSG91 or Meta's Cloud API.

## Notes for tonight specifically
- Groq's daily token quota is tight from today's testing — if a live call
  falls back, the fallback path itself is a feature (logged, never a crash),
  but don't be surprised if a re-run mid-recording shows a fallback tag.
- Razorpay test-mode hit its 30-link cap earlier — if you need a fresh real
  link on camera, either wait for it to reset or don't rely on clicking
  "create a NEW one," reuse a link already shown.
- If either app has been idle a while after deploying to Render's free tier,
  hit both URLs ~60s before recording to clear the cold start.
