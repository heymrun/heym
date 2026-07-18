from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.db.models import User
from app.services.opencode_models import fetch_opencode_models

router = APIRouter()


@router.get("/models")
async def list_opencode_models(
    base_url: str | None = Query(default=None),
    _user: User = Depends(get_current_user),
) -> dict:
    """Return available OpenCode Go models (live from the zen gateway, else a hardcoded fallback)."""
    models, source = await fetch_opencode_models(base_url=base_url)
    return {"models": models, "source": source}
