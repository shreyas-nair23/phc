"""
Vercel serverless entry point.

Vercel runs this file as the ASGI handler.  It lives at backend/api/index.py
which means sys.path must include backend/ so that `from app.main import app`
resolves correctly.
"""

import sys
from pathlib import Path

# backend/ directory — the parent of both app/ and ai_integration/
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.main import app  # noqa: E402  (import after sys.path manipulation)

__all__ = ["app"]
