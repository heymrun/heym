"""OpenCode Go (zen) model catalog: hardcoded fallback + live-list normalization."""

from __future__ import annotations

# Default OpenCode Go gateway base URL. Overridable per credential (its optional ``base_url``), not
# via an environment variable.
OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen/go/v1"

# Small known-good set of Go-gateway models; used when the live /models fetch fails.
OPENCODE_MODEL_FALLBACK: tuple[dict[str, str], ...] = (
    {"id": "opencode/kimi-k3", "name": "Kimi K3"},
    {"id": "opencode/deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
    {"id": "opencode/qwen3.7-max", "name": "Qwen3.7 Max"},
    {"id": "opencode/minimax-m3", "name": "MiniMax M3"},
)

OPENCODE_DEFAULT_MODEL = "opencode/kimi-k3"


def normalize_opencode_models(payload: object) -> list[dict[str, str]]:
    """Normalize an OpenAI-style {"data":[{"id": ...}]} payload to opencode/<id> entries."""
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
        model_id = bare if bare.startswith("opencode/") else f"opencode/{bare}"
        if model_id in seen:
            continue
        seen.add(model_id)
        name = entry.get("name")
        models.append(
            {"id": model_id, "name": name if isinstance(name, str) and name.strip() else bare}
        )
    return models
