"""Generate a synthetic batch of failed recurring payments for the Revenue Recovery Agent.

No external services required - pure synthetic data so the rest of the pipeline
(diagnosis, decision, guardrails, dashboard) can be built and demoed offline.
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

fake = Faker("en_IN")

FAILURE_CODES = [
    ("insufficient_funds", 0.35),
    ("card_expired", 0.15),
    ("bank_declined", 0.15),
    ("technical_timeout", 0.15),
    ("issuer_down", 0.10),
    ("mandate_revoked", 0.06),
    ("fraud_suspected", 0.04),
]

PAYMENT_METHODS = ["upi_autopay", "card", "netbanking"]
SUBSCRIPTION_TIERS = [("basic", 499, 0.50), ("pro", 1499, 0.35), ("enterprise", 4999, 0.15)]
CONTACT_CHANNELS = ["sms", "email", "call"]

# Real bank/gateway response text, not the clean enum. The point: "bank_declined" is
# one label hiding two very different real situations - a rules engine keyed only on
# the enum cannot distinguish them, only reading the actual message can.
BANK_MESSAGE_TEMPLATES = {
    "insufficient_funds": [
        "Transaction declined - insufficient balance in account",
        "Insufficient funds in customer account, please retry",
    ],
    "card_expired": [
        "Card has expired, please use a valid card",
        "Expired card - transaction declined",
    ],
    # Soft: a routine decline, safe to retry / nudge normally.
    "bank_declined_soft": [
        "Do not honor - please retry or contact your bank",
        "Transaction declined by issuing bank, generic decline code 05",
        "Bank declined - temporary hold, retry recommended after some time",
    ],
    # Hard: the card itself is compromised. Retrying isn't just ineffective, it's the
    # wrong thing to do - same enum (bank_declined) as the soft cases above.
    "bank_declined_hard": [
        "Card reported lost or stolen - do not retry",
        "Restricted card - possible unauthorized use flagged by issuer",
        "Suspected compromised card, blocked by issuing bank pending investigation",
    ],
    "technical_timeout": [
        "Gateway timeout - no response from acquirer",
        "Connection timed out during authorization",
    ],
    "issuer_down": [
        "Issuer bank system unavailable",
        "Bank server not responding, try after some time",
    ],
    "mandate_revoked": [
        "e-Mandate cancelled by customer via net banking",
        "UPI AutoPay mandate revoked by user",
    ],
    "fraud_suspected": [
        "Transaction blocked - suspected fraudulent activity",
        "Risk engine flagged this transaction as high risk",
    ],
}

# Simulated free-text customer replies to the outreach message. Real recovery
# systems get exactly this: messy, code-switched, non-templated text - not clean
# enums. The "true_intent" label is our ground truth for scoring the keyword
# baseline against the LLM interpreter later; it is never shown to either engine.
REPLY_TEMPLATES = {
    "promise_with_date": [
        "haan sir agle Monday tak pay kar dunga, please thoda wait kijiye",
        "kal tak kar dunga payment, sorry for the delay",
        "salary ayegi 1st ko, us din turant kar dunga",
        "is weekend tak clear kar dunga, promise",
    ],
    "promise_vague": [
        "thoda time chahiye, jaldi hi kar dunga",
        "abhi busy hoon, baad mein dekhta hoon isko",
    ],
    "claims_already_paid": [
        "maine to already pay kar diya tha last week, check karo apna system",
        "yeh payment to ho chuka hai mera, dobara kyu maang rahe ho",
    ],
    # Uses obvious keywords a rules engine would be built to catch - included so the
    # baseline isn't a strawman that catches nothing.
    "dispute_fraud_obvious": [
        "yeh fraud transaction hai, maine kabhi authorize nahi kiya isko",
        "mera card block karo, yeh unauthorized charge hai",
    ],
    # Same underlying claim - unauthorized use / dispute - phrased the way a real
    # person actually would, with none of the keywords a naive rules engine would
    # be watching for. This is the case that separates language understanding
    # from keyword matching.
    "dispute_fraud_hidden": [
        "yeh charge samajh nahi aaya, mera card kisi aur ne use kiya lagta hai",
        "mujhe pata hi nahi ye transaction kaise hua, maine to kabhi order hi nahi kiya is jagah se",
        "wait yeh kya hai? maine to iss company ka naam bhi pehle kabhi nahi suna",
    ],
    "hostile_refuse": [
        "baar baar message mat karo, mujhe interest nahi hai",
        "stop messaging me, I'll pay when I want to",
    ],
    "wrong_number": [
        "aap galat number pe message kar rahe ho, mera koi subscription nahi hai",
    ],
}


def weighted_choice(pairs):
    items, weights = zip(*[(p[0], p[-1]) for p in pairs])
    return random.choices(items, weights=weights, k=1)[0]


def gen_bank_message(failure_code):
    """Pick a realistic raw bank/gateway message for a failure_code. bank_declined
    is deliberately split 50/50 into soft (retry-safe) and hard (never-retry,
    possible fraud) - the ground-truth label is returned separately, never shown
    to any engine, so we can score whether reading the text actually mattered.
    """
    if failure_code == "bank_declined":
        severity = random.choice(["soft", "hard"])
        message = random.choice(BANK_MESSAGE_TEMPLATES[f"bank_declined_{severity}"])
        return message, severity
    return random.choice(BANK_MESSAGE_TEMPLATES[failure_code]), None


def gen_record(i, now):
    tier_name = weighted_choice(SUBSCRIPTION_TIERS)
    base_amount = next(t[1] for t in SUBSCRIPTION_TIERS if t[0] == tier_name)
    amount = round(base_amount * random.uniform(0.9, 1.3), 2)
    failure_code = weighted_choice(FAILURE_CODES)
    bank_decline_message, bank_message_severity = gen_bank_message(failure_code)
    tenure_days = random.randint(15, 900)
    past_successful = max(0, round(tenure_days / random.uniform(28, 32)))
    past_failures = random.choices([0, 1, 2, 3], weights=[0.6, 0.25, 0.1, 0.05])[0]
    failure_time = now - timedelta(days=random.randint(0, 14), hours=random.randint(0, 23))

    # Some customers were already nudged once via SMS and ignored it -
    # this sets up the "channels exhausted -> escalate" path downstream.
    prior_attempts = []
    if random.random() < 0.30:
        prior_attempts.append({
            "channel": "sms",
            "timestamp": (failure_time + timedelta(hours=random.randint(1, 20))).isoformat(),
            "outcome": random.choice(["ignored", "ignored", "link_expired"]),
        })
        if random.random() < 0.30:
            prior_attempts.append({
                "channel": "email",
                "timestamp": (failure_time + timedelta(days=1, hours=random.randint(1, 10))).isoformat(),
                "outcome": "ignored",
            })

    return {
        "case_id": f"RCV-{i:04d}",
        "customer_id": f"cust_{fake.uuid4()[:8]}",
        "customer_name": fake.name(),
        "subscription_tier": tier_name,
        "amount_inr": amount,
        "payment_method": random.choice(PAYMENT_METHODS),
        "failure_code": failure_code,
        "bank_decline_message": bank_decline_message,
        "true_bank_message_severity": bank_message_severity,  # ground truth, hidden from engines
        "failure_timestamp": failure_time.isoformat(),
        "tenure_days": tenure_days,
        "past_successful_payments": past_successful,
        "past_failures_last_90d": past_failures,
        "contact_preference": random.choice(CONTACT_CHANNELS),
        "do_not_disturb": random.random() < 0.08,
        "prior_contact_attempts": prior_attempts,
        "customer_reply": None,
        "true_reply_intent": None,  # ground truth for scoring, never shown to any engine
    }


def assign_customer_replies(records):
    """Attach a free-text reply to a subset of cases. The two 'dispute' categories
    are pinned to fixed indices (not left to random draw) so the demo's headline
    case - a fraud claim phrased without any of the obvious keywords - always
    exists in the batch regardless of the random seed's other draws.
    """
    pinned = {
        5: "dispute_fraud_hidden",   # the money case: no "fraud"/"dispute"/keyword
        15: "dispute_fraud_obvious",  # keyword-triggering, for baseline calibration
        25: "claims_already_paid",
        35: "promise_with_date",
    }
    for idx, intent in pinned.items():
        text = random.choice(REPLY_TEMPLATES[intent])
        records[idx]["customer_reply"] = text
        records[idx]["true_reply_intent"] = intent

    remaining_intents = list(REPLY_TEMPLATES.keys())
    for i, r in enumerate(records):
        if i in pinned or random.random() >= 0.22:
            continue
        intent = random.choice(remaining_intents)
        r["customer_reply"] = random.choice(REPLY_TEMPLATES[intent])
        r["true_reply_intent"] = intent


def pin_bank_message_severity(records):
    """Guarantee at least one 'hard' (never-retry) and one 'soft' (retry-safe)
    bank_declined case exist, regardless of the random draw, so the demo's
    same-enum-different-reality divergence is always present in the batch.
    """
    bank_declined = [r for r in records if r["failure_code"] == "bank_declined"]
    if len(bank_declined) >= 2:
        bank_declined[0]["true_bank_message_severity"] = "hard"
        bank_declined[0]["bank_decline_message"] = random.choice(BANK_MESSAGE_TEMPLATES["bank_declined_hard"])
        bank_declined[1]["true_bank_message_severity"] = "soft"
        bank_declined[1]["bank_decline_message"] = random.choice(BANK_MESSAGE_TEMPLATES["bank_declined_soft"])


def main(n=60, seed=42, out_path=None):
    out_path = out_path or Path(__file__).parent / "failed_payments.json"
    random.seed(seed)
    now = datetime(2026, 8, 21, 10, 0, 0)
    records = [gen_record(i + 1, now) for i in range(n)]
    pin_bank_message_severity(records)
    assign_customer_replies(records)
    out_path.write_text(json.dumps(records, indent=2))

    total_at_risk = sum(r["amount_inr"] for r in records)
    by_code = {}
    for r in records:
        by_code[r["failure_code"]] = by_code.get(r["failure_code"], 0) + 1
    reply_count = sum(1 for r in records if r["customer_reply"])

    print(f"Wrote {len(records)} records to {out_path}")
    print(f"Total revenue at risk: Rs {total_at_risk:,.2f}")
    print(f"Cases with a customer reply: {reply_count}")
    print("Breakdown by failure code:")
    for code, count in sorted(by_code.items(), key=lambda x: -x[1]):
        print(f"  {code:20s} {count}")


if __name__ == "__main__":
    main()
