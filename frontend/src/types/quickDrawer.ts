import type { NodeResult } from "@/types/workflow";

export interface QuickDrawerPreferences {
  pinnedWorkflowIds: string[];
  lastSelectedWorkflowId: string | null;
}

export interface QuickDrawerOutputNode {
  label: string;
  nodeType: string;
  outputExpression: string | null;
}

export interface QuickDrawerInputField {
  key: string;
  defaultValue?: string;
}

export interface QuickDrawerWorkflowViewModel {
  id: string;
  name: string;
  description: string | null;
  inputFields: QuickDrawerInputField[];
  outputNode: QuickDrawerOutputNode | null;
  createdAt: string;
  updatedAt: string;
  pinned: boolean;
  searchableText: string;
}

export interface QuickDrawerRunState {
  status: "idle" | "running" | "success" | "error" | "pending";
  executionId: string | null;
  outputs: Record<string, unknown> | null;
  executionTimeMs: number | null;
  executionHistoryId: string | null;
  errorMessage: string | null;
  nodeResults: NodeResult[];
  startedAt: number | null;
}
