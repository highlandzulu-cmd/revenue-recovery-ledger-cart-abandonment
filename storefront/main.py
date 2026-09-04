"""Demo e-commerce storefront + live cart-abandonment recovery backend.

Unlike agent/pipeline.py (which processes a static batch of 60 synthetic cases),
this reacts to a REAL abandonment event the moment it happens: a customer adds
items, starts checkout, then goes idle or leaves - the tracking snippet
(static/recovery-agent.js) detects it and calls /api/cart-abandoned, which runs
the exact same decision-agent + guardrail pattern used everywhere else in this
project, then creates a real (test-mode) Razorpay link at the approved price.

Run with:
    uvicorn storefront.main:app --reload --port 8000
"""
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import json
import random

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent import (
    cart_actions, cart_guardrails, cart_rules_baseline, razorpay_client,
    sarvam_client, twilio_client, voice_conversation,
)
from storefront.products import CATEGORIES, PRODUCTS, PRODUCTS_BY_ID

BASE_DIR = Path(__file__).parent
app = FastAPI(title="Demo Store")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# The two agents are one system (see README's "The two agents" section) - lets
# /admin link back to the failed-payment side instead of reading as an
# unrelated project. Defaults to local dev ports; set DASHBOARD_URL once both
# are deployed so the link keeps working there too.
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:8502")

# A real store already knows who's checking out - the customer is logged in, and
# the merchant's backend already has their name/WhatsApp number from their account.
# This is what a real integration's identify() call would provide (see the
# onboarding model: the merchant's own page passes this in, we never ask the
# customer to type it again). Demo stands in for that with a small persona pool.
DEMO_CUSTOMERS = [
    {"name": "Priya Sharma", "phone": "+919876543210", "is_repeat_customer": True, "past_purchase_count": 4},
    {"name": "Rahul Verma", "phone": "+919812345678", "is_repeat_customer": False, "past_purchase_count": 0},
    {"name": "Ananya Iyer", "phone": "+919845098450", "is_repeat_customer": True, "past_purchase_count": 1},
]

# In-memory only - this is a demo storefront, not a production store.
CARTS: dict[str, dict] = {}          # session_id -> {items: {product_id: qty}, customer: {...}}
RECOVERY_EVENTS: list[dict] = []     # every abandonment event we've processed, newest first
CONTACT_COUNTS: dict[str, int] = {}  # session_id -> how many times we've already reached out.
                                      # Tracked server-side (not by the client) so a page
                                      # refresh can't reset a customer back to "first contact"
                                      # and bypass the no-discount-on-first-touch guardrail.
VOICE_CALLS: dict[str, dict] = {}    # Twilio callSid -> {system_prompt, history} for a real,
                                      # in-progress ConversationRelay call.


def _get_or_create_session(request: Request) -> str:
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in CARTS:
        session_id = str(uuid.uuid4())
        CARTS[session_id] = {"items": {}, "customer": random.choice(DEMO_CUSTOMERS)}
    return session_id


def _cart_lines(session_id: str) -> tuple[list[dict], float]:
    cart = CARTS.get(session_id, {"items": {}})
    lines = []
    total = 0.0
    for product_id, qty in cart["items"].items():
        product = PRODUCTS_BY_ID[product_id]
        line_total = product["price"] * qty
        total += line_total
        lines.append({**product, "qty": qty, "line_total": line_total})
    return lines, total


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    session_id = _get_or_create_session(request)
    lines, total = _cart_lines(session_id)
    response = templates.TemplateResponse(request, "home.html", {
        "products": PRODUCTS, "categories": CATEGORIES,
        "cart_count": sum(l["qty"] for l in lines),
        "customer": CARTS[session_id]["customer"],
    })
    response.set_cookie("session_id", session_id, httponly=True)
    return response


@app.post("/cart/add")
def add_to_cart(request: Request, product_id: str = Form(...)):
    session_id = _get_or_create_session(request)
    CARTS[session_id]["items"][product_id] = CARTS[session_id]["items"].get(product_id, 0) + 1
    response = RedirectResponse(url="/cart", status_code=303)
    response.set_cookie("session_id", session_id, httponly=True)
    return response


@app.get("/cart", response_class=HTMLResponse)
def view_cart(request: Request):
    session_id = _get_or_create_session(request)
    lines, total = _cart_lines(session_id)
    response = templates.TemplateResponse(request, "cart.html", {
        "lines": lines, "total": total, "session_id": session_id,
        "cart_count": sum(l["qty"] for l in lines),
        "customer": CARTS[session_id]["customer"],
    })
    response.set_cookie("session_id", session_id, httponly=True)
    return response


@app.get("/checkout", response_class=HTMLResponse)
def checkout(request: Request):
    session_id = _get_or_create_session(request)
    lines, total = _cart_lines(session_id)
    response = templates.TemplateResponse(request, "checkout.html", {
        "lines": lines, "total": total, "session_id": session_id,
        "cart_count": sum(l["qty"] for l in lines),
        "customer": CARTS[session_id]["customer"],
    })
    response.set_cookie("session_id", session_id, httponly=True)
    return response


@app.get("/phone", response_class=HTMLResponse)
def phone_screen(request: Request):
    """Standalone 'customer's phone' screen - no storefront chrome, just the
    call UI. Open it in its own window/tab next to the storefront for a demo
    recording; it rings in sync via BroadcastChannel the moment checkout.html
    gets a real voice_call_high_value decision back - no server round trip
    needed for the sync itself, both tabs are just listening on the same
    same-origin channel."""
    return templates.TemplateResponse(request, "phone.html", {})


@app.post("/api/cart-abandoned")
async def cart_abandoned(request: Request):
    """Called by the tracking snippet when a customer stalls or leaves checkout.
    Runs the decision agent, guardrail-checks any discount, creates a real
    test-mode Razorpay link at the approved price, and records the event so the
    /admin view can show exactly what the agent decided and why.
    """
    payload = await request.json()
    session_id = payload.get("session_id")
    lines, total = _cart_lines(session_id) if session_id in CARTS else ([], 0.0)
    if not lines:
        return {"status": "ignored", "reason": "empty cart"}

    contact_count = CONTACT_COUNTS.get(session_id, 0)
    # Identity comes from the logged-in session (what a real merchant's identify()
    # call would provide), never from the request payload - the customer never
    # typed it, so it's not ours to trust from client input.
    customer = CARTS[session_id]["customer"]

    case = {
        "cart_id": session_id,
        "customer_name": customer["name"],
        "customer_phone": customer["phone"],
        "items": [{"name": l["name"], "qty": l["qty"], "price": l["price"]} for l in lines],
        "cart_value": total,
        "abandonment_stage": payload.get("abandonment_stage", "checkout_started"),
        "is_repeat_customer": customer["is_repeat_customer"],
        "past_purchase_count": customer["past_purchase_count"],
        "contact_count": contact_count,
    }

    decision = _decide(case)
    guardrail_result = cart_guardrails.check(case, decision)
    baseline_decision = cart_rules_baseline.decide(case)
    baseline_agree = baseline_decision["proposed_action"] == decision["proposed_action"]

    discount_pct = guardrail_result.allowed_discount_pct
    final_amount = round(total * (1 - discount_pct / 100), 2)

    # Simulated conversion outcome for this demo event (no real customer behind
    # a synthetic trigger) - this is what actually makes the ROI math in /admin
    # real instead of just a cost figure with nothing to weigh it against.
    outcome = cart_actions.simulate_outcome(guardrail_result.allowed_action)
    amount_recovered = final_amount if outcome == "converted" else 0.0

    razorpay_link = None
    razorpay_error = None
    try:
        link = razorpay_client.create_payment_link({
            "case_id": f"CART-{session_id[:8]}",
            "subscription_tier": "cart-recovery",
            "amount_inr": final_amount,
            "failure_code": "cart_abandoned",
        })
        razorpay_link = link["short_url"]
    except Exception as e:
        razorpay_error = razorpay_client.friendly_error(e)

    dispatch_channel = "voice" if guardrail_result.allowed_action == "voice_call_high_value" else (
        "none" if guardrail_result.allowed_action == "no_action" else "whatsapp"
    )

    event = {
        "event_id": str(uuid.uuid4())[:8],
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "case": case,
        "proposed_action": decision["proposed_action"],
        "final_action": guardrail_result.allowed_action,
        "guardrail_overridden": guardrail_result.overridden,
        "guardrail_reason": guardrail_result.reason,
        "baseline_action": baseline_decision["proposed_action"],
        "baseline_agree": baseline_agree,
        "discount_pct": discount_pct,
        "original_amount": total,
        "final_amount": final_amount,
        "outcome": outcome,
        "amount_recovered": amount_recovered,
        "confidence": decision.get("confidence"),
        "reasoning": decision.get("reasoning"),
        "customer_message": decision.get("customer_message"),
        "razorpay_link": razorpay_link,
        "razorpay_error": razorpay_error,
        "dispatch_channel": dispatch_channel,
        # "simulated" until Twilio credentials are connected - the message/call
        # shown is exactly what WOULD go out, nothing here is faked or invented,
        # it just isn't actually transmitted yet.
        "dispatch_status": "simulated" if dispatch_channel != "none" else "no_action_needed",
    }
    RECOVERY_EVENTS.insert(0, event)
    CONTACT_COUNTS[session_id] = contact_count + 1

    return {
        "status": "processed",
        "event_id": event["event_id"],
        "final_action": event["final_action"],
        "dispatch_channel": event["dispatch_channel"],
        "customer_message": event["customer_message"],
        "customer_name": case["customer_name"],
    }


def _decide(case: dict) -> dict:
    """Live Groq decision, falling back to a safe default if the call fails
    (no key set, network issue, etc.) so a live demo never hard-crashes."""
    try:
        from agent import cart_llm_groq
        return cart_llm_groq.diagnose_and_decide(case)
    except Exception as e:
        return {
            "proposed_action": "send_reminder_no_offer",
            "discount_pct": None,
            "confidence": 0.5,
            "reasoning": f"[fallback - live decision failed: {e}]",
            "customer_message": f"Hi {case['customer_name']}, aapne kuch items cart mein "
                                 f"chhode hain - complete karna chahenge?",
        }


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    """Behind-the-scenes view of every abandonment event the agent has processed -
    what it decided, why, the guardrail trace, the AI-vs-baseline call, and the
    real payment link created."""
    events = RECOVERY_EVENTS
    total_discount_given = sum(
        (e["original_amount"] - e["final_amount"]) for e in events if e["discount_pct"]
    )
    real_links = sum(1 for e in events if e["razorpay_link"])
    guardrail_hits = sum(1 for e in events if e["guardrail_overridden"])
    avg_confidence = (
        sum(e["confidence"] for e in events if e["confidence"]) / len([e for e in events if e["confidence"]])
        if any(e["confidence"] for e in events) else None
    )
    baseline_disagreements = sum(1 for e in events if not e["baseline_agree"])

    # ROI ledger: what the agent actually spent (discounts given away + per-channel
    # action cost) against what it actually recovered (this run's simulated
    # outcomes) - the same numbers a merchant would want before trusting this with
    # real margin.
    total_recovered = sum(e["amount_recovered"] for e in events)
    total_action_cost = sum(
        cart_actions.CART_ACTION_COST_INR.get(e["final_action"], 0) for e in events
    )
    total_cost = total_discount_given + total_action_cost
    roi_multiple = (total_recovered / total_cost) if total_cost > 0 else None

    # Confidence calibration: bucket every confidence-bearing event by its stated
    # confidence and check how often that bucket's decision actually converted -
    # if the AI's "70% confident" bucket doesn't convert anywhere near 70% of the
    # time, that's the AI overstating itself, and this is where it would show up.
    calibration_buckets = _confidence_calibration(events)

    stats = {
        "total_events": len(events),
        "total_discount_given": total_discount_given,
        "real_links": real_links,
        "guardrail_hits": guardrail_hits,
        "avg_confidence": avg_confidence,
        "baseline_disagreements": baseline_disagreements,
        "total_recovered": total_recovered,
        "total_cost": total_cost,
        "roi_multiple": roi_multiple,
    }
    return templates.TemplateResponse(request, "admin.html", {
        "events": events, "stats": stats, "calibration_buckets": calibration_buckets,
        "dashboard_url": DASHBOARD_URL,
    })


_CALIBRATION_BUCKETS = [(0.0, 0.6), (0.6, 0.75), (0.75, 0.9), (0.9, 1.01)]


def _confidence_calibration(events: list[dict]) -> list[dict]:
    """Buckets events by stated confidence and reports each bucket's actual
    conversion rate - a stand-in for calibration accuracy since these are
    simulated outcomes, not graded diagnoses, but the same idea: does a higher
    stated confidence actually track a better real-world result?"""
    rows = []
    for lo, hi in _CALIBRATION_BUCKETS:
        bucket = [e for e in events if e["confidence"] is not None and lo <= e["confidence"] < hi]
        if not bucket:
            continue
        converted = sum(1 for e in bucket if e["outcome"] == "converted")
        rows.append({
            "label": f"{int(lo * 100)}-{min(int(hi * 100), 100)}%",
            "n": len(bucket),
            "conversion_rate_pct": round(100 * converted / len(bucket)),
        })
    return rows


@app.post("/api/tts")
async def tts(text: str = Form(...)):
    """Real Hinglish speech for the fake-call demo UI, via Sarvam AI (an Indian
    voice-AI company whose models are built for this, unlike a generic English
    voice mangling Hindi words). Falls back cleanly if unconfigured or it fails
    - the caller (playRecoveryCall in admin.html) uses the browser's own TTS
    in that case, so a missing key degrades quality, it never breaks the demo.
    """
    if not sarvam_client.is_configured():
        return JSONResponse({"status": "unconfigured"}, status_code=404)
    try:
        audio_bytes = sarvam_client.synthesize(text)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=502)
    return Response(content=audio_bytes, media_type="audio/wav")


@app.post("/api/place-real-call")
async def place_real_call(request: Request, event_id: str = Form(...), to_number: str = Form(None)):
    """Places a REAL outbound phone call (Twilio ConversationRelay) reading and
    responding to the caller live via the AI - deliberately a separate, explicit
    action from the guardrail-decided voice_call_high_value action itself (which
    only ever drafts a script). Nothing here fires automatically off an event;
    it only runs when this endpoint is called, which only happens when someone
    clicks the real-call button in the admin UI.

    Requires (see agent.twilio_client.place_conversation_relay_call): a
    voice-capable TWILIO_VOICE_NUMBER, ConversationRelay accepted in the Twilio
    console, and - since Twilio's servers connect INTO this app - this whole
    service reachable at a real public https URL, not localhost.
    """
    event = next((e for e in RECOVERY_EVENTS if e["event_id"] == event_id), None)
    if not event:
        return JSONResponse({"status": "error", "message": "event not found"}, status_code=404)

    to = to_number or os.environ.get("TEST_PHONE_NUMBER")
    if not to:
        return JSONResponse(
            {"status": "error", "message": "No destination number - set TEST_PHONE_NUMBER "
                                            "in .env, or pass one, and it must be a number "
                                            "verified on this Twilio account."},
            status_code=400,
        )

    case = event["case"]
    case_context = {
        "store_name": "Aura Store",
        "customer_name": case["customer_name"],
        "cart_value": event["original_amount"],
        "item_names": [i["name"] for i in case.get("items", [])],
        "discount_pct": event.get("discount_pct"),
    }
    system_prompt = voice_conversation.build_system_prompt(case_context)

    if request.url.hostname in ("127.0.0.1", "localhost"):
        return JSONResponse(
            {"status": "error", "message": "This app is running on localhost - Twilio's "
                                            "servers need to reach it over the public "
                                            "internet to stream the call, so this only "
                                            "works once deployed (e.g. to Render)."},
            status_code=400,
        )
    websocket_url = f"wss://{request.url.hostname}/voice-relay"
    greeting = f"Hi {case['customer_name']}, this is Aura Store calling about your cart."

    try:
        result = twilio_client.place_conversation_relay_call(
            to_number=to,
            websocket_url=websocket_url,
            welcome_greeting=greeting,
            custom_parameters={"event_id": event_id},
        )
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    VOICE_CALLS[event_id] = {"system_prompt": system_prompt, "history": []}
    return JSONResponse({"status": "calling", "call_sid": result["sid"]})


@app.websocket("/voice-relay")
async def voice_relay(websocket: WebSocket):
    """The live conversation loop for a real ConversationRelay call. Twilio's
    servers connect here (not a browser), stream the caller's transcribed
    speech as 'prompt' messages, and speak back whatever we send as 'text'
    messages - see agent.voice_conversation for how each reply is generated,
    and https://www.twilio.com/docs/voice/conversationrelay/websocket-messages
    for the exact message protocol this implements.
    """
    await websocket.accept()
    call_state = None

    try:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            msg_type = message.get("type")

            if msg_type == "setup":
                event_id = message.get("customParameters", {}).get("event_id")
                call_state = VOICE_CALLS.get(event_id)
                if call_state is None:
                    # Nothing we recognize (e.g. a stale/unknown call) - answer
                    # generically rather than dropping the connection outright.
                    call_state = {
                        "system_prompt": "You are a polite voice agent for Aura Store. "
                                          "Keep replies to one short sentence.",
                        "history": [],
                    }

            elif msg_type == "prompt" and message.get("last") and call_state is not None:
                call_state["history"].append({"role": "user", "content": message["voicePrompt"]})
                reply = voice_conversation.generate_reply(call_state["system_prompt"], call_state["history"])
                call_state["history"].append({"role": "assistant", "content": reply})
                await websocket.send_text(json.dumps({"type": "text", "token": reply, "last": True}))

            elif msg_type == "interrupt" and call_state is not None:
                # Caller talked over the agent - trim the last assistant turn down
                # to what was actually heard, so the next reply doesn't act like
                # the rest of the interrupted sentence was said.
                heard = message.get("utteranceUntilInterrupt", "")
                if call_state["history"] and call_state["history"][-1]["role"] == "assistant":
                    call_state["history"][-1]["content"] = heard

    except WebSocketDisconnect:
        pass
