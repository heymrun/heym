"""Find the Heym account behind an email address."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


async def find_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Return the account for an address, ignoring case and surrounding whitespace.

    Addresses are stored as typed, so ``Jane@corp.example`` must still sign in as
    ``jane@corp.example``. Instances that predate the registration check may hold several
    case variants of one address; the exact spelling wins, then the oldest account, so the
    lookup never raises on them.
    """
    typed = email.strip()
    if not typed:
        return None
    result = await db.execute(
        select(User)
        .where(func.lower(func.trim(User.email)) == typed.lower())
        .order_by((User.email == typed).desc(), User.created_at, User.id)
        .limit(1)
    )
    return result.scalar_one_or_none()
