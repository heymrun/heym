"""Code node authoring helpers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.db.models import User
from app.services.code_formatter import MAX_SOURCE_BYTES, format_python

router = APIRouter()


class CodeFormatRequest(BaseModel):
    """Python source to format."""

    code: str = Field(default="", max_length=MAX_SOURCE_BYTES)


class CodeFormatResponse(BaseModel):
    """Formatted Python source."""

    formatted: str


@router.post("/format", response_model=CodeFormatResponse)
async def format_code(
    payload: CodeFormatRequest,
    _current_user: User = Depends(get_current_user),
) -> CodeFormatResponse:
    """Format Code node Python with Ruff, preserving comments."""
    try:
        return CodeFormatResponse(formatted=format_python(payload.code))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
