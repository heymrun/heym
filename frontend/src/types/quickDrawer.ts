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

/** The file a workflow's File Upload trigger takes; the run form shows a drop zone for it. */
export interface QuickDrawerFileInput {
  label: string;
  maxSizeMb: number;
  allowedTypes: string[];
}

export interface QuickDrawerWorkflowViewModel {
  id: string;
  name: string;
  description: string | null;
  inputFields: QuickDrawerInputField[];
  fileInput: QuickDrawerFileInput | null;
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
