export type TemplateVisibility = "everyone" | "specific_users";

export interface WorkflowTemplate {
  id: string;
  author_id: string;
  author_name?: string | null;
  name: string;
  description: string | null;
  tags: string[];
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  canvas_snapshot: string | null;
  visibility: TemplateVisibility;
  shared_with: string[];
  shared_with_teams?: string[];
  use_count: number;
  created_at: string;
}

export interface NodeTemplate {
  id: string;
  author_id: string;
  author_name?: string | null;
  name: string;
  description: string | null;
  tags: string[];
  node_type: string;
  node_data: Record<string, unknown>;
  visibility: TemplateVisibility;
  shared_with: string[];
  shared_with_teams?: string[];
  use_count: number;
  created_at: string;
}

export interface TemplateListResponse {
  workflow_templates: WorkflowTemplate[];
  node_templates: NodeTemplate[];
}

export interface CreateWorkflowTemplatePayload {
  name: string;
  description?: string;
  tags?: string[];
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  canvas_snapshot?: string;
  visibility?: TemplateVisibility;
  shared_with?: string[];
  shared_with_teams?: string[];
}

export interface CreateNodeTemplatePayload {
  name: string;
  description?: string;
  tags?: string[];
  node_type: string;
  node_data: Record<string, unknown>;
  visibility?: TemplateVisibility;
  shared_with?: string[];
  shared_with_teams?: string[];
}

export interface CreateTemplateRequest {
  kind: "workflow" | "node";
  workflow?: CreateWorkflowTemplatePayload;
  node?: CreateNodeTemplatePayload;
}

export type TemplateKind = "workflow" | "node";

export interface UpdateTemplatePayload {
  name?: string;
  description?: string;
  tags?: string[];
  visibility?: TemplateVisibility;
  shared_with?: string[];
  shared_with_teams?: string[];
}
