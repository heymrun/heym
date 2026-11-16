"""Which workflow a trigger's webhook URL (`/webhook/{node_id}`) belongs to.

Node ids are unique only inside one workflow: the AI builder names a trigger "n1", and
"Use template" copies the template's node ids. The URL carries only the node id, so the
lookup matches a node of the trigger's own type, and when several workflows have one, it
takes the workflow whose credential verifies the request. Another owner's workflow cannot
verify a request signed with this bot's secret, so it never receives it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Workflow

# Does this credential verify the incoming request (secret token, signature)?
RequestVerifier = Callable[[AsyncSession, str], Awaitable[bool]]


async def find_trigger_workflow(
    db: AsyncSession, node_id: str, node_type: str, verifies: RequestVerifier
) -> Workflow | None:
    """The workflow whose `node_type` node has this id.

    With one such workflow, that one. With several, the most recently saved one whose
    trigger credential verifies the request; when none does, the most recently saved one,
    which the route then rejects as it would have.
    """
    result = await db.execute(
        select(Workflow)
        .where(
            text("nodes::jsonb @> (:node_filter)::jsonb").bindparams(
                node_filter=json.dumps([{"id": node_id, "type": node_type}])
            )
        )
        .order_by(Workflow.updated_at.desc())
    )
    workflows = list(result.scalars())
    if len(workflows) <= 1:
        return workflows[0] if workflows else None
    for workflow in workflows:
        node = next(
            (n for n in workflow.nodes if n.get("id") == node_id and n.get("type") == node_type),
            {},
        )
        credential_id = (node.get("data") or {}).get("credentialId")
        if credential_id and await verifies(db, str(credential_id)):
            return workflow
    return workflows[0]
