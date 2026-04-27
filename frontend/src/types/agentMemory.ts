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
