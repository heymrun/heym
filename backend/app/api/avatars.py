import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.services.gravatar import get_gravatar

router = APIRouter()

# Short enough that a new Gravatar picture shows up within the hour.
_AVATAR_HEADERS = {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}


@router.get(
    "/{user_id}",
    response_class=Response,
    responses={
        200: {"content": {"image/*": {}}, "description": "The user's Gravatar picture"},
        304: {"description": "The cached picture is still current"},
        404: {"description": "The user has no Gravatar picture"},
    },
)
async def get_user_avatar(
    user_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Return a user's Gravatar picture; 404 means the UI should show their initial."""
    if user_id == current_user.id:
        email: str | None = current_user.email
    else:
        result = await db.execute(select(User.email).where(User.id == user_id))
        email = result.scalar_one_or_none()

    image = await get_gravatar(email) if email else None
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No avatar",
            headers=_AVATAR_HEADERS,
        )

    headers = {**_AVATAR_HEADERS, "ETag": image.etag}
    if request.headers.get("if-none-match") == image.etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=image.content, media_type=image.content_type, headers=headers)
