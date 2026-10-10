/** What a workflow needs to be offered as a run widget, from `/workflows/with-inputs`. */
export interface RunnableWorkflow {
  name: string;
  input_fields: { key: string }[];
  file_input?: { allowed_types?: string[] } | null;
}

/** How a run widget will run the workflow, in a few words for its picker. */
export function runWidgetKind(workflow: RunnableWorkflow): string {
  if (workflow.file_input) return "takes a file";
  const keys = workflow.input_fields.map((field) => field.key);
  return keys.length > 0 ? `asks for ${keys.join(", ")}` : "runs without input";
}

/** A picker option: the workflow's name and how the widget will run it. */
export function runWidgetOption(workflow: RunnableWorkflow & { id: string }): { value: string; label: string } {
  return { value: workflow.id, label: `${workflow.name} · ${runWidgetKind(workflow)}` };
}
