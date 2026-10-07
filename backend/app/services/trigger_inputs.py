"""Which trigger nodes receive a run's initial inputs.

Both run paths (``WorkflowExecutor.execute`` and the streaming run) hand the inputs to
these nodes through ``data["_initial_inputs"]``. ``textInput`` is handled apart, because
it also copies the text into its value.
"""

INITIAL_INPUT_TRIGGER_TYPES = frozenset(
    {
        "imapTrigger",
        "websocketTrigger",
        "slackTrigger",
        "discordTrigger",
        "telegramTrigger",
        "heymTrigger",
    }
)


def receives_initial_inputs(node: dict) -> bool:
    """Whether a trigger node other than ``textInput`` reads the run's initial inputs."""
    if node.get("type") == "rabbitmq":
        return (node.get("data") or {}).get("rabbitmqOperation") == "receive"
    return node.get("type") in INITIAL_INPUT_TRIGGER_TYPES
