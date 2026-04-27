"""Playwright browser automation API."""

import json
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from openai import UnprocessableEntityError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Credential, CredentialShare, CredentialType, User
from app.db.session import get_db
from app.services.encryption import decrypt_config
from app.services.llm_service import execute_llm
from app.services.playwright_code_generator import (
    generate_playwright_code,
    normalize_playwright_auth_state,
)
from app.services.playwright_execution_tokens import validate_token

logger = logging.getLogger(__name__)

router = APIRouter()

AI_STEP_SYSTEM_PROMPT = """You are a Playwright automation expert. Given HTML (and optionally a screenshot description), analyze the page and return a JSON object with a "steps" array of Playwright actions to fulfill the user's instructions.

Each step must have an "action" field. Supported actions (do not use "aiStep"):
- navigate: requires "url" (full URL string)
- click: requires "selector"
- type: requires "selector" and "text"
- fill: requires "selector" and "value"
- wait: optional "timeout" (ms, default 2000)
- hover: requires "selector"
- selectOption: requires "selector" and "value"
- scrollDown: optional "amount" (pixels, default 300); optional "timeout" for post-scroll wait
- scrollUp: optional "amount" (pixels, default 300); optional "timeout" for post-scroll wait
- screenshot: optional "outputKey" (default "screenshot")
- getText: optional "selector" (default "body"); optional "timeout" (ms) to wait for visible; optional "outputKey" (default "text") — uses element text content
- getAttribute: requires "selector"; optional "attribute" (default "href"); optional "timeout"; optional "outputKey" (default "attr")
- getHTML: optional "selector" (default "body"); optional "timeout"; optional "outputKey" (default "html")
- getVisibleTextOnPage: requires "outputKey" — full page visible text (document.body.innerText); no selector; optional "timeout" (ms) waits before reading

Omit unused fields as empty strings or omit keys where the schema allows.

Return ONLY valid JSON, no markdown or explanation. Example:
{"steps": [{"action": "navigate", "url": "https://example.com"}, {"action": "getVisibleTextOnPage", "outputKey": "pageText"}]}
"""

AI_STEP_HEAL_PROMPT = """You are a Playwright automation expert. A selector failed after 2 attempts. Find an alternative locator.

Only return interaction actions: click, type, fill, hover, or selectOption (not navigate, getText, screenshot, etc.).

Use robust Playwright locators that page.locator() accepts:
- role=button[name='Login'] or role=textbox[name='Email']
- text=Exact button text
- CSS selector as fallback: button.primary

Return a JSON object with "steps" array containing ONE alternative step.
Return ONLY valid JSON, no markdown. Example:
{"steps": [{"action": "click", "selector": "role=button[name='Submit']"}]}
"""


@router.post("/generate-code")
async def generate_code(
    body: dict,
    _: User = Depends(get_current_user),
) -> dict:
    """Generate Playwright Python code from step definitions."""
    steps = body.get("steps", [])
    if not steps:
        return {"code": "# Add steps and generate code"}

    capture_network = body.get("captureNetwork", False)
    auth_enabled = body.get("authEnabled", False) is True
    auth_state = None
    if auth_enabled:
        try:
            auth_state = normalize_playwright_auth_state(body.get("authState"))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
    try:
        auth_check_timeout = int(body.get("authCheckTimeout", 5000) or 5000)
    except (TypeError, ValueError):
        auth_check_timeout = 5000

    code = generate_playwright_code(
        steps,
        capture_network=capture_network,
        auth_enabled=auth_enabled,
        auth_state=auth_state,
        auth_check_selector=str(body.get("authCheckSelector", "") or ""),
        auth_check_timeout=auth_check_timeout,
        auth_fallback_steps=body.get("authFallbackSteps") or [],
    )
    has_ai = any(s.get("action") == "aiStep" for s in steps)
    if has_ai:
        code = (
            "# AI steps: _heym_api_url and _heym_execution_token are injected at runtime\n"
            "_heym_api_url = 'http://localhost:10105'  # overridden by executor\n"
            "_heym_execution_token = ''  # overridden by executor\n\n" + code
        )
    return {"code": code}


@router.post("/ai-step")
async def ai_step(
    body: dict,
    x_execution_token: str | None = Header(None, alias="X-Execution-Token"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """LLM-powered step: analyze HTML and return Playwright actions. Called from Playwright subprocess."""
    user_id = validate_token(x_execution_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired execution token",
        )

    credential_id_raw = body.get("credentialId")
    model = body.get("model")
    try:
        credential_id = uuid.UUID(credential_id_raw) if credential_id_raw else None
    except (ValueError, TypeError):
        credential_id = None
    html = body.get("html", "")
    instructions = body.get("instructions", "")
    screenshot_base64 = body.get("screenshotBase64")
    log_steps = body.get("logStepsToConsole", False)
    save_steps = body.get("saveStepsForFuture", False)
    saved_steps = body.get("savedSteps") or []

    if not credential_id or not model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="credentialId and model are required",
        )

    user_uuid = uuid.UUID(user_id)
    result = await db.execute(
        select(Credential).where(Credential.id == credential_id, Credential.owner_id == user_uuid)
    )
    credential = result.scalar_one_or_none()
    if not credential:
        shared = await db.execute(
            select(Credential)
            .join(CredentialShare, CredentialShare.credential_id == Credential.id)
            .where(Credential.id == credential_id, CredentialShare.user_id == user_uuid)
        )
        credential = shared.scalar_one_or_none()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found or access denied",
        )

    if credential.type not in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    if save_steps and saved_steps and len(saved_steps) > 0:
        if log_steps:
            logger.info("Playwright AI step reusing %d saved steps (no LLM call)", len(saved_steps))
        return {"steps": saved_steps}

    config = decrypt_config(credential.encrypted_config)
    api_key = config.get("api_key")
    base_url = config.get("base_url")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential has no API key",
        )

    user_content = f"Instructions: {instructions}\n\nHTML:\n{html[:50000]}"
    image_input = None
    if screenshot_base64:
        image_input = f"data:image/png;base64,{screenshot_base64}"
        user_content += "\n\nA screenshot of the page is attached. Use it to understand visual layout and element positions."

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "playwright_steps",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": [
                                        "navigate",
                                        "click",
                                        "type",
                                        "fill",
                                        "wait",
                                        "hover",
                                        "selectOption",
                                        "scrollDown",
                                        "scrollUp",
                                        "screenshot",
                                        "getText",
                                        "getAttribute",
                                        "getHTML",
                                        "getVisibleTextOnPage",
                                    ],
                                },
                                "selector": {"type": "string"},
                                "url": {"type": "string"},
                                "text": {"type": "string"},
                                "value": {"type": "string"},
                                "attribute": {"type": "string"},
                                "timeout": {"type": "integer"},
                                "amount": {"type": "integer"},
                                "outputKey": {"type": "string"},
                            },
                            "required": ["action"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["steps"],
                "additionalProperties": False,
            },
        },
    }

    try:
        result = await execute_llm(
            credential_type=credential.type.value,
            api_key=api_key,
            base_url=base_url,
            model=model,
            system_instruction=AI_STEP_SYSTEM_PROMPT,
            user_message=user_content,
            temperature=0.1,
            response_format=response_format,
            image_input=image_input,
        )
    except UnprocessableEntityError as e:
        err_msg = str(e).lower()
        if image_input and ("image_url" in err_msg or "content type" in err_msg):
            logger.info("Model %s does not support images, retrying without screenshot", model)
            user_content_no_img = user_content.replace(
                "\n\nA screenshot of the page is attached. Use it to understand visual layout and element positions.",
                "",
            ).strip()
            try:
                result = await execute_llm(
                    credential_type=credential.type.value,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    system_instruction=AI_STEP_SYSTEM_PROMPT,
                    user_message=user_content_no_img,
                    temperature=0.1,
                    response_format=response_format,
                    image_input=None,
                )
            except Exception as retry_e:
                logger.exception("Playwright AI step LLM retry without image failed")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"LLM call failed: {str(retry_e)}",
                ) from retry_e
        else:
            logger.exception("Playwright AI step LLM call failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM call failed: {str(e)}",
            ) from e
    except Exception as e:
        logger.exception("Playwright AI step LLM call failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM call failed: {str(e)}",
        ) from e

    text = result.get("text", "")
    if not text:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Empty LLM response",
        )

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Playwright AI step invalid JSON: %s", text[:500])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Invalid JSON from LLM: {e}",
        ) from e

    steps = parsed.get("steps", [])
    if log_steps:
        logger.info(
            "Playwright AI step generated %d actions: %s", len(steps), json.dumps(steps)[:500]
        )

    out: dict = {"steps": steps}
    if save_steps and steps:
        out["saveSteps"] = steps
    return out


@router.post("/ai-step-heal")
async def ai_step_heal(
    body: dict,
    x_execution_token: str | None = Header(None, alias="X-Execution-Token"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """LLM-powered heal: selector failed, return alternative step using text/role locators."""
    user_id = validate_token(x_execution_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired execution token",
        )

    credential_id_raw = body.get("credentialId")
    model = body.get("model")
    try:
        credential_id = uuid.UUID(credential_id_raw) if credential_id_raw else None
    except (ValueError, TypeError):
        credential_id = None
    html = body.get("html", "")
    instructions = body.get("instructions", "")
    failed_step = body.get("failedStep") or {}
    log_steps = body.get("logStepsToConsole", False)
    screenshot_base64 = body.get("screenshotBase64")

    if not credential_id or not model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="credentialId and model are required",
        )

    if log_steps:
        logger.info(
            "Playwright AI step: step failed twice, switching to auto-heal mode (step: %s)",
            failed_step,
        )

    user_uuid = uuid.UUID(user_id)
    result = await db.execute(
        select(Credential).where(Credential.id == credential_id, Credential.owner_id == user_uuid)
    )
    credential = result.scalar_one_or_none()
    if not credential:
        shared = await db.execute(
            select(Credential)
            .join(CredentialShare, CredentialShare.credential_id == Credential.id)
            .where(Credential.id == credential_id, CredentialShare.user_id == user_uuid)
        )
        credential = shared.scalar_one_or_none()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found or access denied",
        )

    if credential.type not in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    config = decrypt_config(credential.encrypted_config)
    api_key = config.get("api_key")
    base_url = config.get("base_url")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential has no API key",
        )

    action = failed_step.get("action", "")
    selector = failed_step.get("selector", "")
    text = failed_step.get("text", "")
    value = failed_step.get("value", "")

    user_content = (
        f"The Playwright selector failed after 2 attempts.\n"
        f"Failed step: action={action}, selector={selector}, text={text}, value={value}\n"
        f"Instructions: {instructions}\n\n"
        f"HTML:\n{html[:50000]}"
    )
    image_input = None
    if screenshot_base64:
        image_input = f"data:image/png;base64,{screenshot_base64}"
        user_content += "\n\nA screenshot is attached. Use it to find the correct element."

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "playwright_heal_steps",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": [
                                        "click",
                                        "type",
                                        "fill",
                                        "hover",
                                        "selectOption",
                                    ],
                                },
                                "selector": {"type": "string"},
                                "text": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["action"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["steps"],
                "additionalProperties": False,
            },
        },
    }

    try:
        result = await execute_llm(
            credential_type=credential.type.value,
            api_key=api_key,
            base_url=base_url,
            model=model,
            system_instruction=AI_STEP_HEAL_PROMPT,
            user_message=user_content,
            temperature=0.1,
            response_format=response_format,
            image_input=image_input,
        )
    except UnprocessableEntityError as e:
        err_msg = str(e).lower()
        if image_input and ("image_url" in err_msg or "content type" in err_msg):
            logger.info(
                "Model %s does not support images for heal, retrying without screenshot", model
            )
            user_content_no_img = user_content.replace(
                "\n\nA screenshot is attached. Use it to find the correct element.",
                "",
            ).strip()
            try:
                result = await execute_llm(
                    credential_type=credential.type.value,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    system_instruction=AI_STEP_HEAL_PROMPT,
                    user_message=user_content_no_img,
                    temperature=0.1,
                    response_format=response_format,
                    image_input=None,
                )
            except Exception as retry_e:
                logger.exception("Playwright AI step heal LLM retry without image failed")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"LLM heal failed: {str(retry_e)}",
                ) from retry_e
        else:
            logger.exception("Playwright AI step heal LLM call failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM heal failed: {str(e)}",
            ) from e
    except Exception as e:
        logger.exception("Playwright AI step heal LLM call failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM heal failed: {str(e)}",
        ) from e

    text_res = result.get("text", "")
    if not text_res:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Empty LLM heal response",
        )

    try:
        parsed = json.loads(text_res)
    except json.JSONDecodeError as e:
        logger.warning("Playwright AI step heal invalid JSON: %s", text_res[:500])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Invalid JSON from LLM heal: {e}",
        ) from e

    steps = parsed.get("steps", [])
    return {"steps": steps}
