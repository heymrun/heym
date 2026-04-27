import type { NodeTemplate } from "@/features/templates/types/template.types";
import type { NodeType, WorkflowNode } from "@/types/workflow";

import { generateId, replaceInputRefs } from "@/lib/utils";
import { NODE_DEFINITIONS } from "@/types/node";

interface SourceForRefs {
  label: string;
  type: NodeType;
}

/**
 * Build a canvas node from a saved node template (defaults merged with template data).
 */
export function buildWorkflowNodeFromNodeTemplate(
  template: NodeTemplate,
  position: { x: number; y: number },
  sourceForRefs: SourceForRefs | null,
): WorkflowNode {
  const type = template.node_type as NodeType;
  const definition = NODE_DEFINITIONS[type];
  const defaults = definition ? { ...definition.defaultData } : ({} as WorkflowNode["data"]);
  let merged = { ...defaults, ...template.node_data } as WorkflowNode["data"];
  if (sourceForRefs) {
    merged = replaceInputRefs(merged, sourceForRefs);
  }
  const data = {
    ...merged,
    label: String(template.node_data?.label ?? template.name),
  } as WorkflowNode["data"];
  return {
    id: generateId(),
    type,
    position,
    data,
  };
}
