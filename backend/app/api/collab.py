"""Canvas collaboration socket for one workflow.

Presence, cursors, live edits, follow state and voice signalling travel through this socket.
The server stores nothing: every frame is validated, stamped with the sender's identity and
published on ``collab_bus``, which hands it back to every process in the order Postgres
committed it. Opening a canvas is not an audited action, so ``audit()`` is not called here.
"""

import asyncio
import logging
import time
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket
from starlette.datastructures import Headers

from app.api.deps import resolve_token_user_id
from app.config import settings
from app.db.models import User, Workflow
from app.db.session import async_session_maker
from app.services.collab.bus import CollabPublishError, collab_bus
from app.services.collab.hub import CollabConnection, collab_hub
from app.services.collab.protocol import (
    PERMISSION_RECHECK_SECONDS,
    ProtocolError,
    RateLimiter,
    RoutedMessage,
    SessionIdentity,
    route_client_message,
    server_message,
)
from app.services.collab.wire import MAX_MESSAGE_BYTES, MessageTooLargeError
from app.services.workflow_access import get_workflow_permission

logger = logging.getLogger(__name__)

router = APIRouter()

CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_ROOM_FULL = 4429
CLOSE_POLICY = 1008
CLOSE_TOO_LARGE = 1009
CLOSE_TOO_SLOW = 1013


def origin_allowed(headers: Headers, allowed_origins: list[str]) -> bool:
    """True when the page opening the socket is Heym itself.

    The socket authenticates with the ``access_token`` cookie, which a browser attaches to a
    socket that any site opens. Checking ``Origin`` stops another site from opening one as the
    signed-in user.
    """
    origin = headers.get("origin")
    if not origin:
        return False
    if origin in allowed_origins:
        return True
    origin_host = urlsplit(origin).netloc.lower()
    for name in ("host", "x-forwarded-host"):
        value = headers.get(name)
        if value and value.split(",")[0].strip().lower() == origin_host:
            return True
    return False


async def _permission(workflow_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    async with async_session_maker() as db:
        workflow = await db.get(Workflow, workflow_id)
        if workflow is None:
            return None
        return await get_workflow_permission(db, workflow, user_id)


async def _identify(
    websocket: WebSocket, workflow_id: uuid.UUID
) -> tuple[SessionIdentity | None, int]:
    token = websocket.cookies.get("access_token")
    user_id = await resolve_token_user_id(websocket, token) if token else None
    if user_id is None:
        return None, CLOSE_UNAUTHENTICATED
    async with async_session_maker() as db:
        user = await db.get(User, user_id)
    if user is None:
        return None, CLOSE_UNAUTHENTICATED
    permission = await _permission(workflow_id, user_id)
    if permission is None:
        return None, CLOSE_FORBIDDEN
    identity = SessionIdentity(
        sid=str(uuid.uuid4()), user_id=str(user.id), name=user.name, permission=permission
    )
    return identity, 0


async def _publish_quietly(room: str, message: RoutedMessage) -> None:
    try:
        await collab_bus.publish(room, message)
    except (CollabPublishError, MessageTooLargeError):
        logger.warning("Collab message for room %s was not published", room)


@router.websocket("/{workflow_id}/collab")
async def workflow_collab_socket(websocket: WebSocket, workflow_id: uuid.UUID) -> None:
    """Join the canvas room of one workflow."""
    if not origin_allowed(websocket.headers, settings.cors_origins_list):
        await websocket.close(code=CLOSE_FORBIDDEN)
        return
    identity, close_code = await _identify(websocket, workflow_id)
    # Accept before refusing so the browser sees the close code and stops reconnecting.
    await websocket.accept()
    if identity is None:
        await websocket.close(code=close_code)
        return
    room = str(workflow_id)
    connection = CollabConnection(identity.sid)
    if not collab_hub.add(room, connection):
        await websocket.close(code=CLOSE_ROOM_FULL)
        return
    try:
        await collab_bus.ensure_started()
        await websocket.send_text(server_message("welcome", **identity.stamp()))
        await _publish_quietly(
            room,
            RoutedMessage(to=None, skip=identity.sid, data={"t": "join", "from": identity.stamp()}),
        )
        await _run_session(websocket, room, workflow_id, identity, connection)
    finally:
        collab_hub.remove(room, identity.sid)
        await _publish_quietly(
            room,
            RoutedMessage(
                to=None, skip=identity.sid, data={"t": "leave", "from": identity.stamp()}
            ),
        )


async def _run_session(
    websocket: WebSocket,
    room: str,
    workflow_id: uuid.UUID,
    identity: SessionIdentity,
    connection: CollabConnection,
) -> None:
    # Receiving stays on the request's own task; helpers that close the socket set ``closed``.
    closed = asyncio.Event()
    helpers = [
        asyncio.create_task(_send_loop(websocket, connection, closed)),
        asyncio.create_task(_recheck_loop(websocket, workflow_id, identity, closed)),
    ]
    try:
        await _receive_loop(websocket, room, identity, connection, closed)
    finally:
        for task in helpers:
            task.cancel()
        for result in await asyncio.gather(*helpers, return_exceptions=True):
            if isinstance(result, Exception):
                logger.warning("Collab session %s ended with %r", identity.sid, result)


async def _receive_loop(
    websocket: WebSocket,
    room: str,
    identity: SessionIdentity,
    connection: CollabConnection,
    closed: asyncio.Event,
) -> None:
    limiter = RateLimiter()
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect" or closed.is_set():
            return
        raw = message.get("text")
        if raw is None:
            continue
        if len(raw) > MAX_MESSAGE_BYTES or len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
            await websocket.close(code=CLOSE_TOO_LARGE)
            return
        now = time.monotonic()
        if not limiter.allow(now):
            if limiter.sustained_excess(now):
                await websocket.close(code=CLOSE_POLICY)
                return
            continue
        try:
            await collab_bus.publish(room, route_client_message(raw, identity))
        except (ProtocolError, MessageTooLargeError) as exc:
            connection.enqueue(server_message("error", message=str(exc)))
        except CollabPublishError:
            connection.enqueue(server_message("error", message="message not delivered"))


async def _send_loop(
    websocket: WebSocket, connection: CollabConnection, closed: asyncio.Event
) -> None:
    while True:
        text = await connection.queue.get()
        if connection.overflowed:
            closed.set()
            await websocket.close(code=CLOSE_TOO_SLOW)
            return
        await websocket.send_text(text)


async def _recheck_loop(
    websocket: WebSocket, workflow_id: uuid.UUID, identity: SessionIdentity, closed: asyncio.Event
) -> None:
    while True:
        await asyncio.sleep(PERMISSION_RECHECK_SECONDS)
        try:
            permission = await _permission(workflow_id, uuid.UUID(identity.user_id))
        except Exception:
            logger.warning("Collab permission recheck failed; keeping the session", exc_info=True)
            continue
        if permission is None:
            closed.set()
            await websocket.close(code=CLOSE_FORBIDDEN)
            return
        identity.permission = permission
