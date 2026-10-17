"""Slack bot endpoints: interactivity for approvals, buttons and forms, and the pickers.

Slack posts every click and modal submission to the app's Interactivity Request URL,
`/api/slack/interactions/{credential_id}`, signed with the credential's signing secret.
"""

import asyncio
import json
import logging
import uuid
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.slack import _verify_slack_signature
from app.db.models import CredentialType, User
from app.db.session import get_db
from app.models.slack_schemas import (
    SlackChannelItem,
    SlackChannelListResponse,
    SlackUserItem,
    SlackUserListResponse,
    SlackWorkspaceResponse,
)
from app.services import slack_service as slack
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config
from app.services.hitl_service import resume_hitl_request_in_background
from app.services.slack_interactions import (
    answer_for_action,
    answer_for_view,
    bot_credential,
    find_waiting_request,
    may_answer,
    record_answer,
    replace_buttons,
    user_ref,
)

logger = logging.getLogger("slack_interactions")

router = APIRouter()

_GONE = "This request is no longer waiting for an answer."
_NOT_ALLOWED = "You are not one of the people who can answer this request."
_PAGES = 5


def _ephemeral(response_url: str, text: str) -> None:
    slack.post_response_url(
        response_url, {"response_type": "ephemeral", "replace_original": False, "text": text}
    )


async def _block_action(
    db: AsyncSession,
    credential_id: str,
    config: slack.SlackBotConfig,
    payload: dict,
    background_tasks: BackgroundTasks,
) -> None:
    actions = payload.get("actions") or []
    action = actions[0] if actions and isinstance(actions[0], dict) else {}
    action_id = str(action.get("action_id") or "")
    if not action_id.startswith("heym_"):
        return
    response_url = str(payload.get("response_url") or "")
    user = user_ref(payload.get("user"))
    hitl_request = await find_waiting_request(db, str(action.get("value") or ""), credential_id)
    if hitl_request is None:
        background_tasks.add_task(_ephemeral, response_url, _GONE)
        return
    if not may_answer(hitl_request, user["id"]):
        background_tasks.add_task(_ephemeral, response_url, _NOT_ALLOWED)
        return
    key = str(action.get("value") or "")
    trigger_id = str(payload.get("trigger_id") or "")
    if action_id in (slack.ACTION_CHANGES, slack.ACTION_FORM_OPEN):
        stored = hitl_request.original_agent_output.get("_slack") or {}
        view = (
            slack.changes_modal(key)
            if action_id == slack.ACTION_CHANGES
            else slack.form_modal(
                key,
                stored.get("formTitle") or "Form",
                stored.get("fields") or [],
                stored.get("submitLabel") or "Submit",
            )
        )
        # trigger_id expires after three seconds, so the modal opens before Slack is answered.
        await asyncio.to_thread(
            slack.call_slack,
            config.bot_token,
            "views.open",
            {"trigger_id": trigger_id, "view": view},
        )
        return
    answer = answer_for_action(hitl_request, action_id, user)
    if answer is None:
        return
    if not await record_answer(db, hitl_request, answer):
        background_tasks.add_task(_ephemeral, response_url, _GONE)
        return
    background_tasks.add_task(replace_buttons, config.bot_token, hitl_request, answer.note)
    background_tasks.add_task(resume_hitl_request_in_background, hitl_request.id)


async def _view_submission(
    db: AsyncSession,
    credential_id: str,
    config: slack.SlackBotConfig,
    payload: dict,
    background_tasks: BackgroundTasks,
) -> Response:
    view = payload.get("view") if isinstance(payload.get("view"), dict) else {}
    if view.get("callback_id") not in (slack.VIEW_CHANGES, slack.VIEW_FORM):
        return Response(status_code=status.HTTP_200_OK)
    user = user_ref(payload.get("user"))
    hitl_request = await find_waiting_request(
        db, str(view.get("private_metadata") or ""), credential_id
    )
    if hitl_request is None or not may_answer(hitl_request, user["id"]):
        first_block = next(
            (block.get("block_id") for block in view.get("blocks") or [] if block.get("block_id")),
            "comment",
        )
        message = _GONE if hitl_request is None else _NOT_ALLOWED
        return JSONResponse({"response_action": "errors", "errors": {first_block: message}})
    answer = answer_for_view(hitl_request, view, user)
    if answer is not None and await record_answer(db, hitl_request, answer):
        background_tasks.add_task(replace_buttons, config.bot_token, hitl_request, answer.note)
        background_tasks.add_task(resume_hitl_request_in_background, hitl_request.id)
    return Response(status_code=status.HTTP_200_OK)


@router.post("/interactions/{credential_id}")
async def slack_interactions(
    credential_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Receive a click or a modal submission from Slack and answer the run waiting on it."""
    raw_body = await request.body()
    config = await bot_credential(db, credential_id)
    # Fails closed: no credential or no signing secret means nothing is accepted.
    if config is None or not config.signing_secret:
        logger.warning("Slack interaction rejected: credential %s cannot verify", credential_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid interactivity credential configuration",
        )
    timestamp = request.headers.get("x-slack-request-timestamp", "")
    signature = request.headers.get("x-slack-signature", "")
    if not _verify_slack_signature(config.signing_secret, raw_body, timestamp, signature):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Slack signature")
    try:
        payload: dict[str, Any] = json.loads(parse_qs(raw_body.decode("utf-8"))["payload"][0])
    except (KeyError, IndexError, ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")
    try:
        if payload.get("type") == "block_actions":
            await _block_action(db, credential_id, config, payload, background_tasks)
        elif payload.get("type") == "view_submission":
            return await _view_submission(db, credential_id, config, payload, background_tasks)
    except slack.SlackApiError as exc:
        logger.warning("Slack interaction failed for credential %s: %s", credential_id, exc)
    return Response(status_code=status.HTTP_200_OK)


async def _owned_bot_token(db: AsyncSession, credential_id: uuid.UUID, user: User) -> str:
    credential = await get_accessible_credential(db, credential_id, user.id)
    if credential is None or credential.type != CredentialType.slack_bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Slack Bot credential not found"
        )
    try:
        return slack.bot_config(decrypt_config(credential.encrypted_config)).bot_token
    except slack.SlackApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


async def _slack(token: str, method: str, params: dict) -> dict:
    try:
        return await asyncio.to_thread(slack.call_slack, token, method, params, read=True)
    except slack.SlackApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


async def _paged(token: str, method: str, params: dict, key: str) -> list[dict]:
    items: list[dict] = []
    cursor = ""
    for _ in range(_PAGES):
        body = await _slack(token, method, {**params, **({"cursor": cursor} if cursor else {})})
        items.extend(item for item in body.get(key) or [] if isinstance(item, dict))
        cursor = str((body.get("response_metadata") or {}).get("next_cursor") or "")
        if not cursor:
            break
    return items


@router.get("/bot/{credential_id}/workspace", response_model=SlackWorkspaceResponse)
async def slack_workspace(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SlackWorkspaceResponse:
    """The workspace and bot a Slack Bot credential connects to."""
    token = await _owned_bot_token(db, credential_id, current_user)
    try:
        body = await asyncio.to_thread(slack.call_slack, token, "auth.test", {})
    except slack.SlackApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return SlackWorkspaceResponse(
        team=str(body.get("team") or ""),
        team_id=str(body.get("team_id") or ""),
        bot_user=str(body.get("user") or ""),
        url=str(body.get("url") or ""),
    )


@router.get("/bot/{credential_id}/channels", response_model=SlackChannelListResponse)
async def slack_channels(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SlackChannelListResponse:
    """Channels the bot can see, public and private, for channel pickers."""
    token = await _owned_bot_token(db, credential_id, current_user)
    params = {
        "types": "public_channel,private_channel",
        "exclude_archived": "true",
        "limit": "1000",
    }
    channels = await _paged(token, "conversations.list", params, "channels")
    return SlackChannelListResponse(
        channels=sorted(
            (
                SlackChannelItem(
                    id=str(item.get("id") or ""),
                    name=str(item.get("name") or ""),
                    is_private=bool(item.get("is_private")),
                    is_member=bool(item.get("is_member")),
                )
                for item in channels
            ),
            key=lambda channel: channel.name,
        )
    )


@router.get("/bot/{credential_id}/users", response_model=SlackUserListResponse)
async def slack_users(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SlackUserListResponse:
    """People in the workspace, for person pickers."""
    token = await _owned_bot_token(db, credential_id, current_user)
    members = await _paged(token, "users.list", {"limit": "500"}, "members")
    users = [
        SlackUserItem(
            id=str(item.get("id") or ""),
            name=str(item.get("name") or ""),
            real_name=str(
                (item.get("profile") or {}).get("real_name") or item.get("real_name") or ""
            ),
            email=str((item.get("profile") or {}).get("email") or ""),
        )
        for item in members
        if not item.get("deleted") and not item.get("is_bot") and item.get("id") != "USLACKBOT"
    ]
    return SlackUserListResponse(users=sorted(users, key=lambda user: user.real_name or user.name))
