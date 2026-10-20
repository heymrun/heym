interface WorkflowOption {
  value: string;
  label: string;
}

/** `heymWorkflowId` value the backend reads as every workflow the owner can reach. */
export const HEYM_ALL_WORKFLOWS = "all";

/** Only the execution history can span workflows. */
function supportsAllWorkflows(operation: string): boolean {
  return operation === "getExecutionHistory";
}

export function heymWorkflowPickerOptions(
  operation: string,
  workflows: WorkflowOption[],
): WorkflowOption[] {
  if (supportsAllWorkflows(operation)) {
    return [{ value: HEYM_ALL_WORKFLOWS, label: "All workflows" }, ...workflows];
  }
  return [{ value: "", label: "Select a workflow..." }, ...workflows];
}

/** The workflow id to keep after the operation changes: "all" means nothing to the others. */
export function heymWorkflowIdForOperation(operation: string, workflowId: string): string {
  if (workflowId === HEYM_ALL_WORKFLOWS && !supportsAllWorkflows(operation)) return "";
  return workflowId;
}
