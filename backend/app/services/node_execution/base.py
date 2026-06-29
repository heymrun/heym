from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NodeExecutionContext:
    """Context passed to a node handler during workflow execution."""

    executor: Any
    node_id: str
    inputs: dict
    allow_branch_skip: bool
    start_time: float
    node: dict
    node_type: str
    node_data: dict
    node_label: str
