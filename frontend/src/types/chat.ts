import type { WorkflowEdge, WorkflowNode } from "@/types/workflow"

export interface WorkflowPreview {
  id: string
  name: string
  description: string | null
  url: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export interface ToolCall {
  id: string
  name: string
  label: string
  args: Record<string, unknown>
  response_summary?: string
  elapsed_ms?: number
  status: 'running' | 'success' | 'error' | 'compressed' | 'cancelled'
}

export interface ContextBreakdown {
  system: number
  agents_md: number
  workflows: number
  user_rules: number
  history: number
  attachment: number
}

export interface ContextUsage {
  used: number
  limit: number
  breakdown: ContextBreakdown
}

export interface Conversation {
  id: string
  title: string
  is_pinned: boolean
  is_running: boolean
  has_unread: boolean
  created_at: string
  updated_at: string
}

export interface QueuedMessage {
  id: string
  content: string
  credential_id: string
  model: string
  attachment_name: string | null
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  images?: string[]
  attachmentName?: string
  workflowPreview?: WorkflowPreview
  tool_calls?: ToolCall[]
  created_at: string
}

export interface ConversationDetail extends Conversation {
  last_credential_id: string | null
  last_model: string | null
  messages: Message[]
  queued_messages: QueuedMessage[]
}

export interface ConversationCreate {
  title?: string
}

export interface ConversationUpdate {
  title?: string
  is_pinned?: boolean
}

export interface MessageCreate {
  content: string
  credential_id: string
  model: string
}

export interface SendMessageResponse {
  conversation_id: string
  status: 'started' | 'queued'
  user_message: Message | null
  queued_message: QueuedMessage | null
}

export type SSEChunk =
  | { type: 'content'; text: string; message_id?: string }
  | { type: 'tool_start'; id: string; name: string; label: string; args: Record<string, unknown>; message_id?: string }
  | { type: 'tool_end'; id: string; response_summary: string; elapsed_ms: number; status: 'success' | 'error'; message_id?: string }
  | { type: 'compressed'; messages_compressed: number; tokens_before: number; tokens_after: number; elapsed_ms: number; message_id?: string }
  | { type: 'context'; used: number; limit: number; breakdown: ContextBreakdown }
  | { type: 'tool_output'; images: string[] }
  | { type: 'workflow_created'; workflow: WorkflowPreview; message_id?: string }
  | { type: 'title'; title: string }
  | { type: 'assistant_done'; message_id?: string; paused_for_clarification?: boolean; cancelled?: boolean }
  | { type: 'queued_message_created'; queued_message: QueuedMessage }
  | { type: 'queued_message_updated'; queued_message: QueuedMessage }
  | { type: 'queued_message_deleted'; queued_message_id: string }
  | { type: 'queue_cleared' }
  | { type: 'queued_message_started'; queued_message_id: string; user_message: Message }
  | { type: 'done' }
  | { type: 'error'; text?: string; message?: string }
