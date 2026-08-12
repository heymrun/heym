"""OpenCode Go (zen) model catalog: hardcoded fallback + live-list normalization."""

from __future__ import annotations

# Default OpenCode Go gateway base URL. Overridable per credential (its optional ``base_url``), not
# via an environment variable.
OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen/go/v1"

# The Go gateway is its own CLI provider on models.dev; plain ``opencode`` is OpenCode Zen
# (``/zen/v1``) and rejects Go models with ``ProviderModelNotFoundError``.
OPENCODE_PROVIDER_ID = "opencode-go"
_LEGACY_PROVIDER_ID = "opencode"

# Small known-good set of Go-gateway models; used when the live /models fetch fails.
OPENCODE_MODEL_FALLBACK: tuple[dict[str, str], ...] = (
    {"id": "opencode-go/kimi-k3", "name": "Kimi K3"},
    {"id": "opencode-go/deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
    {"id": "opencode-go/qwen3.7-max", "name": "Qwen3.7 Max"},
    {"id": "opencode-go/minimax-m3", "name": "MiniMax M3"},
)

OPENCODE_DEFAULT_MODEL = "opencode-go/kimi-k3"


def qualify_model_id(model: str) -> str:
    """Return ``opencode-go/<model>``, rewriting the legacy ``opencode/<model>`` ids."""
    bare = (model or "").strip()
    if not bare:
        return ""
    if bare.startswith(f"{OPENCODE_PROVIDER_ID}/"):
        return bare
    if bare.startswith(f"{_LEGACY_PROVIDER_ID}/"):
        bare = bare[len(_LEGACY_PROVIDER_ID) + 1 :]
    return f"{OPENCODE_PROVIDER_ID}/{bare}"


def normalize_opencode_models(payload: object) -> list[dict[str, str]]:
    """Normalize an OpenAI-style {"data":[{"id": ...}]} payload to opencode-go/<id> entries."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    seen: set[str] = set()
    models: list[dict[str, str]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("id")
        if not isinstance(raw, str) or not raw.strip():
            continue
        bare = raw.strip()
        model_id = qualify_model_id(bare)
        if model_id in seen:
            continue
        seen.add(model_id)
        label = model_id.split("/", 1)[1]
        name = entry.get("name")
        models.append(
            {"id": model_id, "name": name if isinstance(name, str) and name.strip() else label}
        )
    return models
