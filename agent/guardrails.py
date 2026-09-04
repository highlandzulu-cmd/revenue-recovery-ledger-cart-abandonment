"""Hard-coded compliance and stopping rules.

These are deliberately NOT prompted to the LLM - they are enforced in code so a bad
model decision can never violate them. The agent proposes an action; this module has
the final say and can downgrade or block it. Every override is logged with a reason,
which is what "compliant escalation" and "stopping rules" in the track brief actually
mean in a demo: show the agent being stopped from doing something, not just doing things.
"""
from dataclasses import dataclass

from . import actions

MAX_AUTO_RETRIES = 3
MAX_CONTACTS_PER_DAY = 1
ESCALATE_AFTER_IGNORED_ATTEMPTS = 2
CONFIDENCE_THRESHOLD = 0.55

# Below this amount, a ~Rs180 human-labor escalation costs more than it's worth to
# chase - see the cost-aware rule at the bottom of check(). Not applied when a
# compliance rule already forced the escalation (this check only runs last).
LOW_VALUE_ESCALATION_THRESHOLD_INR = 720

NEVER_RETRY_CODES = {"mandate_revoked", "fraud_suspected"}
CARD_COMPROMISED_ROOT_CAUSES = {"card_compromised"}


@dataclass
class GuardrailResult:
    allowed_action: str
    overridden: bool
    reason: str


def check(case: dict, decision: dict) -> GuardrailResult:
    """Take the LLM's full decision (action + root_cause + confidence) and the case,
    return what's actually allowed to happen. Rules are checked in priority order and
    the first match wins - compliance/safety rules are ordered before the cost-aware
    rule so cost can never override a compliance-driven escalation.
    """
    proposed_action = decision["proposed_action"]
    root_cause = decision.get("root_cause")
    confidence = decision.get("confidence")

    failure_code = case["failure_code"]
    prior_attempts = case.get("prior_contact_attempts", [])
    ignored_count = sum(1 for a in prior_attempts if a["outcome"] == "ignored")
    retry_count = case.get("retry_count", 0)

    # Hard stop #1: the raw bank message indicated a compromised/lost/stolen card -
    # this comes from reading bank_decline_message, not from failure_code, so it can
    # fire even when failure_code alone would look routine (e.g. bank_declined).
    if root_cause in CARD_COMPROMISED_ROOT_CAUSES and proposed_action not in (
        "escalate_to_human", "stop_no_action",
    ):
        return GuardrailResult(
            allowed_action="escalate_to_human",
            overridden=True,
            reason="root_cause='card_compromised', read from the raw bank_decline_message "
                   f"(not just the failure_code enum); proposed '{proposed_action}' blocked - "
                   "no further automated contact or retry, routed to a human.",
        )

    # Hard stop #2: some failure codes must never be auto-retried, no matter what the
    # model proposes. This is the guardrail that should fire visibly in the demo.
    if failure_code in NEVER_RETRY_CODES and proposed_action in ("retry_at", "send_payment_link"):
        return GuardrailResult(
            allowed_action="escalate_to_human",
            overridden=True,
            reason=f"failure_code='{failure_code}' is in NEVER_RETRY_CODES; "
                   f"proposed '{proposed_action}' blocked and routed to a human agent instead.",
        )

    # Do-not-disturb customers never get an automated contact of any kind.
    if case.get("do_not_disturb") and proposed_action not in ("stop_no_action", "escalate_to_human"):
        return GuardrailResult(
            allowed_action="escalate_to_human",
            overridden=True,
            reason="customer is flagged do_not_disturb; automated contact blocked, routed to human.",
        )

    # Low-confidence diagnosis: don't act automatically on an uncertain read, get a
    # human to look at it instead of trusting a shaky classification.
    if (
        confidence is not None
        and confidence < CONFIDENCE_THRESHOLD
        and proposed_action not in ("escalate_to_human", "stop_no_action")
    ):
        return GuardrailResult(
            allowed_action="escalate_to_human",
            overridden=True,
            reason=f"model confidence={confidence:.2f} is below CONFIDENCE_THRESHOLD="
                   f"{CONFIDENCE_THRESHOLD}; routing to a human instead of acting on an "
                   "uncertain diagnosis.",
        )

    # Retry cap.
    if proposed_action == "retry_at" and retry_count >= MAX_AUTO_RETRIES:
        return GuardrailResult(
            allowed_action="escalate_to_human",
            overridden=True,
            reason=f"retry_count={retry_count} has reached MAX_AUTO_RETRIES={MAX_AUTO_RETRIES}; "
                   f"escalating instead of retrying again.",
        )

    # Escalate after repeated ignored contact rather than keep nudging indefinitely.
    if ignored_count >= ESCALATE_AFTER_IGNORED_ATTEMPTS and proposed_action not in (
        "escalate_to_human", "stop_no_action",
    ):
        return GuardrailResult(
            allowed_action="escalate_to_human",
            overridden=True,
            reason=f"{ignored_count} prior contacts were ignored (>= "
                   f"{ESCALATE_AFTER_IGNORED_ATTEMPTS}); escalating to a human instead of "
                   f"another automated nudge.",
        )

    # Daily contact cap - only relevant to actions that contact the customer.
    contact_actions = {"send_payment_link", "send_update_method_link", "personalized_reminder"}
    if proposed_action in contact_actions:
        today_contacts = [a for a in prior_attempts if _is_today(a["timestamp"], case)]
        if len(today_contacts) >= MAX_CONTACTS_PER_DAY:
            return GuardrailResult(
                allowed_action="stop_no_action",
                overridden=True,
                reason=f"already contacted {len(today_contacts)} time(s) today; "
                       f"MAX_CONTACTS_PER_DAY={MAX_CONTACTS_PER_DAY} reached, holding off.",
            )

    # Cost-aware downgrade - last resort. Only applies when NONE of the compliance
    # conditions above are present, checked explicitly here rather than relying on
    # rule order: the model can propose escalate_to_human on its own for a compliance
    # reason (e.g. it correctly reads a card_compromised message and escalates without
    # needing to be forced), which never triggers the override branches above since
    # those only fire when the model's proposal needs correcting. Without this
    # explicit re-check, cost would silently downgrade a correct compliance escalation
    # into a cheap automated channel - exactly the failure mode this system exists to
    # prevent. Compliance always wins over cost, never the reverse.
    is_compliance_driven = (
        root_cause in CARD_COMPROMISED_ROOT_CAUSES
        or failure_code in NEVER_RETRY_CODES
        or case.get("do_not_disturb")
        or (confidence is not None and confidence < CONFIDENCE_THRESHOLD)
        or ignored_count >= ESCALATE_AFTER_IGNORED_ATTEMPTS
    )
    if (
        proposed_action == "escalate_to_human"
        and not is_compliance_driven
        and case["amount_inr"] < LOW_VALUE_ESCALATION_THRESHOLD_INR
    ):
        cheap_action = "send_payment_link"
        expected_recovery = actions.recovery_probability(cheap_action) * case["amount_inr"]
        return GuardrailResult(
            allowed_action=cheap_action,
            overridden=True,
            reason=f"proposed escalate_to_human (~Rs{actions.ACTION_COST_INR['escalate_to_human']} "
                   f"labor cost) for a Rs{case['amount_inr']:.2f} case with no compliance reason "
                   f"forcing escalation; not cost-justified (cheap channel's expected recovery "
                   f"~Rs{expected_recovery:.2f} at ~Rs{actions.ACTION_COST_INR[cheap_action]} cost) - "
                   f"downgraded to {cheap_action} instead.",
        )

    return GuardrailResult(allowed_action=proposed_action, overridden=False, reason="no guardrail triggered")


def _is_today(timestamp_iso: str, case: dict) -> bool:
    # Simplified for the synthetic dataset: compare calendar date only.
    return timestamp_iso[:10] == case["failure_timestamp"][:10]


@dataclass
class ReplyGuardrailResult:
    halt_all_contact: bool
    routed_action: str
    reason: str


def check_reply_intent(intent: str) -> ReplyGuardrailResult:
    """A customer's interpreted reply can override everything that came before it -
    this runs regardless of what the original recovery action or guardrail decided.

    A dispute/fraud claim is the strictest case: it permanently halts all further
    automated contact on this case, full stop. This is a hard rule, not something
    left to the model's judgment on a case-by-case basis - continuing to dun someone
    who's disputing a charge is the exact scenario "compliant escalation" exists to
    prevent.
    """
    if intent == "dispute_fraud_claim":
        return ReplyGuardrailResult(
            halt_all_contact=True,
            routed_action="halt_dispute_escalate",
            reason="customer reply was classified as a fraud/dispute claim; all automated "
                   "contact permanently halted, case routed to fraud/compliance review.",
        )

    if intent == "wrong_number":
        return ReplyGuardrailResult(
            halt_all_contact=True,
            routed_action="escalate_to_human",
            reason="customer says they have no account/subscription with us at all - "
                   "distinct from a fraud dispute (which claims a specific charge is "
                   "unauthorized); halting automated contact, routed to a human to "
                   "verify the contact details rather than fraud/compliance review.",
        )

    if intent == "claims_already_paid":
        return ReplyGuardrailResult(
            halt_all_contact=True,
            routed_action="escalate_to_human",
            reason="customer claims this was already paid; halting automated contact, "
                   "routed to a human to verify against payment records.",
        )

    if intent == "refuses_hostile":
        return ReplyGuardrailResult(
            halt_all_contact=True,
            routed_action="escalate_to_human",
            reason="customer explicitly asked to stop being contacted; automated "
                   "outreach halted, routed to a human for any further handling.",
        )

    if intent == "promise_to_pay":
        return ReplyGuardrailResult(
            halt_all_contact=False,
            routed_action="mark_promise_to_pay",
            reason="customer committed to paying; tracking as a promise-to-pay.",
        )

    return ReplyGuardrailResult(
        halt_all_contact=False,
        routed_action="escalate_to_human",
        reason="reply intent unclear; routed to a human rather than guessing.",
    )
