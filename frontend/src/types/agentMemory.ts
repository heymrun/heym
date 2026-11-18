export interface AgentMemoryNodeDTO {
  id: string;
  entity_name: string;
  entity_type: string;
  properties: Record<string, unknown>;
  confidence: number;
  created_at: string;
  updated_at: string;
}

export interface AgentMemoryEdgeDTO {
  id: string;
  source_node_id: string;
  target_node_id: string;
  relationship_type: string;
  properties: Record<string, unknown>;
  confidence: number;
  created_at: string;
  updated_at: string;
}

export interface AgentMemoryGraphResponse {
  nodes: AgentMemoryNodeDTO[];
  edges: AgentMemoryEdgeDTO[];
}

export interface AgentMemoryAiInsertRequest {
  text: string;
  credential_id: string;
  model: string;
}

export interface AgentMemoryAiInsertResponse {
  /** The graph after the insert, read in the transaction that wrote it. */
  graph: AgentMemoryGraphResponse;
  entities_applied: number;
  relationships_applied: number;
}

export interface AgentMemoryClearResponse {
  deleted_nodes: number;
  deleted_edges: number;
}
