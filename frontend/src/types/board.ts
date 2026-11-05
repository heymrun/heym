/** The caller's access to a board. Shared boards can be read-only. */
export type BoardPermission = "owner" | "write" | "read";

export interface BoardSummary {
  id: string;
  name: string;
  description: string | null;
  column_count: number;
  card_count: number;
  mapper_model: string | null;
  mapper_credential_id: string | null;
  mapper_credential_name: string | null;
  permission: BoardPermission;
  auto_advance: boolean;
  updated_at: string;
}

export interface BoardColumnWorkflow {
  workflow_id: string;
  workflow_name: string;
  position: number;
}

export interface BoardColumn {
  id: string;
  board_id: string;
  name: string;
  position: number;
  color: string | null;
  ai_instructions: string | null;
  workflows: BoardColumnWorkflow[];
}

export type CardRunStatus = "idle" | "running" | "pending" | "success" | "failed";

export type CardPriority = "low" | "medium" | "high" | "urgent";

export interface CardFields {
  assignee_user_id: string | null;
  priority: CardPriority | null;
  /** YYYY-MM-DD */
  due_date: string | null;
  labels: string[];
}

/** Someone who can open a board, and so can be assigned its cards. */
export interface BoardMember {
  user_id: string;
  name: string | null;
  email: string;
  permission: BoardPermission;
}

/** Typed fields a write sets; a key left out keeps its value, null clears it. */
export interface CardFieldsPayload {
  assignee_user_id?: string | null;
  priority?: CardPriority | null;
  due_date?: string | null;
  labels?: string[] | null;
}

export interface BoardCard {
  id: string;
  board_id: string;
  column_id: string;
  title: string;
  content: string;
  position: number;
  run_status: CardRunStatus;
  card_metadata: Record<string, unknown>;
  fields: CardFields;
  /** Send back as expected_edit_version; a changed card answers 409. */
  edit_version: string;
  created_at: string;
  updated_at: string;
}

export interface BoardState {
  id: string;
  name: string;
  description: string | null;
  mapper_model: string | null;
  mapper_credential_id: string | null;
  mapper_credential_name: string | null;
  permission: BoardPermission;
  auto_advance: boolean;
  columns: BoardColumn[];
  cards: BoardCard[];
  has_active_runs: boolean;
}

export interface CardActivity {
  id: string;
  kind: "comment" | "event" | "output";
  author_type: "user" | "agent" | "system";
  author_user_id: string | null;
  content: string;
  data: Record<string, unknown>;
  run_id: string | null;
  created_at: string;
}

export interface CardRun {
  id: string;
  card_id: string;
  column_id: string;
  workflow_id: string | null;
  workflow_name: string;
  chain_position: number;
  chain_length: number;
  status: "running" | "pending" | "success" | "failed" | "cancelled" | "skipped";
  execution_history_id: string | null;
  active_execution_id: string | null;
  output: Record<string, unknown>;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface CardDetail {
  card: BoardCard;
  activities: CardActivity[];
  runs: CardRun[];
}

export interface BoardCreatePayload {
  name: string;
  description?: string | null;
  mapper_model?: string | null;
  mapper_credential_id?: string | null;
  auto_advance?: boolean;
}

export interface BoardUpdatePayload {
  name?: string;
  description?: string | null;
  mapper_model?: string | null;
  mapper_credential_id?: string | null;
  auto_advance?: boolean;
}

export interface ColumnUpdatePayload {
  name?: string;
  color?: string | null;
  position?: number;
  ai_instructions?: string | null;
  workflow_ids?: string[];
}

export interface CardCreatePayload extends CardFieldsPayload {
  title: string;
  content?: string;
  column_id?: string;
  position?: number;
}

export interface CardUpdatePayload extends CardFieldsPayload {
  title?: string;
  content?: string;
  card_metadata?: Record<string, unknown>;
  position?: number;
  expected_edit_version?: string;
}

export interface CardAttachment {
  file_id: string;
  name: string;
  url: string;
  mime_type: string | null;
  size: number | null;
}

export interface BoardShare {
  id: string;
  user_id: string;
  email: string;
  name: string | null;
  permission: "read" | "write";
  shared_at: string;
}

export interface BoardTeamShare {
  id: string;
  team_id: string;
  team_name: string;
  permission: "read" | "write";
  shared_at: string;
}
