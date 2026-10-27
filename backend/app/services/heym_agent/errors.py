"""Errors the Heym Agent reports to whichever protocol called it."""


class AgentError(Exception):
    """The agent cannot run: bad arguments, bad configuration, or a busy conversation."""
