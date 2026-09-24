"""
Vercel serverless entry point — lives at repo root api/index.py.

Vercel's @vercel/python runtime:
  - Looks for this file at <root>/api/index.py
  - Looks for requirements.txt at <root>/requirements.txt
  - Sets the working directory to the repo root at runtime

So we add backend/ to sys.path so that `from app.main import app` resolves.
"""

import sys
from pathlib import Path

# repo root is the parent of api/
_REPO_ROOT   = Path(__file__).resolve().parent.parent   # phc-replenishment-engine-main/
_BACKEND_DIR = _REPO_ROOT / "backend"                   # backend/

# Both need to be on the path:
#   _BACKEND_DIR  → so `from app.xxx import …` resolves (app/ lives inside backend/)
#   _REPO_ROOT    → so any repo-root-relative imports work too
for p in (_BACKEND_DIR, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from app.main import app  # noqa: E402

__all__ = ["app"]
