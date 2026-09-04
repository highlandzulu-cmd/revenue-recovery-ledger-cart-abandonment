"""Real Razorpay test-mode API calls.

Test-mode keys (rzp_test_...) never move real money - this is Razorpay's own sandbox,
safe to call freely. Notifications are left off (notify.sms/email = False) since our
synthetic dataset has no real customer contact info; we only use the real short_url
this returns to show a genuine payment link, we never ask Razorpay to message anyone.
"""
import os
import time

import razorpay

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = razorpay.Client(auth=(os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"]))
    return _client


def create_payment_link(case: dict) -> dict:
    """Create a real (test-mode) Razorpay payment link for a failed-payment case."""
    client = _get_client()
    amount_paise = int(round(case["amount_inr"] * 100))

    # reference_id must be unique per Razorpay account - the same case_id gets reused
    # across pipeline re-runs against the same test account, so a run-specific suffix
    # is needed or every re-run after the first collides with the earlier link.
    reference_id = f"{case['case_id']}-{int(time.time())}"

    link = client.payment_link.create(data={
        "amount": amount_paise,
        "currency": "INR",
        "description": f"Recovery: {case['case_id']} - {case['subscription_tier']} subscription",
        "reference_id": reference_id,
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
        "notes": {
            "case_id": case["case_id"],
            "failure_code": case["failure_code"],
        },
    })

    return {
        "payment_link_id": link["id"],
        "short_url": link["short_url"],
        "status": link["status"],
    }


def fetch_payment_link_status(payment_link_id: str) -> dict:
    client = _get_client()
    link = client.payment_link.fetch(payment_link_id)
    return {"status": link["status"], "amount_paid": link.get("amount_paid", 0)}


def friendly_error(e: Exception) -> str:
    """A one-line message safe to show in a live demo. KeyError's str() is just
    the bare key ('RAZORPAY_KEY_ID') with no context, and the raw SDK exception
    text is written for a developer reading logs, not someone watching a judged
    demo - this maps the couple of cases actually expected during testing to
    something readable, and otherwise still shows the real error rather than
    swallowing it (a demo hiding its own failures would be a worse look than
    an honest one)."""
    if isinstance(e, KeyError):
        return "Razorpay not configured (missing API key)"
    text = str(e)
    if "test mode limit" in text:
        return "Razorpay test-mode link limit reached for today"
    return text
