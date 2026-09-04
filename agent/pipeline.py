"""Orchestrates the recovery loop over a batch: diagnose -> decide -> guardrail-check
-> execute -> log. Writes data/results.json, which the dashboard reads.

Run with the offline mock decision-maker (no API key needed):
    python -m agent.pipeline

Run with the real Claude-backed decision-maker (needs ANTHROPIC_API_KEY in .env):
    python -m agent.pipeline --live

Run with the free Groq-backed decision-maker (needs GROQ_API_KEY in .env):
    python -m agent.pipeline --live-groq

Add --with-razorpay to any mode to create real (test-mode, sandboxed) Razorpay
payment links instead of placeholder URLs (needs RAZORPAY_KEY_ID/SECRET in .env):
    python -m agent.pipeline --live-groq --with-razorpay
"""
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import actions, guardrails, mock_llm, reply_rules_baseline

# How many days out a customer's promise-to-pay is simulated to fall due,
# used only when no real date could be extracted from a reply.
PROMISE_WINDOW_DAYS = (2, 5)

DATA_PATH = Path(__file__).parent.parent / "data" / "failed_payments.json"
RESULTS_PATH = Path(__file__).parent.parent / "data" / "results.json"


def _decide_resilient(decide_fn, case: dict, pace_seconds: float) -> tuple[dict, str | None]:
    """Call decide_fn with one retry, then fall back to the deterministic mock
    decision for just this case rather than taking the whole batch down.

    This exists because a live model call can fail in ways that have nothing to
    do with our code - e.g. the model emitting malformed JSON in a tool call
    ("confidence": 0. nine) that the provider's API itself rejects as
    unparseable. Without this, one bad response crashes every case after it.
    The fallback is never silent: decision_error is recorded on the result row
    so a degraded case is always visible, not hidden as if it succeeded normally.
    """
    try:
        return decide_fn(case), None
    except Exception as first_error:
        if pace_seconds:
            time.sleep(pace_seconds)
        try:
            return decide_fn(case), None
        except Exception as second_error:
            fallback = mock_llm.diagnose_and_decide(case)
            fallback["reasoning"] = (
                f"[fallback after live decision failed twice: {second_error}] " + fallback["reasoning"]
            )
            return fallback, str(second_error)


def run_batch(
    decide_fn,
    data_path: Path = DATA_PATH,
    results_path: Path = RESULTS_PATH,
    pace_seconds: float = 0,
    interpret_reply_fn=None,
    use_real_razorpay: bool = False,
) -> list[dict]:
    cases = json.loads(data_path.read_text())
    results = []

    for i, case in enumerate(cases):
        if pace_seconds and i > 0:
            time.sleep(pace_seconds)
        decision, decision_error = _decide_resilient(decide_fn, case, pace_seconds)
        proposed_action = decision["proposed_action"]

        # The enum-only baseline is computed alongside every case, free and local (no
        # API cost) - it never drives what happens, it's only recorded so the dashboard
        # can show exactly where reading bank_decline_message changed the outcome,
        # the same measured comparison used for reply interpretation.
        baseline_decision = mock_llm.diagnose_and_decide(case)

        guardrail_result = guardrails.check(case, decision)
        final_action = guardrail_result.allowed_action

        exec_result = actions.execute(case, final_action, use_real_razorpay=use_real_razorpay)

        if pace_seconds:
            flag = " [DECISION FALLBACK]" if decision_error else ""
            print(f"  [{i + 1}/{len(cases)}] {case['case_id']} -> {final_action} ({exec_result['outcome']}){flag}")

        results.append({
            "case_id": case["case_id"],
            "decision_error": decision_error,
            "customer_name": case["customer_name"],
            "subscription_tier": case["subscription_tier"],
            "amount_inr": case["amount_inr"],
            "failure_code": case["failure_code"],
            "bank_decline_message": case.get("bank_decline_message"),
            "root_cause": decision["root_cause"],
            "baseline_root_cause": baseline_decision["root_cause"],
            "root_cause_agree": decision["root_cause"] == baseline_decision["root_cause"],
            "confidence": decision.get("confidence"),
            "reasoning": decision["reasoning"],
            "customer_message": decision["customer_message"],
            "proposed_action": proposed_action,
            "guardrail_overridden": guardrail_result.overridden,
            "guardrail_reason": guardrail_result.reason,
            "final_action": final_action,
            "outcome": exec_result["outcome"],
            "amount_recovered": exec_result["amount_recovered"],
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "promise_due_date": None,
            "promise_resolution": None,
            "round2_action": None,
            "round2_outcome": None,
            "customer_reply": case.get("customer_reply"),
            "reply_baseline_intent": None,
            "reply_ai_intent": None,
            "reply_ai_reasoning": None,
            "baseline_ai_agree": None,
            "reply_interpretation_error": None,
            "razorpay_link_url": exec_result.get("razorpay_link_url"),
            "razorpay_link_id": exec_result.get("razorpay_link_id"),
        })

    if interpret_reply_fn:
        _interpret_replies(results, interpret_reply_fn, pace_seconds)

    _resolve_promises(results)

    results_path.write_text(json.dumps(results, indent=2))
    return results


def _interpret_resilient(interpret_reply_fn, reply_text: str, pace_seconds: float) -> tuple[dict, str | None]:
    """Same resilience pattern as _decide_resilient: one retry, then fall back
    rather than crashing the reply-interpretation phase over a single bad
    response. The fallback here is the keyword baseline's own verdict - clearly
    worse than a working AI call, but honestly labeled and non-fatal."""
    try:
        return interpret_reply_fn(reply_text), None
    except Exception:
        if pace_seconds:
            time.sleep(pace_seconds)
        try:
            return interpret_reply_fn(reply_text), None
        except Exception as second_error:
            fallback = reply_rules_baseline.interpret(reply_text)
            fallback["reasoning"] = (
                f"[fallback after live interpretation failed twice: {second_error}] " + fallback["reasoning"]
            )
            return fallback, str(second_error)


def _interpret_replies(results: list[dict], interpret_reply_fn, pace_seconds: float) -> None:
    """For every case with a real customer reply, run both the keyword baseline and
    the AI interpreter on the SAME text, then let the AI verdict drive what actually
    happens next via guardrails.check_reply_intent - the baseline result is recorded
    only for comparison, it never controls the case. A dispute/fraud verdict overrides
    everything decided in round 1: no further automated contact, no exceptions.
    """
    targets = [r for r in results if r["customer_reply"]]

    for i, r in enumerate(targets):
        if pace_seconds and i > 0:
            time.sleep(pace_seconds)

        baseline = reply_rules_baseline.interpret(r["customer_reply"])
        ai, ai_error = _interpret_resilient(interpret_reply_fn, r["customer_reply"], pace_seconds)

        r["reply_baseline_intent"] = baseline["intent"]
        r["reply_ai_intent"] = ai["intent"]
        r["reply_ai_reasoning"] = ai["reasoning"]
        r["baseline_ai_agree"] = baseline["intent"] == ai["intent"]
        r["reply_interpretation_error"] = ai_error

        if pace_seconds:
            agree = "agree" if r["baseline_ai_agree"] else "DISAGREE"
            flag = " [FALLBACK]" if ai_error else ""
            print(f"  [reply {i + 1}/{len(targets)}] {r['case_id']} -> "
                  f"baseline={baseline['intent']} ai={ai['intent']} ({agree}){flag}")

        disposition = guardrails.check_reply_intent(ai["intent"])

        if disposition.halt_all_contact:
            r["round2_action"] = disposition.routed_action
            r["round2_outcome"] = "halted" if disposition.routed_action == "halt_dispute_escalate" \
                else "queued_for_human"
            r["outcome"] = "dispute_claim" if ai["intent"] == "dispute_fraud_claim" else r["outcome"]
            r["amount_recovered"] = 0.0
            # A reply-driven halt supersedes anything the random round-1 simulation
            # guessed about a promise - we now have the customer's actual words.
            r["promise_due_date"] = None
            r["promise_resolution"] = None
        else:
            # promise_to_pay: use the AI's extracted date if it resolved one,
            # otherwise fall back to the same simulated window as an un-dated promise.
            r["outcome"] = "promised"
            due = ai.get("extracted_promise_date")
            if not due:
                due = (datetime.now(timezone.utc)
                       + timedelta(days=random.randint(*PROMISE_WINDOW_DAYS))).date().isoformat()
            r["promise_due_date"] = due


def _resolve_promises(results: list[dict]) -> None:
    """Second pass: for every case a customer promised to pay, simulate reaching the
    due date and check whether the promise was honored. A broken promise auto-escalates
    to a human rather than firing another automated nudge - same policy the guardrail
    layer applies to repeatedly-ignored contacts, just triggered by a different signal.

    Skips rows a reply already fully resolved (halted/disputed cases have no promise
    to check) and only sets a fallback due date for rows that don't have one yet.
    """
    now = datetime.now(timezone.utc)

    for r in results:
        if r["outcome"] != "promised" or r["promise_resolution"] is not None:
            continue

        if not r["promise_due_date"]:
            due_date = now + timedelta(days=random.randint(*PROMISE_WINDOW_DAYS))
            r["promise_due_date"] = due_date.date().isoformat()

        resolution = actions.resolve_promise(r)
        r["amount_recovered"] = resolution["amount_recovered"]

        if resolution["outcome"] == "promise_kept":
            r["promise_resolution"] = "kept"
        else:
            r["promise_resolution"] = "broken"
            r["round2_action"] = "escalate_to_human"
            r["round2_outcome"] = "queued_for_human"


_CALIBRATION_BUCKETS = [(0.0, 0.6), (0.6, 0.75), (0.75, 0.9), (0.9, 1.01)]


def confidence_calibration(results: list[dict]) -> list[dict]:
    """Buckets every confidence-bearing case by its stated confidence and reports
    each bucket's actual recovery rate. This is the check a "90% confident"
    number is only worth trusting if it passes: does the 90%+ bucket actually
    recover money ~90% of the time, or is the model just as likely to say 90%
    on a case that goes nowhere as it is on one that pays out?"""
    rows = []
    for lo, hi in _CALIBRATION_BUCKETS:
        bucket = [r for r in results if r["confidence"] is not None and lo <= r["confidence"] < hi]
        if not bucket:
            continue
        recovered = sum(1 for r in bucket if r["amount_recovered"] > 0)
        rows.append({
            "label": f"{int(lo * 100)}-{min(int(hi * 100), 100)}%",
            "n": len(bucket),
            "recovery_rate_pct": round(100 * recovered / len(bucket)),
        })
    return rows


def summarize(results: list[dict]) -> dict:
    total_at_risk = sum(r["amount_inr"] for r in results)
    total_recovered = sum(r["amount_recovered"] for r in results)
    promises = [r for r in results if r["promise_resolution"] is not None]
    replies = [r for r in results if r["reply_ai_intent"] is not None]

    escalations = sum(
        1 for r in results
        if r["final_action"] == "escalate_to_human" or r["round2_action"] == "escalate_to_human"
    )
    dispute_claims_caught = sum(1 for r in replies if r["reply_ai_intent"] == "dispute_fraud_claim")
    baseline_ai_disagreements = sum(1 for r in replies if not r["baseline_ai_agree"])
    real_razorpay_links = sum(
        1 for r in results if r["razorpay_link_url"] and not r["razorpay_link_url"].startswith("[razorpay call failed")
    )
    card_compromised_caught = sum(1 for r in results if r["root_cause"] == "card_compromised")
    diagnosis_disagreements = sum(1 for r in results if not r["root_cause_agree"])
    low_confidence_escalations = sum(
        1 for r in results
        if r["confidence"] is not None and r["confidence"] < 0.55 and r["guardrail_overridden"]
    )
    cost_downgrades = sum(
        1 for r in results
        if r["guardrail_overridden"] and "not cost-justified" in (r["guardrail_reason"] or "")
    )
    decision_fallbacks = sum(1 for r in results if r.get("decision_error"))
    reply_fallbacks = sum(1 for r in replies if r.get("reply_interpretation_error"))

    return {
        "batch_size": len(results),
        "total_at_risk_inr": round(total_at_risk, 2),
        "total_recovered_inr": round(total_recovered, 2),
        "recovery_rate_pct": round(100 * total_recovered / total_at_risk, 1) if total_at_risk else 0,
        "guardrail_interventions": sum(1 for r in results if r["guardrail_overridden"]),
        "escalations_to_human": escalations,
        "stopped_no_action": sum(1 for r in results if r["final_action"] == "stop_no_action"),
        "promises_made": len(promises),
        "promises_kept": sum(1 for r in promises if r["promise_resolution"] == "kept"),
        "promises_broken": sum(1 for r in promises if r["promise_resolution"] == "broken"),
        "replies_interpreted": len(replies),
        "baseline_ai_disagreements": baseline_ai_disagreements,
        "dispute_claims_caught": dispute_claims_caught,
        "real_razorpay_links_created": real_razorpay_links,
        "card_compromised_caught": card_compromised_caught,
        "diagnosis_disagreements": diagnosis_disagreements,
        "low_confidence_escalations": low_confidence_escalations,
        "cost_downgrades": cost_downgrades,
        "decision_fallbacks": decision_fallbacks,
        "reply_interpretation_fallbacks": reply_fallbacks,
    }


if __name__ == "__main__":
    pace = 0
    interpret_reply_fn = None

    if "--live-groq" in sys.argv:
        from . import llm_groq, reply_interpreter_groq
        decide_fn = llm_groq.diagnose_and_decide
        interpret_reply_fn = reply_interpreter_groq.interpret
        pace = llm_groq.PACING_SECONDS
        print(f"Running with live Groq decisions (GROQ_API_KEY required), "
              f"paced {pace}s/case to stay under the free-tier token cap "
              f"(includes reply interpretation vs. keyword baseline)...")
    elif "--live" in sys.argv:
        from . import llm
        decide_fn = llm.diagnose_and_decide
        print("Running with live Claude decisions (ANTHROPIC_API_KEY required)... "
              "note: reply interpretation is Groq-only for now, replies won't be scored.")
    else:
        from . import mock_llm
        decide_fn = mock_llm.diagnose_and_decide
        print("Running with offline mock decisions "
              "(pass --live for Claude or --live-groq for free Groq calls)... "
              "note: reply interpretation needs --live-groq, replies won't be scored.")

    use_real_razorpay = "--with-razorpay" in sys.argv
    if use_real_razorpay:
        print("Creating real (test-mode) Razorpay payment links for send_payment_link cases "
              "(RAZORPAY_KEY_ID/SECRET required)...")

    batch_results = run_batch(
        decide_fn, pace_seconds=pace, interpret_reply_fn=interpret_reply_fn,
        use_real_razorpay=use_real_razorpay,
    )
    print(json.dumps(summarize(batch_results), indent=2))
    print(f"\nFull audit trail written to {RESULTS_PATH}")
