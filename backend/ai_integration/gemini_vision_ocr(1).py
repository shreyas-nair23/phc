"""
gemini_vision_ocr.py
---------------------
Backend Dev 2 — Item 1: Gemini Vision Integration

Purpose
=======
Take a photo of a paper invoice / delivery register / medicine carton
(bytes, uploaded from the PHC staff PWA) and return VALIDATED structured
data: drug name, batch number, quantity, expiry date, etc.

This file has exactly one job: image bytes in -> validated Python object out.
It does not touch the database (that's Backend Dev 1's layer) and it does
not send anything to vendors (that's Item 3, the SMS engine).

Usage
=====
    from gemini_vision_ocr import extract_invoice_data

    with open("invoice_photo.jpg", "rb") as f:
        result = extract_invoice_data(f.read())

    print(result.model_dump_json(indent=2))

Or from the command line:
    python gemini_vision_ocr.py path/to/invoice_photo.jpg

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
from typing import List, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gemini_vision_ocr")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_NAME = "gemini-2.5-flash"
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.5

_API_KEY = os.environ.get("GEMINI_API_KEY")
if not _API_KEY:
    logger.warning(
        "GEMINI_API_KEY not set. Set it in your environment or a .env file "
        "before calling extract_invoice_data(), or calls will fail."
    )

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    """Lazy singleton client so importing this module never fails just
    because the key isn't loaded yet (useful for testing schema logic)."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Schema — this IS the hallucination guardrail.
# Gemini is forced to emit only this shape. Backend Dev 1 can import
# InvoiceExtraction directly for the DB insert layer.
# ---------------------------------------------------------------------------

class MedicineLineItem(BaseModel):
    drug_name: str = Field(description="Name of the medicine exactly as printed, e.g. 'Paracetamol 500mg'")
    batch_no: str = Field(default="", description="Batch/lot number printed on the packaging. Empty string if illegible or absent.")
    quantity: int = Field(default=0, description="Number of units/strips/boxes received. 0 if unreadable.")
    unit: str = Field(default="units", description="Unit of measure, e.g. 'strips', 'boxes', 'bottles'.")
    expiry_date: str = Field(default="", description="Expiry date in YYYY-MM-DD format if determinable, else empty string. Never guess a date.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Model's own confidence 0-1 that this line item was read correctly.")


class InvoiceExtraction(BaseModel):
    vendor_name: str = Field(default="", description="Supplier/vendor name if visible on the document, else empty string.")
    invoice_date: str = Field(default="", description="Date on the invoice in YYYY-MM-DD if determinable, else empty string.")
    line_items: List[MedicineLineItem] = Field(default_factory=list)
    extraction_notes: str = Field(default="", description="Any caveats, e.g. 'image partially blurred' or 'handwriting unclear on line 2'. Empty string if none.")


# ---------------------------------------------------------------------------
# Fallback data — used ONLY if the live API call fails after retries.
# Keeps a demo from dying on stage due to wifi/rate-limit issues.
# ---------------------------------------------------------------------------

_FALLBACK_EXTRACTION = InvoiceExtraction(
    vendor_name="Karnataka State Medical Supplies Corp",
    invoice_date="2026-09-01",
    line_items=[
        MedicineLineItem(
            drug_name="Paracetamol 500mg",
            batch_no="PCM2026A11",
            quantity=500,
            unit="strips",
            expiry_date="2027-08-31",
            confidence=0.5,
        ),
        MedicineLineItem(
            drug_name="ORS Sachets",
            batch_no="ORS2026C04",
            quantity=1000,
            unit="sachets",
            expiry_date="2028-01-31",
            confidence=0.5,
        ),
    ],
    extraction_notes="FALLBACK DATA — live Gemini extraction failed and this cached sample was used instead.",
)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_INSTRUCTION = """You are an OCR and data-extraction engine for a rural Indian Primary \
Health Centre medicine supply system. You will be shown a photo of a paper invoice, delivery \
register page, or medicine carton/box.

Rules:
1. Extract ONLY what is actually printed or written in the image. Never invent, guess, or infer \
values that are not visibly present.
2. If a field is illegible, damaged, or absent, use the schema's default (empty string / 0.0) — \
do not fabricate a plausible-looking value.
3. Dates must be normalized to YYYY-MM-DD only if you can read them with confidence. Otherwise \
leave the field empty.
4. Assign an honest per-line confidence score (0.0 to 1.0) reflecting how certain you are that \
each field was read correctly, considering handwriting legibility, image blur, and lighting.
5. If the image contains multiple medicines (e.g. a delivery register with several rows), return \
one line item per medicine.
6. Output must match the provided JSON schema exactly. No prose, no markdown, no commentary \
outside the JSON."""


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def extract_invoice_data(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    use_fallback_on_failure: bool = True,
) -> InvoiceExtraction:
    """
    Send an invoice/carton photo to Gemini and return validated structured data.

    Parameters
    ----------
    image_bytes: raw bytes of the uploaded photo (jpg/png/webp).
    mime_type: "image/jpeg", "image/png", or "image/webp".
    use_fallback_on_failure: if True (default), returns cached sample data
        instead of raising when the API call fails after retries. Set to
        False if you want calling code to handle the exception itself
        (e.g. to show the user an explicit "please retake photo" error).

    Returns
    -------
    InvoiceExtraction — always schema-valid, never raw/untrusted text.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 2):  # e.g. MAX_RETRIES=2 -> tries 1,2,3
        try:
            client = _get_client()
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                            types.Part.from_text(
                                text="Extract the medicine invoice/delivery details from this image."
                            ),
                        ],
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=InvoiceExtraction,
                    temperature=0.1,  # low temperature: we want faithful reading, not creativity
                ),
            )

            raw_text = response.text
            data = json.loads(raw_text)
            result = InvoiceExtraction.model_validate(data)

            logger.info(
                "Extraction succeeded on attempt %d: %d line item(s) found.",
                attempt, len(result.line_items),
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

    # All retries exhausted.
    logger.error("All %d attempts failed. Last error: %s", MAX_RETRIES + 1, last_error)

    if use_fallback_on_failure:
        logger.warning("Returning cached fallback extraction so the app keeps functioning.")
        return _FALLBACK_EXTRACTION

    raise RuntimeError(f"Gemini Vision extraction failed after {MAX_RETRIES + 1} attempts") from last_error


# ---------------------------------------------------------------------------
# CLI entry point for quick manual testing
# ---------------------------------------------------------------------------

def _mime_type_from_filename(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python gemini_vision_ocr.py path/to/invoice_photo.jpg")
        sys.exit(1)

    image_path = sys.argv[1]
    with open(image_path, "rb") as f:
        img_bytes = f.read()

    extraction = extract_invoice_data(img_bytes, mime_type=_mime_type_from_filename(image_path))
    print(extraction.model_dump_json(indent=2))
