"""Validation and normalization of llm node batch-mode user messages.

Batch mode requires the ``userMessage`` expression to resolve to an array of primitives.
This is llm-node-specific input handling, so it lives beside the node modules rather than
in the shared executor.
"""

from __future__ import annotations


def normalize_batch_user_messages(
    *,
    user_message: object,
    model: str,
    output_type: str,
    image_input: str | None,
) -> tuple[list[str] | None, dict | None]:
    """Return ``(messages, None)`` when batch input is usable, else ``(None, error_result)``.

    The error result is the same node output shape the executor returns for a failed LLM
    call, so callers can hand it straight back.
    """

    def _error(message: str) -> tuple[None, dict]:
        return None, {"text": "", "model": model, "error": message}

    if output_type == "image":
        return _error("Batch mode is only supported for text outputs.")
    if image_input:
        return _error("Batch mode does not support image input.")
    if not isinstance(user_message, list):
        return _error(
            "Batch mode requires the User Message expression to resolve to an array. "
            'Example: $input.items.map("item.text")'
        )
    if not user_message:
        return _error("Batch mode requires at least one item in the User Message array.")

    normalized: list[str] = []
    for item in user_message:
        if item is None:
            normalized.append("")
        elif isinstance(item, (str, int, float, bool)):
            normalized.append(str(item))
        else:
            return _error(
                "Batch mode items must resolve to strings or primitive values. "
                "Map objects into prompt strings before sending them to the LLM node."
            )
    return normalized, None
