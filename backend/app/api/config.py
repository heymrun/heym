from fastapi import APIRouter

from app.constants import RESERVED_VARIABLE_NAMES

router = APIRouter()


@router.get("/reserved-variable-names")
async def get_reserved_variable_names() -> list[str]:
    return RESERVED_VARIABLE_NAMES
