from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the disableNode node."""
    self = ctx.executor
    node_data = ctx.node_data

    target_node_label = node_data.get("targetNodeLabel", "")
    if not target_node_label:
        raise ValueError("disableNode requires a targetNodeLabel")

    target_node_id = None
    for nid, n in self.nodes.items():
        if n.get("data", {}).get("label") == target_node_label:
            target_node_id = nid
            break

    if not target_node_id:
        raise ValueError(f"Target node with label '{target_node_label}' not found")

    self.nodes[target_node_id]["data"]["active"] = False
    self.inactive_nodes.add(target_node_id)
    self.skipped_nodes.add(target_node_id)

    if self.workflow_id:
        from sqlalchemy.orm.attributes import flag_modified

        from app.db.models import Workflow
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            workflow = db.query(Workflow).filter(Workflow.id == self.workflow_id).first()
            if workflow:
                updated_nodes = []
                for wf_node in workflow.nodes:
                    if wf_node.get("data", {}).get("label") == target_node_label:
                        wf_node["data"]["active"] = False
                    updated_nodes.append(wf_node)
                workflow.nodes = updated_nodes
                flag_modified(workflow, "nodes")
                db.commit()

    output = {
        "targetNode": target_node_label,
        "disabled": True,
    }
    return output
