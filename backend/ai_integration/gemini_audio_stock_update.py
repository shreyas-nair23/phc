"""
gemini_audio_stock_update.py
------------------------------
Backend Dev 2 — Item 2: Gemini Audio Integration

Purpose
=======
Take a short voice-note recording (a PHC staff member saying something like
"gave five paracetamol to a patient" or "received two hundred ORS packets")
and return VALIDATED structured stock-movement data: which drug, a signed
quantity delta (negative = leaving stock, positive = arriving), and the
action type.

Same single-responsibility rule as gemini_vision_ocr.py: audio bytes in,
validated Python object out. No database code here — that's Backend Dev 1's
layer. No SMS/vendor code here either — that's Item 3.

Usage
=====
    from gemini_audio_stock_update import extract_stock_updates

    with open("voice_note.wav", "rb") as f:
        result = extract_stock_updates(f.read())

    print(result.model_dump_json(indent=2))

Or from the command line:
    python gemini_audio_stock_update.py path/to/voice_note.wav

Environment
===========
Requires GEMINI_API_KEY in your environment or a .env file:
    GEMINI_API_KEY=your_key_here

Install
=======
    pip install google-genai pydantic python-dotenv
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

load_dotenv()
load_dotenv(Path(__file__).with_name(".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gemini_audio_stock_update")

# ---------------------------------------------------------------------------
# Config — deliberately identical pattern to gemini_vision_ocr.py
# ---------------------------------------------------------------------------

MODEL_NAMES = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-2.5-flash"]
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.5

_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
if not _API_KEY:
    logger.warning(
        "GEMINI_API_KEY not set. Set it in your environment or a .env file "
        "before calling extract_stock_updates(), or calls will fail."
    )

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if not _API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    if _client is None:
        _client = genai.Client(api_key=_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class StockMovement(BaseModel):
    drug_name: str = Field(description="Name of the medicine as spoken, normalized to its common form, e.g. 'Paracetamol 500mg'")
    quantity_delta: int = Field(
        default=0,
        description="Signed change in stock count. NEGATIVE if stock is leaving (dispensed to a patient, disposed as expired/damaged). POSITIVE if stock is arriving (received from vendor/transfer). 0 if action_type is 'unclear'.",
    )
    unit: str = Field(default="units", description="Unit spoken, e.g. 'strips', 'tablets', 'sachets', 'bottles'.")
    action_type: str = Field(
        default="unclear",
        description="One of: 'dispensed' (given to a patient), 'received' (arrived from vendor/transfer), 'disposed' (thrown out, e.g. expired/damaged), 'unclear' (couldn't confidently determine the action or quantity).",
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Model's own confidence 0-1 that drug, quantity, and action were all understood correctly.")


class AudioStockExtraction(BaseModel):
    raw_transcript: str = Field(default="", description="Best-effort transcript of what was said, in the language it was spoken (or transliterated). Always populate this even if extraction otherwise fails — it's the audit trail a human reviews.")
    detected_language: str = Field(default="", description="Best guess at the spoken language, e.g. 'Hindi', 'Kannada', 'Tamil', 'English'. Empty string if undeterminable.")
    movements: List[StockMovement] = Field(default_factory=list)
    extraction_notes: str = Field(default="", description="Any caveats, e.g. 'background noise made second item unclear'. Empty string if none.")


# ---------------------------------------------------------------------------
# Fallback data — used ONLY if the live API call fails after retries.
# ---------------------------------------------------------------------------

_FALLBACK_EXTRACTION = AudioStockExtraction(
    extraction_notes="Audio extraction was unavailable. No stock movement was recorded.",
)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_INSTRUCTION = """You are a speech-understanding engine for a rural Indian Primary Health \
Centre medicine stock system. You will be given a short audio recording of a PHC staff member \
speaking about medicine stock movements, in English or a regional Indian language (Hindi, \
Kannada, Tamil, Telugu, etc.), sometimes mixed.

Rules:
1. First transcribe what was actually said into `raw_transcript` (transliterate if needed) — this \
is an audit trail and must always be filled in, even if you can't confidently extract structured \
movements from it.
2. For each distinct medicine mentioned, extract one StockMovement.
3. quantity_delta must be NEGATIVE when stock is leaving the PHC (given/dispensed to a patient, \
thrown out/disposed as expired or damaged) and POSITIVE when stock is arriving (received from a \
vendor or transferred in from another PHC).
4. If you cannot confidently determine the drug name, the quantity, or the direction (dispensed \
vs received) for a mentioned item, set action_type to "unclear" and quantity_delta to 0 rather \
than guessing. A wrong invented number is worse than an honest "unclear."
5. Never invent a quantity, drug name, or direction that was not actually said or clearly implied.
6. Assign an honest confidence score (0.0-1.0) per movement based on audio clarity and how \
unambiguous the speech was.
7. Output must match the provided JSON schema exactly. No prose, no markdown, no commentary \
outside the JSON."""


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def extract_stock_updates(
    audio_bytes: bytes,
    mime_type: str = "audio/wav",
    use_fallback_on_failure: bool = False,
) -> AudioStockExtraction:
    """
    Send a voice-note recording to Gemini and return validated structured
    stock-movement data.

    Parameters
    ----------
    audio_bytes: raw bytes of the recorded clip.
    mime_type: "audio/wav", "audio/mp3", "audio/aac", "audio/ogg", or "audio/flac".
    use_fallback_on_failure: if True (default), returns cached sample data
        instead of raising when the API call fails after retries.

    Returns
    -------
    AudioStockExtraction — always schema-valid, never raw/untrusted text.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            client = _get_client()
            for model_name in MODEL_NAMES:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=[
                            types.Content(
                                role="user",
                                parts=[
                                    types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                                    types.Part.from_text(
                                        text="Transcribe this recording and extract any medicine stock movements mentioned."
                                    ),
                                ],
                            )
                        ],
                        config=types.GenerateContentConfig(
                            system_instruction=_SYSTEM_INSTRUCTION,
                            response_mime_type="application/json",
                            response_schema=AudioStockExtraction,
                            temperature=0.1,  # low temperature: faithful understanding, not creativity
                        ),
                    )
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "Gemini model %s failed on attempt %d (%s). Trying next model...",
                        model_name, attempt, e,
                    )
            else:
                logger.warning("All Gemini fallback models failed on attempt %d. Retrying...", attempt)
                if attempt <= MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue

            raw_text = response.text
            data = json.loads(raw_text)
            result = AudioStockExtraction.model_validate(data)

            logger.info(
                "Extraction succeeded on attempt %d: %d movement(s) found, language=%s.",
                attempt, len(result.movements), result.detected_language or "unknown",
            )
            return result

        except (ValidationError, json.JSONDecodeError) as e:
            last_error = e
            logger.warning("Attempt %d: Gemini output failed schema validation (%s). Retrying...", attempt, e)
        except Exception as e:  # network errors, rate limits, timeouts, etc.
            last_error = e
            logger.warning("Attempt %d: API call failed (%s). Retrying...", attempt, e)

        if attempt <= MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    logger.error("All %d attempts failed. Last error: %s", MAX_RETRIES + 1, last_error)

    if use_fallback_on_failure:
        logger.warning("Returning cached fallback extraction so the app keeps functioning.")
        return _FALLBACK_EXTRACTION

    raise RuntimeError(f"Gemini Audio extraction failed after {MAX_RETRIES + 1} attempts") from last_error


# ---------------------------------------------------------------------------
# CLI entry point for quick manual testing
# ---------------------------------------------------------------------------

def _mime_type_from_filename(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".mp3"):
        return "audio/mp3"
    if lower.endswith(".ogg"):
        return "audio/ogg"
    if lower.endswith(".aac"):
        return "audio/aac"
    if lower.endswith(".flac"):
        return "audio/flac"
    return "audio/wav"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python gemini_audio_stock_update.py path/to/voice_note.wav")
        sys.exit(1)

    audio_path = sys.argv[1]
    with open(audio_path, "rb") as f:
        clip_bytes = f.read()

    extraction = extract_stock_updates(clip_bytes, mime_type=_mime_type_from_filename(audio_path))
    print(extraction.model_dump_json(indent=2))
