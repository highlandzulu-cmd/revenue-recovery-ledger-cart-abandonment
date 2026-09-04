"""Text-to-speech via Sarvam AI - an Indian voice-AI company whose models are
built specifically for Hindi/Hinglish, unlike the generic Western TTS voices
(browser speechSynthesis, Twilio's Polly) used as the fallback everywhere else
in this project. Every drafted message here is already Hinglish; this is what
actually makes it sound like it, rather than a US English voice stumbling
through Hindi words.

Used only for the fake-call demo UI (agent.voice_conversation / Twilio
ConversationRelay still use their own bundled voices for the real call path -
swapping those is future work, not tonight's scope).
"""
import base64
import os

import requests

API_URL = "https://api.sarvam.ai/text-to-speech"


def is_configured() -> bool:
    return bool(os.environ.get("SARVAM_API_KEY"))


def synthesize(text: str, language_code: str = "hi-IN", speaker: str = "anushka") -> bytes:
    """Returns WAV audio bytes for `text`. Raises on any failure (missing key,
    network error, bad response) - callers should catch and fall back to
    browser TTS rather than let a demo call go silent."""
    api_key = os.environ["SARVAM_API_KEY"]
    response = requests.post(
        API_URL,
        headers={"api-subscription-key": api_key, "Content-Type": "application/json"},
        json={
            "text": text[:1500],  # bulbul:v2 limit
            "language_code": language_code,
            "speaker": speaker,
            "model": "bulbul:v2",
            "speech_sample_rate": 22050,
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    audio_b64 = data["audios"][0]
    return base64.b64decode(audio_b64)
