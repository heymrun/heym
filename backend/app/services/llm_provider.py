import asyncio
import re

import httpx

from app.db.models import CredentialType
from app.http_identity import HEYM_USER_AGENT
from app.models.schemas import LLMModel
from app.services.opencode_catalog import is_opencode_base_url, opencode_model_protocol
from app.services.ssrf_guard import (
    SsrfBlockedError,
    build_guarded_async_http_client,
    guard_http_url,
)

OPENAI_BATCH_SUPPORT_MESSAGE = (
    "Batch mode is available for this OpenAI model and runs on the Batch API."
)
GOOGLE_BATCH_UNSUPPORTED_MESSAGE = "Batch mode is not available for Google credentials in Heym yet."
NON_OPENAI_LLM_BATCH_MESSAGE = "Batch mode is only available for OpenAI credentials in Heym."

OPENAI_RESPONSES_SUPPORT_MESSAGE = "The Responses API is available for this credential."
GOOGLE_RESPONSES_UNSUPPORTED_MESSAGE = "Google credentials do not support the Responses API."
CUSTOM_RESPONSES_SUPPORT_MESSAGE = (
    "Your gateway must support the Responses API. If it does not, runs on this node will fail."
)

OPENCODE_RESPONSES_AUTO_MESSAGE = (
    "OpenCode Go serves this model over the Responses API only, so Heym uses it automatically."
)
OPENCODE_CHAT_ONLY_MESSAGE = (
    "OpenCode Go serves this model over Chat Completions, not the Responses API."
)
OPENCODE_MESSAGES_ONLY_MESSAGE = (
    "OpenCode Go serves this model over the Anthropic Messages API, which Heym calls automatically."
)

OPENCODE_GOOGLE_ONLY_MESSAGE = (
    "OpenCode Go serves this model over Google's generateContent API, "
    "which Heym calls automatically."
)

# Every GPT generation from 5 on is a reasoning model and rejects `temperature`.
_GPT_GENERATION = re.compile(r"(?:^|[/:])gpt-(\d+)")

REASONING_MODELS = {
    "o1",
    "o1-preview",
    "o1-mini",
    "o3",
    "o3-mini",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5.1-codex",
    "gpt-5.1",
    "gemini-2.0-flash-thinking-exp",
    "gemini-exp-1206",
}


_LEGACY_OPENAI_CHAT_MARKERS = ("gpt-4", "gpt-3.5", "o1", "o3", "chatgpt")
_O_SERIES = re.compile(r"(?:^|[/:])o\d")


def is_openai_chat_model(model_id: str) -> bool:
    """Whether an id from OpenAI's /v1/models belongs in the model pickers.

    Every id the old marker list kept still passes; any GPT generation and the whole o-series
    are added, so GPT-5, GPT-6 and o4 are no longer hidden.
    """
    model_lower = model_id.lower()
    if any(marker in model_lower for marker in _LEGACY_OPENAI_CHAT_MARKERS):
        return True
    if _GPT_GENERATION.search(model_lower) is not None:
        return True
    return _O_SERIES.search(model_lower) is not None


def is_reasoning_model(model_id: str) -> bool:
    model_lower = model_id.lower()
    for reasoning in REASONING_MODELS:
        if reasoning in model_lower:
            return True
    generation = _GPT_GENERATION.search(model_lower)
    if generation is not None and int(generation.group(1)) >= 5:
        return True
    # o4-mini rejects `temperature` like o1 and o3.
    return _O_SERIES.search(model_lower) is not None


def opencode_responses_support(model_id: str) -> tuple[bool, str]:
    """Whether the OpenCode gateway offers ``model_id`` on /responses, with the UI reason."""
    protocol = opencode_model_protocol(model_id)
    if protocol == "responses":
        return True, OPENCODE_RESPONSES_AUTO_MESSAGE
    if protocol == "messages":
        return False, OPENCODE_MESSAGES_ONLY_MESSAGE
    if protocol == "google":
        return False, OPENCODE_GOOGLE_ONLY_MESSAGE
    return False, OPENCODE_CHAT_ONLY_MESSAGE


async def fetch_models(credential_type: CredentialType, config: dict) -> list[LLMModel]:
    if credential_type == CredentialType.openai:
        return await fetch_openai_models(config["api_key"])
    elif credential_type == CredentialType.google:
        return await fetch_google_models(config["api_key"])
    elif credential_type == CredentialType.custom:
        return await fetch_custom_models(config["base_url"], config["api_key"])
    return []


async def fetch_openai_models(api_key: str) -> list[LLMModel]:
    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": HEYM_USER_AGENT},
        ) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("data", []):
                model_id = model.get("id", "")
                if is_openai_chat_model(model_id):
                    models.append(
                        LLMModel(
                            id=model_id,
                            name=model_id,
                            is_reasoning=is_reasoning_model(model_id),
                            supports_batch=True,
                            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
                            supports_responses=True,
                            responses_support_reason=OPENAI_RESPONSES_SUPPORT_MESSAGE,
                        )
                    )

            models.sort(key=lambda m: (not m.is_reasoning, m.id))
            return models
    except Exception:
        return get_default_openai_models()


def get_default_openai_models() -> list[LLMModel]:
    return [
        LLMModel(
            id="o1",
            name="o1",
            is_reasoning=True,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
            supports_responses=True,
            responses_support_reason=OPENAI_RESPONSES_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="o1-mini",
            name="o1-mini",
            is_reasoning=True,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
            supports_responses=True,
            responses_support_reason=OPENAI_RESPONSES_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="o1-preview",
            name="o1-preview",
            is_reasoning=True,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
            supports_responses=True,
            responses_support_reason=OPENAI_RESPONSES_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="o3-mini",
            name="o3-mini",
            is_reasoning=True,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
            supports_responses=True,
            responses_support_reason=OPENAI_RESPONSES_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="gpt-4o",
            name="GPT-4o",
            is_reasoning=False,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
            supports_responses=True,
            responses_support_reason=OPENAI_RESPONSES_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="gpt-4o-mini",
            name="GPT-4o Mini",
            is_reasoning=False,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
            supports_responses=True,
            responses_support_reason=OPENAI_RESPONSES_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="gpt-4-turbo",
            name="GPT-4 Turbo",
            is_reasoning=False,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
            supports_responses=True,
            responses_support_reason=OPENAI_RESPONSES_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="gpt-4",
            name="GPT-4",
            is_reasoning=False,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
            supports_responses=True,
            responses_support_reason=OPENAI_RESPONSES_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="gpt-3.5-turbo",
            name="GPT-3.5 Turbo",
            is_reasoning=False,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
            supports_responses=True,
            responses_support_reason=OPENAI_RESPONSES_SUPPORT_MESSAGE,
        ),
    ]


def supports_generate_content(model: dict) -> bool:
    """Whether a Gemini /v1beta/models entry can answer chat requests.

    The list also holds Gemini models that only embed (``gemini-embedding-001``)
    or only stream audio (Live / native-audio models); they report the methods
    they serve in ``supportedGenerationMethods``. An entry without the field is
    kept, as before.
    """
    methods = model.get("supportedGenerationMethods")
    return methods is None or "generateContent" in methods


async def fetch_google_models(api_key: str) -> list[LLMModel]:
    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": HEYM_USER_AGENT},
        ) as client:
            response = await client.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            )
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("models", []):
                model_name = model.get("name", "").replace("models/", "")
                display_name = model.get("displayName", model_name)
                if "gemini" in model_name.lower() and supports_generate_content(model):
                    models.append(
                        LLMModel(
                            id=model_name,
                            name=display_name,
                            is_reasoning=is_reasoning_model(model_name),
                            supports_batch=False,
                            batch_support_reason=GOOGLE_BATCH_UNSUPPORTED_MESSAGE,
                            supports_responses=False,
                            responses_support_reason=GOOGLE_RESPONSES_UNSUPPORTED_MESSAGE,
                        )
                    )

            models.sort(key=lambda m: (not m.is_reasoning, m.id))
            return models
    except Exception:
        return get_default_google_models()


def get_default_google_models() -> list[LLMModel]:
    return [
        LLMModel(
            id="gemini-2.0-flash-thinking-exp",
            name="Gemini 2.0 Flash Thinking",
            is_reasoning=True,
            supports_batch=False,
            batch_support_reason=GOOGLE_BATCH_UNSUPPORTED_MESSAGE,
            supports_responses=False,
            responses_support_reason=GOOGLE_RESPONSES_UNSUPPORTED_MESSAGE,
        ),
        LLMModel(
            id="gemini-2.0-flash-exp",
            name="Gemini 2.0 Flash",
            is_reasoning=False,
            supports_batch=False,
            batch_support_reason=GOOGLE_BATCH_UNSUPPORTED_MESSAGE,
            supports_responses=False,
            responses_support_reason=GOOGLE_RESPONSES_UNSUPPORTED_MESSAGE,
        ),
        LLMModel(
            id="gemini-1.5-pro",
            name="Gemini 1.5 Pro",
            is_reasoning=False,
            supports_batch=False,
            batch_support_reason=GOOGLE_BATCH_UNSUPPORTED_MESSAGE,
            supports_responses=False,
            responses_support_reason=GOOGLE_RESPONSES_UNSUPPORTED_MESSAGE,
        ),
        LLMModel(
            id="gemini-1.5-flash",
            name="Gemini 1.5 Flash",
            is_reasoning=False,
            supports_batch=False,
            batch_support_reason=GOOGLE_BATCH_UNSUPPORTED_MESSAGE,
            supports_responses=False,
            responses_support_reason=GOOGLE_RESPONSES_UNSUPPORTED_MESSAGE,
        ),
        LLMModel(
            id="gemini-1.0-pro",
            name="Gemini 1.0 Pro",
            is_reasoning=False,
            supports_batch=False,
            batch_support_reason=GOOGLE_BATCH_UNSUPPORTED_MESSAGE,
            supports_responses=False,
            responses_support_reason=GOOGLE_RESPONSES_UNSUPPORTED_MESSAGE,
        ),
    ]


async def fetch_custom_models(base_url: str, api_key: str) -> list[LLMModel]:
    try:
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            url = base + "/models"
        else:
            url = base + "/v1/models"

        await asyncio.to_thread(guard_http_url, url, "Custom LLM credential base URL")
        async with await build_guarded_async_http_client(
            timeout=10.0,
            headers={"User-Agent": HEYM_USER_AGENT},
        ) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            response.raise_for_status()
            data = response.json()

            on_opencode = is_opencode_base_url(base)
            models = []
            for model in data.get("data", []):
                model_id = model.get("id", "")
                if on_opencode:
                    supports_responses, responses_reason = opencode_responses_support(model_id)
                else:
                    supports_responses, responses_reason = True, CUSTOM_RESPONSES_SUPPORT_MESSAGE
                models.append(
                    LLMModel(
                        id=model_id,
                        name=model_id,
                        is_reasoning=is_reasoning_model(model_id),
                        supports_batch=False,
                        batch_support_reason=NON_OPENAI_LLM_BATCH_MESSAGE,
                        supports_responses=supports_responses,
                        responses_support_reason=responses_reason,
                    )
                )

            models.sort(key=lambda m: m.id)
            return models
    except SsrfBlockedError:
        raise
    except Exception:
        return []
