import httpx

from app.db.models import CredentialType
from app.http_identity import HEYM_USER_AGENT
from app.models.schemas import LLMModel

OPENAI_BATCH_SUPPORT_MESSAGE = (
    "Batch mode is available for this OpenAI model and runs on the Batch API."
)
GOOGLE_BATCH_UNSUPPORTED_MESSAGE = "Batch mode is not available for Google credentials in Heym yet."
NON_OPENAI_LLM_BATCH_MESSAGE = "Batch mode is only available for OpenAI credentials in Heym."

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


def is_reasoning_model(model_id: str) -> bool:
    model_lower = model_id.lower()
    for reasoning in REASONING_MODELS:
        if reasoning in model_lower:
            return True
    return False


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
                if any(x in model_id for x in ["gpt-4", "gpt-3.5", "o1", "o3", "chatgpt"]):
                    models.append(
                        LLMModel(
                            id=model_id,
                            name=model_id,
                            is_reasoning=is_reasoning_model(model_id),
                            supports_batch=True,
                            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
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
        ),
        LLMModel(
            id="o1-mini",
            name="o1-mini",
            is_reasoning=True,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="o1-preview",
            name="o1-preview",
            is_reasoning=True,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="o3-mini",
            name="o3-mini",
            is_reasoning=True,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="gpt-4o",
            name="GPT-4o",
            is_reasoning=False,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="gpt-4o-mini",
            name="GPT-4o Mini",
            is_reasoning=False,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="gpt-4-turbo",
            name="GPT-4 Turbo",
            is_reasoning=False,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="gpt-4",
            name="GPT-4",
            is_reasoning=False,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
        ),
        LLMModel(
            id="gpt-3.5-turbo",
            name="GPT-3.5 Turbo",
            is_reasoning=False,
            supports_batch=True,
            batch_support_reason=OPENAI_BATCH_SUPPORT_MESSAGE,
        ),
    ]


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
                if "gemini" in model_name.lower():
                    models.append(
                        LLMModel(
                            id=model_name,
                            name=display_name,
                            is_reasoning=is_reasoning_model(model_name),
                            supports_batch=False,
                            batch_support_reason=GOOGLE_BATCH_UNSUPPORTED_MESSAGE,
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
        ),
        LLMModel(
            id="gemini-2.0-flash-exp",
            name="Gemini 2.0 Flash",
            is_reasoning=False,
            supports_batch=False,
            batch_support_reason=GOOGLE_BATCH_UNSUPPORTED_MESSAGE,
        ),
        LLMModel(
            id="gemini-1.5-pro",
            name="Gemini 1.5 Pro",
            is_reasoning=False,
            supports_batch=False,
            batch_support_reason=GOOGLE_BATCH_UNSUPPORTED_MESSAGE,
        ),
        LLMModel(
            id="gemini-1.5-flash",
            name="Gemini 1.5 Flash",
            is_reasoning=False,
            supports_batch=False,
            batch_support_reason=GOOGLE_BATCH_UNSUPPORTED_MESSAGE,
        ),
        LLMModel(
            id="gemini-1.0-pro",
            name="Gemini 1.0 Pro",
            is_reasoning=False,
            supports_batch=False,
            batch_support_reason=GOOGLE_BATCH_UNSUPPORTED_MESSAGE,
        ),
    ]


async def fetch_custom_models(base_url: str, api_key: str) -> list[LLMModel]:
    try:
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            url = base + "/models"
        else:
            url = base + "/v1/models"

        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": HEYM_USER_AGENT},
        ) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("data", []):
                model_id = model.get("id", "")
                models.append(
                    LLMModel(
                        id=model_id,
                        name=model_id,
                        is_reasoning=is_reasoning_model(model_id),
                        supports_batch=False,
                        batch_support_reason=NON_OPENAI_LLM_BATCH_MESSAGE,
                    )
                )

            models.sort(key=lambda m: m.id)
            return models
    except Exception:
        return []
