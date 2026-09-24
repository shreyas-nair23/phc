"""
gemini_sms_engine.py
----------------------
Backend Dev 2 — Item 3: Multilingual SMS Engine

Purpose
=======
Take a "Low Stock" alert (drug, quantity left, vendor, vendor's phone and
preferred language) and:
  1. Ask Gemini to turn it into a natural, polite reorder message in the
     vendor's regional language (not a robotic word-for-word translation).
  2. Send that message as a real SMS via Twilio's REST API (raw `requests`
     calls, no Twilio SDK dependency).
  3. Return a structured record of what was composed and what happened,
     shaped for Backend Dev 1 to log against the order.

Same single-responsibility rule as the other two modules: this file does
not decide WHETHER to reorder (that's Backend Dev 1's dynamic-reorder
logic) and does not touch the database directly.

SAFETY DEFAULT: dispatch_low_stock_alert() defaults to dry_run=True. It
will NOT send a real SMS or spend a Twilio credit unless you explicitly
pass dry_run=False. See 03_GEMINI_SMS_SETUP.md for why.

Usage
=====
    from gemini_sms_engine import LowStockAlert, dispatch_low_stock_alert

    alert = LowStockAlert(
        phc_name="Kadugodi PHC",
        drug_name="Paracetamol 500mg",
        current_stock=12,
        unit="strips",
        reorder_quantity=200,
        vendor_name="Karnataka State Medical Supplies Corp",
        vendor_phone="9876543210",
        target_language="Kannada",
    )

    result = dispatch_low_stock_alert(alert, dry_run=True)   # preview only
    print(result.model_dump_json(indent=2))

    # result = dispatch_low_stock_alert(alert, dry_run=False)  # actually sends

Or from the command line (uses a built-in sample alert):
    python gemini_sms_engine.py            # dry run — prints what would be sent
    python gemini_sms_engine.py --send      # actually sends the SMS

Environment
===========
    GEMINI_API_KEY=your_gemini_key_here
    TWILIO_ACCOUNT_SID=your_account_sid_here
    TWILIO_AUTH_TOKEN=your_auth_token_here
    TWILIO_FROM_NUMBER=+1xxxxxxxxxx

Install
=======
    pip install google-genai pydantic python-dotenv requests
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Optional

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gemini_sms_engine")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_NAME = "gemini-2.5-flash"
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.5

_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
_TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
_TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
_TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

if not _GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY not set. Message composition will fail until it is.")
if not (_TWILIO_ACCOUNT_SID and _TWILIO_AUTH_TOKEN and _TWILIO_FROM_NUMBER):
    logger.warning(
        "Twilio credentials incomplete (need TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
        "TWILIO_FROM_NUMBER). dry_run mode will still work; real sending will not."
    )

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=_GEMINI_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LowStockAlert(BaseModel):
    """Input — what Backend Dev 1's system hands off when stock is low."""
    phc_name: str
    drug_name: str
    current_stock: int
    unit: str = "units"
    reorder_quantity: int = 0
    vendor_name: str
    vendor_phone: str = Field(description="Indian 10-digit number or E.164, e.g. '9876543210' or '+919876543210'")
    target_language: str = Field(default="English", description="e.g. 'Hindi', 'Kannada', 'Tamil', 'Telugu', 'English'")


class ReorderMessage(BaseModel):
    """Gemini's composed message — schema-enforced."""
    local_message: str = Field(description="The polite reorder request, written naturally in target_language (native script, not transliteration, unless target_language is English).")
    english_back_translation: str = Field(description="Plain English back-translation of local_message, so a non-speaker can sanity-check what's being sent.")
    language: str = Field(description="The language local_message is actually written in.")
    notes: str = Field(default="", description="Any caveats about the composition. Empty string if none.")


class DispatchResult(BaseModel):
    """Output — what gets logged against the order."""
    phc_name: str
    drug_name: str
    vendor_name: str
    vendor_phone: str
    local_message: str
    english_back_translation: str
    language: str
    char_count: int
    dry_run: bool
    sent: bool
    provider: str = "twilio"
    message_sid: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Fallback — used only if the Gemini composition call fails after retries.
# Plain English so the vendor still gets something actionable.
# ---------------------------------------------------------------------------

def _fallback_message(alert: LowStockAlert) -> ReorderMessage:
    text = (
        f"Dear {alert.vendor_name}, this is {alert.phc_name}. "
        f"Our stock of {alert.drug_name} is low ({alert.current_stock} {alert.unit} remaining). "
        f"Please arrange delivery of {alert.reorder_quantity} {alert.unit} at the earliest. Thank you."
    )
    return ReorderMessage(
        local_message=text,
        english_back_translation=text,
        language="English",
        notes="FALLBACK MESSAGE — live Gemini composition failed; plain English template used instead.",
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_INSTRUCTION = """You compose short, polite SMS reorder requests from a rural Indian \
Primary Health Centre (PHC) to a local medicine vendor.

Rules:
1. Write a natural, respectful message a real vendor would read and act on — not a robotic \
field-by-field translation of the data. Vendors in this context respond better to a courteous, \
human-sounding request than a terse data dump.
2. Write local_message in the requested target_language, in its native script (e.g. actual \
Devanagari for Hindi, actual Kannada script for Kannada) — not English transliteration — unless \
target_language is English.
3. Keep it concise enough for a single SMS (roughly under 300 characters where the language and \
politeness norms allow it).
4. Always include: the PHC name, the medicine name, and the quantity needed. Do not invent details \
not present in the input.
5. Always also provide english_back_translation — a plain English translation of exactly what \
local_message says, so someone who can't read the target script can verify nothing was distorted.
6. Output must match the provided JSON schema exactly. No prose, no markdown, no commentary \
outside the JSON."""


# ---------------------------------------------------------------------------
# Step 1: compose the localized message
# ---------------------------------------------------------------------------

def compose_reorder_message(alert: LowStockAlert, use_fallback_on_failure: bool = True) -> ReorderMessage:
    """
    Ask Gemini to turn a LowStockAlert into a natural, polite reorder SMS in
    the vendor's preferred language, with an English back-translation for
    verification.
    """
    prompt_payload = alert.model_dump()
    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            client = _get_client()
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text=f"Compose a reorder SMS from this alert data:\n{json.dumps(prompt_payload, ensure_ascii=False)}"
                            ),
                        ],
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=ReorderMessage,
                    temperature=0.4,  # a little room for natural phrasing, still low
                ),
            )

            data = json.loads(response.text)
            result = ReorderMessage.model_validate(data)
            logger.info("Message composed on attempt %d (%s, %d chars).", attempt, result.language, len(result.local_message))
            return result

        except (ValidationError, json.JSONDecodeError) as e:
            last_error = e
            logger.warning("Attempt %d: schema validation failed (%s). Retrying...", attempt, e)
        except Exception as e:
            last_error = e
            logger.warning("Attempt %d: API call failed (%s). Retrying...", attempt, e)

        if attempt <= MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    logger.error("All %d composition attempts failed. Last error: %s", MAX_RETRIES + 1, last_error)

    if use_fallback_on_failure:
        logger.warning("Using plain-English fallback message so the vendor still gets something actionable.")
        return _fallback_message(alert)

    raise RuntimeError(f"Gemini message composition failed after {MAX_RETRIES + 1} attempts") from last_error


# ---------------------------------------------------------------------------
# Step 2: normalize phone number & send via Twilio REST API (raw requests)
# ---------------------------------------------------------------------------

def _normalize_to_e164(raw_number: str, default_country_code: str = "91") -> str:
    """Best-effort normalization to E.164. Assumes India (+91) for bare
    10-digit numbers, since that's this project's context. Already-prefixed
    '+' numbers are passed through untouched."""
    digits = "".join(ch for ch in raw_number if ch.isdigit() or ch == "+")
    if digits.startswith("+"):
        return digits
    if len(digits) == 10:
        return f"+{default_country_code}{digits}"
    return f"+{digits}"


def _send_via_twilio(to_number: str, body: str) -> DispatchResult:
    """Raw REST call to Twilio's Messages endpoint — no Twilio SDK needed."""
    if not (_TWILIO_ACCOUNT_SID and _TWILIO_AUTH_TOKEN and _TWILIO_FROM_NUMBER):
        return {"sent": False, "message_sid": "", "error": "Twilio credentials not configured in .env"}

    url = f"https://api.twilio.com/2010-04-01/Accounts/{_TWILIO_ACCOUNT_SID}/Messages.json"
    payload = {"From": _TWILIO_FROM_NUMBER, "To": to_number, "Body": body}

    try:
        resp = requests.post(
            url,
            data=payload,
            auth=(_TWILIO_ACCOUNT_SID, _TWILIO_AUTH_TOKEN),
            timeout=15,
        )
        resp_json = resp.json()
        if resp.status_code in (200, 201):
            return {"sent": True, "message_sid": resp_json.get("sid", ""), "error": ""}
        return {"sent": False, "message_sid": "", "error": resp_json.get("message", f"HTTP {resp.status_code}")}
    except Exception as e:
        return {"sent": False, "message_sid": "", "error": str(e)}


# ---------------------------------------------------------------------------
# Public entry point: compose + (optionally) send
# ---------------------------------------------------------------------------

def dispatch_low_stock_alert(alert: LowStockAlert, dry_run: bool = True) -> DispatchResult:
    """
    Compose the localized reorder message and, unless dry_run is True
    (the default), send it as a real SMS via Twilio.

    dry_run=True (default): composes and returns the message, does NOT
        send anything or touch Twilio credits. Use this to review what
        would be sent before committing.
    dry_run=False: actually sends the SMS. Requires TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER in your environment, and
        (on a Twilio trial account) the recipient must be a verified
        number in the Twilio Console.
    """
    composed = compose_reorder_message(alert)
    to_number = _normalize_to_e164(alert.vendor_phone)

    if dry_run:
        logger.info("[DRY RUN] Would send to %s: %s", to_number, composed.local_message)
        send_outcome = {"sent": False, "message_sid": "", "error": ""}
    else:
        send_outcome = _send_via_twilio(to_number, composed.local_message)
        if send_outcome["sent"]:
            logger.info("SMS sent to %s (SID: %s).", to_number, send_outcome["message_sid"])
        else:
            logger.error("SMS send failed to %s: %s", to_number, send_outcome["error"])

    return DispatchResult(
        phc_name=alert.phc_name,
        drug_name=alert.drug_name,
        vendor_name=alert.vendor_name,
        vendor_phone=to_number,
        local_message=composed.local_message,
        english_back_translation=composed.english_back_translation,
        language=composed.language,
        char_count=len(composed.local_message),
        dry_run=dry_run,
        sent=send_outcome["sent"],
        message_sid=send_outcome["message_sid"],
        error=send_outcome["error"],
    )


# ---------------------------------------------------------------------------
# CLI entry point — uses a built-in sample alert so you can test with no args
# ---------------------------------------------------------------------------

_SAMPLE_ALERT = LowStockAlert(
    phc_name="Kadugodi PHC",
    drug_name="Paracetamol 500mg",
    current_stock=12,
    unit="strips",
    reorder_quantity=200,
    vendor_name="Karnataka State Medical Supplies Corp",
    vendor_phone="9876543210",   # replace with your own verified number to test a real send
    target_language="Kannada",
)

if __name__ == "__main__":
    send_for_real = "--send" in sys.argv

    if send_for_real:
        print("Sending a REAL SMS (dry_run=False)...\n")
    else:
        print("Dry run (default) — nothing will be sent. Pass --send to actually deliver.\n")

    result = dispatch_low_stock_alert(_SAMPLE_ALERT, dry_run=not send_for_real)
    print(result.model_dump_json(indent=2))
