"""Errors shared by every sandbox backend."""


class SandboxTimeoutError(TimeoutError):
    """The sandbox ran past its limit. Its container or pod is already removed."""


class SandboxConfigError(RuntimeError):
    """The backend cannot run this spec safely. Callers fail closed with the message."""
