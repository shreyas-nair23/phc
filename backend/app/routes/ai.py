"""HTTP adapters for the Gemini AI integrations."""

from __future__ import annotations
import sys
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/ai", tags=["Google AI"])


class ReorderPreviewRequest(BaseModel):
    phc_name: str
    drug_name: str
    current_stock: int = Field(ge=0)
    unit: str = "units"
    reorder_quantity: int = Field(ge=0)
    vendor_name: str
    vendor_phone: str
    target_language: str = "Kannada"
    send: bool = False


def _ai_integration_path() -> Path:
    """Return the path to ai_integration/, whether running locally or on Vercel."""
    # When deployed: /var/task/backend/ai_integration
    # When local:    <repo>/backend/ai_integration
    candidates = [
        Path(__file__).resolve().parents[3] / "ai_integration",  # local: repo/backend/ai_integration
        Path(__file__).resolve().parents[2] / "ai_integration",  # fallback
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _ensure_ai_path():
    ai_path = str(_ai_integration_path().parent)
    if ai_path not in sys.path:
        sys.path.insert(0, ai_path)


@router.post("/invoice")
async def extract_invoice(file: UploadFile = File(...)):
    """Extract structured medicine lines from an uploaded invoice photo."""
    content_type = (file.content_type or "").split(";", 1)[0]
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, or WebP image.")

    _ensure_ai_path()
    from ai_integration.gemini_vision_ocr import extract_invoice_data

    try:
        result = extract_invoice_data(
            await file.read(),
            mime_type=content_type,
            use_fallback_on_failure=False,
        )
    except RuntimeError as error:
        message = str(error)
        if "401" in message or "UNAUTHENTICATED" in message:
            detail = "Gemini rejected the API key. Check GEMINI_API_KEY in your .env file."
        elif "429" in message or "RESOURCE_EXHAUSTED" in message:
            detail = "Gemini quota exhausted. Check your Google Cloud quota and billing."
        else:
            detail = "Gemini photo extraction failed. Check the API key, quota, and image format."
        return JSONResponse(
            status_code=500,
            content={"error": "gemini_invoice_extraction_failed", "detail": detail},
        )
    return result.model_dump(mode="json")


@router.post("/audio")
async def extract_audio(
    file: UploadFile = File(...),
    mime_type: str | None = Form(None),
):
    """Transcribe a PHC voice note and return validated stock movements."""
    content_type = (mime_type or file.content_type or "audio/wav").split(";", 1)[0]
    if not content_type.startswith("audio/"):
        raise HTTPException(status_code=415, detail="Upload an audio recording.")

    _ensure_ai_path()
    from ai_integration.gemini_audio_stock_update import extract_stock_updates

    try:
        result = extract_stock_updates(
            await file.read(),
            mime_type=content_type,
            use_fallback_on_failure=False,
        )
    except RuntimeError as error:
        message = str(error)
        if "401" in message or "UNAUTHENTICATED" in message:
            detail = "Gemini rejected the API key. Check GEMINI_API_KEY in your .env file."
        elif "429" in message or "RESOURCE_EXHAUSTED" in message:
            detail = "Gemini quota exhausted."
        else:
            detail = "Gemini audio extraction failed."
        raise HTTPException(status_code=503, detail=detail) from error
    return result.model_dump(mode="json")


@router.post("/reorder-message")
def create_reorder_message(payload: ReorderPreviewRequest):
    """Compose a localized reorder SMS, dry-running unless `send` is true."""
    _ensure_ai_path()
    from ai_integration.gemini_sms_engine import LowStockAlert, dispatch_low_stock_alert

    alert = LowStockAlert(
        phc_name=payload.phc_name,
        drug_name=payload.drug_name,
        current_stock=payload.current_stock,
        unit=payload.unit,
        reorder_quantity=payload.reorder_quantity,
        vendor_name=payload.vendor_name,
        vendor_phone=payload.vendor_phone,
        target_language=payload.target_language,
    )
    result = dispatch_low_stock_alert(alert, dry_run=not payload.send)
    return result.model_dump(mode="json")
