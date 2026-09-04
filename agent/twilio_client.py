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
    using inline TwiML rather than a webhook URL - simplest path for a demo.
    One-way: the AI's message is spoken, the call doesn't listen or respond -
    see place_conversation_relay_call for the real two-way version."""
    client = _get_client()
    from_number = os.environ.get("TWILIO_VOICE_NUMBER") or os.environ["TWILIO_WHATSAPP_NUMBER"].replace("whatsapp:", "")

    twiml = f'<Response><Say voice="Polly.Aditi">{script_text}</Say></Response>'
    call = client.calls.create(from_=from_number, to=to_number, twiml=twiml)
    return {"sid": call.sid, "status": call.status}


def place_conversation_relay_call(
    to_number: str, websocket_url: str, welcome_greeting: str, custom_parameters: dict
) -> dict:
    """Place a real, two-way conversational voice call. Twilio's ConversationRelay
    connects the call to `websocket_url` (must be wss://, publicly reachable -
    Twilio's own servers connect to it, so this can never be localhost) and
    handles speech-to-text and text-to-speech itself (Deepgram + ElevenLabs by
    default); our server just receives transcribed caller speech over that socket
    and sends back the text to say next - see storefront.main's /voice-relay
    websocket route for the actual conversation loop.

    Requires, on the Twilio side (one-time, in console): Voice -> Settings ->
    Privacy & Security -> accept the Conversation Relay terms. Requires, on this
    account: at least one voice-capable number (TWILIO_VOICE_NUMBER) - if that's
    unset or the account has none provisioned, this raises before ever dialing.
    """
    client = _get_client()
    from_number = os.environ.get("TWILIO_VOICE_NUMBER")
    if not from_number:
        raise RuntimeError(
            "TWILIO_VOICE_NUMBER not set - a voice-capable Twilio number is required "
            "to place any real call, and this account currently has none provisioned "
            "(claim one free in the Twilio console, then set this env var)."
        )

    params_xml = "".join(
        f'<Parameter name="{k}" value="{v}"/>' for k, v in custom_parameters.items()
    )
    twiml = (
        "<Response><Connect>"
        f'<ConversationRelay url="{websocket_url}" welcomeGreeting="{welcome_greeting}">'
        f"{params_xml}"
        "</ConversationRelay>"
        "</Connect></Response>"
    )
    call = client.calls.create(from_=from_number, to=to_number, twiml=twiml)
    return {"sid": call.sid, "status": call.status}
