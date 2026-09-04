"""Real WhatsApp/voice dispatch via Twilio.

Uses API Key auth (SID + Secret + Account SID) rather than the main Auth Token -
same REST API either way. Sandbox WhatsApp numbers can only message numbers that
have joined the sandbox (sent the "join <code>" message).

As of WhatsApp's April 2025 policy, business-initiated messages need an approved
Content Template (a ContentSid, "HX...") - a raw free-form body is rejected even
within the sandbox. TWILIO_CONTENT_SID (set once the template is approved) holds
the template that wraps our AI-drafted message as its single variable.
"""
import json
import os

from twilio.rest import Client

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Client(
            os.environ["TWILIO_API_KEY_SID"],
            os.environ["TWILIO_API_KEY_SECRET"],
            os.environ["TWILIO_ACCOUNT_SID"],
        )
    return _client


def send_whatsapp(to_number: str, body: str) -> dict:
    """Send a real WhatsApp message via the Twilio sandbox, using the approved
    Content Template (TWILIO_CONTENT_SID) with our AI-drafted message passed as
    its single variable. `to_number` is a plain phone number with country code
    (e.g. +919999999999) - the whatsapp: prefix is added here."""
    client = _get_client()
    from_number = os.environ["TWILIO_WHATSAPP_NUMBER"]
    to = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"

    message = client.messages.create(
        from_=from_number,
        to=to,
        content_sid=os.environ["TWILIO_CONTENT_SID"],
        content_variables=json.dumps({"1": body}),
    )
    return {"sid": message.sid, "status": message.status}


def place_voice_call(to_number: str, script_text: str) -> dict:
    """Place a real voice call that reads `script_text` via Twilio's TTS (Polly),
    using inline TwiML rather than a webhook URL - simplest path for a demo."""
    client = _get_client()
    from_number = os.environ.get("TWILIO_VOICE_NUMBER") or os.environ["TWILIO_WHATSAPP_NUMBER"].replace("whatsapp:", "")

    twiml = f'<Response><Say voice="Polly.Aditi">{script_text}</Say></Response>'
    call = client.calls.create(from_=from_number, to=to_number, twiml=twiml)
    return {"sid": call.sid, "status": call.status}
