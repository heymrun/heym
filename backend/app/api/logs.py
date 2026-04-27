from typing import Optional

import docker
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db

router = APIRouter()

ALLOWED_CONTAINERS = {"heym-backend", "heym-frontend", "heym-postgres"}


def get_docker_client():
    try:
        client = docker.from_env()
        client.ping()
        return client
    except docker.errors.APIError:
        return None
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Failed to initialize Docker client: {str(e)}")
        return None


def validate_container_name(container_name: str) -> None:
    if container_name not in ALLOWED_CONTAINERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Container not allowed. Allowed containers: {', '.join(ALLOWED_CONTAINERS)}",
        )


@router.get("/docker/{container_name}")
async def get_docker_logs(
    container_name: str,
    lines: int = Query(100, ge=1, le=10000, description="Number of lines to retrieve"),
    since: Optional[str] = Query(None, description="Show logs since timestamp (RFC3339)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    validate_container_name(container_name)

    client = get_docker_client()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Docker client not available",
        )

    try:
        container = client.containers.get(container_name)
        logs = container.logs(tail=lines, since=since, timestamps=True).decode("utf-8")
        return {"logs": logs, "container": container_name}
    except docker.errors.NotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container {container_name} not found",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving logs: {str(e)}",
        )


@router.get("/docker/{container_name}/stream")
async def stream_docker_logs(
    container_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    validate_container_name(container_name)

    client = get_docker_client()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Docker client not available",
        )

    try:
        container = client.containers.get(container_name)

        async def generate():
            try:
                for line in container.logs(stream=True, follow=True, timestamps=True):
                    yield f"data: {line.decode('utf-8', errors='replace')}\n\n"
            except Exception as e:
                yield f"data: Error: {str(e)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except docker.errors.NotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container {container_name} not found",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error streaming logs: {str(e)}",
        )
