import type { HitlFilter, HitlSource, HitlSourceStep } from "@/types/dashboard";

/*
 * Choosing which reviews a HITL widget shows: all of them, one workflow's, or one step's of it.
 * Heym's widget Settings, the canvas properties panel and Heym Work's widget Settings all build
 * their two selects from these functions, so they agree on what is offered and what a pick means.
 * The sources are the workflows the editor can open, owned or shared with them.
 * No API, store or router imports: Heym Work imports this file.
 */

/** The select value meaning "every workflow" or "every step of it". */
export const ALL_CHOICE = "__all__";

export const STEP_FIELD_LABEL = "Select agent";
export const UNKNOWN_WORKFLOW_LABEL = "A workflow you cannot open";
export const MISSING_STEP_LABEL = "A step that no longer exists";

export interface HitlChoice {
  value: string;
  label: string;
}

function findSource(sources: HitlSource[], workflowId: string): HitlSource | undefined {
  return sources.find((source) => source.workflow_id === workflowId);
}

/** A step's name in the select; Slack steps say so, since they are not agents. */
export function stepLabel(step: HitlSourceStep): string {
  return step.kind === "slack" ? `${step.label} (Slack)` : step.label;
}

/** Every workflow with a review step, and a stored one the editor cannot see, so it can be changed. */
export function workflowChoices(sources: HitlSource[], current: HitlFilter | null): HitlChoice[] {
  const choices: HitlChoice[] = [
    { value: ALL_CHOICE, label: "All workflows" },
    ...sources.map((source) => ({ value: source.workflow_id, label: source.workflow_name })),
  ];
  if (current && !findSource(sources, current.workflow_id)) {
    choices.push({ value: current.workflow_id, label: UNKNOWN_WORKFLOW_LABEL });
  }
  return choices;
}

/**
 * The chosen workflow's steps. "All agents" leads when there are several, or when one is not
 * chosen yet. Empty when no workflow is chosen or its steps cannot be seen.
 */
export function stepChoices(sources: HitlSource[], current: HitlFilter | null): HitlChoice[] {
  const source = current ? findSource(sources, current.workflow_id) : undefined;
  if (!current || !source) return [];
  const steps = source.steps.map((step) => ({ value: step.node_id, label: stepLabel(step) }));
  const choices =
    steps.length > 1 || current.node_id === null
      ? [{ value: ALL_CHOICE, label: "All agents" }, ...steps]
      : steps;
  if (current.node_id !== null && !source.steps.some((step) => step.node_id === current.node_id)) {
    choices.push({ value: current.node_id, label: MISSING_STEP_LABEL });
  }
  return choices;
}

/** The chosen workflow's id when the editor can open it, for the "open in a new tab" link. */
export function openableWorkflowId(sources: HitlSource[], current: HitlFilter | null): string | null {
  return current && findSource(sources, current.workflow_id) ? current.workflow_id : null;
}

export function workflowValue(current: HitlFilter | null): string {
  return current?.workflow_id ?? ALL_CHOICE;
}

export function stepValue(current: HitlFilter | null): string {
  return current?.node_id ?? ALL_CHOICE;
}

/** The filter after a workflow is picked: with a single review step, that step is picked too. */
export function chooseWorkflow(
  sources: HitlSource[],
  current: HitlFilter | null,
  value: string | undefined,
): HitlFilter | null {
  if (!value || value === ALL_CHOICE) return null;
  if (current?.workflow_id === value) return current;
  const steps = findSource(sources, value)?.steps ?? [];
  return { workflow_id: value, node_id: steps.length === 1 ? steps[0].node_id : null };
}

/** The filter after a step is picked; "All agents" keeps the workflow and drops the step. */
export function chooseStep(current: HitlFilter, value: string | undefined): HitlFilter {
  return { ...current, node_id: !value || value === ALL_CHOICE ? null : value };
}

export function sameFilter(a: HitlFilter | null, b: HitlFilter | null): boolean {
  const sameWorkflow = (a?.workflow_id ?? null) === (b?.workflow_id ?? null);
  return sameWorkflow && (a?.node_id ?? null) === (b?.node_id ?? null);
}
