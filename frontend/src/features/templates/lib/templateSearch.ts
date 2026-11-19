import type { NodeTemplate, WorkflowTemplate } from "../types/template.types";

function fieldsMatch(query: string, fields: Array<string | null | undefined>): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return fields.some((field) => typeof field === "string" && field.toLowerCase().includes(q));
}

/** Name, description, a tag or the type of one of its nodes, as the server matches them. */
export function workflowTemplateMatches(template: WorkflowTemplate, query: string): boolean {
  const nodeTypes = template.nodes.map((node) =>
    typeof node.type === "string" ? node.type : null,
  );
  return fieldsMatch(query, [template.name, template.description, ...template.tags, ...nodeTypes]);
}

/** Name, description, a tag or the node type, as the server matches them. */
export function nodeTemplateMatches(template: NodeTemplate, query: string): boolean {
  return fieldsMatch(query, [
    template.name,
    template.description,
    ...template.tags,
    template.node_type,
  ]);
}
