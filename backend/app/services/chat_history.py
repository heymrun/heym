"""Keep interrupted requests as context without treating them as pending work."""

from collections.abc import Sequence
from typing import Protocol

INTERRUPTED_TURN_INSTRUCTIONS = """

## Current request after an interruption
The user stopped the previous response and sent the latest user message immediately.
The interrupted request is background context, not a second pending task. Follow the
latest user message. When it cancels, replaces or narrows the task, discard the abandoned
plan and do not call tools for it, even to fetch background information. A request such
as "skip the workflow question, just show my teams" needs only the teams tool, not workflow
lists, run history or analytics. Do not offer to resume the abandoned task in the answer.
When the latest message instead refines the same task,
use the previous context only for the parts it still asks you to do. Do not interpret
withdrawing a question as permission to cancel or delete actual workflows.
"""


class HistoryMessage(Protocol):
    """The stored message fields the model history reads."""

    role: str
    content: str


def messages_for_chat_turn(
    messages: Sequence[HistoryMessage], *, interrupted: bool = False
) -> list[dict[str, str]]:
    """Demote the interrupted user request to context while preserving earlier history."""
    history = [{"role": message.role, "content": message.content} for message in messages]
    user_indices = [index for index, message in enumerate(history) if message["role"] == "user"]
    if interrupted and len(user_indices) >= 2:
        index = user_indices[-2]
        history[index] = {
            "role": "assistant",
            "content": (
                "The user cancelled the previous request while its response was still in "
                "progress and sent a new message. The unfinished request below is kept as "
                "background context only. It is not pending, and you do not need to answer it. "
                "Follow the user's latest message instead.\n\nCancelled request:\n\n"
                + history[index]["content"]
            ),
        }
    return history
