import type { NodeType, WorkflowNode, WorkflowEdge } from "@/types/workflow";
import { INPUT_HANDLE } from "@/lib/canvasConnectionRules";

/** Primary output handle id rendered by BaseNode (see workflowEdges.resolveRenderedSourceHandle). */
const OUTPUT_HANDLE = "output";

/** Sample input the demo types into the Input node. */
export const RUNBOOK_INPUT_TEXT = "Heym runs and governs AI agents in production";

/** consoleLog message expression — logs the input upper-cased. DSL supports .upper(). */
export const RUNBOOK_LOG_EXPRESSION = "$input.text.upper()";

/** The demo workflow name created from menu entry points. */
export const RUNBOOK_WORKFLOW_NAME = "Runbook — Heym demo";

/** Query flag the editor consumes on mount to auto-play the runbook. */
export const RUNBOOK_QUERY_FLAG = "runbook";
export const RUNBOOK_QUERY_VALUE = "play";

/** Horizontal spacing between the three demo nodes. */
const NODE_DX = 320;

interface RunbookStepDef {
  type: NodeType;
  data: WorkflowNode["data"];
  /** Pause (ms) before this node slides in. */
  enterDelayMs: number;
}

/** The three real, credential-free nodes the demo builds, in order. */
export const RUNBOOK_STEPS: RunbookStepDef[] = [
  {
    type: "textInput",
    data: { label: "start", value: RUNBOOK_INPUT_TEXT, inputFields: [{ key: "text" }] },
    enterDelayMs: 300,
  },
  {
    type: "wait",
    data: { label: "wait", duration: 2000 },
    enterDelayMs: 650,
  },
  {
    type: "consoleLog",
    data: { label: "consoleLog", logMessage: RUNBOOK_LOG_EXPRESSION },
    enterDelayMs: 650,
  },
];

/**
 * Pause (ms) after the cursor starts gliding to the Run control before the
 * workflow actually executes — long enough that the run clearly starts *after*
 * the cursor lands on Run (cursor travel is ~700ms), not in parallel with it.
 */
export const RUNBOOK_RUN_DELAY_MS = 1200;

/** Build a positioned node for step `index`, marked for the entrance animation. */
export function buildRunbookNode(index: number): WorkflowNode {
  const step = RUNBOOK_STEPS[index];
  return {
    id: `node_runbook_${step.type}_${Date.now()}_${index}`,
    type: step.type,
    position: { x: index * NODE_DX, y: 0 },
    data: { ...step.data, __runbookEntrance: true },
  };
}

/** Build the edge connecting the previous node to this one (with proper ports). */
export function buildRunbookEdge(sourceId: string, targetId: string): WorkflowEdge {
  return {
    id: `edge_runbook_${sourceId}_${targetId}_${Date.now()}`,
    source: sourceId,
    target: targetId,
    sourceHandle: OUTPUT_HANDLE,
    targetHandle: INPUT_HANDLE,
  };
}

/** Sticky note that introduces the demo while the nodes build. */
export function buildRunbookStickyNode(): WorkflowNode {
  return {
    id: `node_runbook_sticky_${Date.now()}`,
    type: "sticky",
    position: { x: 0, y: -210 },
    data: {
      label: "stickyNote",
      stickyTitle: "Heym Runbook",
      stickyColor: "sky",
      note: "Heym runs and governs AI agents in production.\n\nWatch it build a tiny workflow — Input → Wait → Console Log — then run it automatically.",
    },
  };
}
