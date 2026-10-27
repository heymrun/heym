"""A2A and JSON-RPC errors, numbered as the JSON-RPC binding of A2A 1.0 numbers them."""

from __future__ import annotations

from typing import Any

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002
PUSH_NOTIFICATION_NOT_SUPPORTED = -32003
UNSUPPORTED_OPERATION = -32004
CONTENT_TYPE_NOT_SUPPORTED = -32005
VERSION_NOT_SUPPORTED = -32009


class A2AError(Exception):
    """A request the agent refuses, carried back to the client as a JSON-RPC error."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def invalid_params(message: str) -> A2AError:
    return A2AError(INVALID_PARAMS, message)


def unsupported(message: str) -> A2AError:
    return A2AError(UNSUPPORTED_OPERATION, message)


def task_not_found() -> A2AError:
    return A2AError(TASK_NOT_FOUND, "Task not found.")


def task_not_cancelable() -> A2AError:
    return A2AError(TASK_NOT_CANCELABLE, "The task is finished and cannot be canceled.")


def push_not_supported() -> A2AError:
    return A2AError(
        PUSH_NOTIFICATION_NOT_SUPPORTED,
        "This agent does not send push notifications. Use SendStreamingMessage or SubscribeToTask.",
    )


def content_type_not_supported() -> A2AError:
    return A2AError(
        CONTENT_TYPE_NOT_SUPPORTED,
        "Only text and data parts are supported. Send files as links in text.",
    )


def jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def jsonrpc_error(request_id: Any, error: A2AError) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": error.code, "message": error.message},
    }
