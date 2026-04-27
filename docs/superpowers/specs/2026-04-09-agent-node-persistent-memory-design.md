# *Agent Node Persistent Memory (Graph-Based) - Design Spec*

***Date:** 2026-04-09
**Feature:** Persistent Memory for Agent Nodes with Knowledge Graph Visualization
**Status:** Proposed*

---

## *Overview*

*Add graph-based persistent memory functionality to Agent nodes in Heym workflows:*

1. *Enable/disable memory via checkbox on agent node*
2. *Automatically extract entities and relationships from conversations using LLM*
3. *Build and maintain a knowledge graph per agent*
4. *Visualize graph in dialog with add/edit/delete operations*
5. *Merge duplicates and update outdated information automatically*

---

## *Context & Requirements*

***User Story:**
As a workflow builder, I want agent nodes to remember conversations across executions, so the agent can accumulate knowledge about users' preferences, decisions, and history.*

***Key Requirements:***

- *Per-agent memory scope (isolated memory for each agent node)*
- *Async extraction (no workflow slowdown)*
- *Semi-aggressive deduplication (LLM decides on merges)*
- *Self-update capability (new info overrides old)*
- *Manual cleanup only (no retention policy)*
- *Visualization with edit capabilities*
- *PostgreSQL storage (new tables)*

---

## *Architecture*

### *Async Extraction Flow*

```
Workflow Execution (Main Thread)
├── Agent node runs LLM for task completion
├── Returns response to user immediately
└── Background async task triggers
    ├── LLM call #2: Extract entities/relationships
    ├── LLM call #3: Semantic deduplication check
    ├── Merge with existing graph
    └── Update database
```

***Key Decision:** Async execution ensures zero performance impact on workflow completion time.*

### *Data Model*

```sql
-- agent_memory_nodes
CREATE TABLE agent_memory_nodes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_node_id VARCHAR(64) NOT NULL,
  entity_name VARCHAR(255) NOT NULL,
  entity_type VARCHAR(50) NOT NULL,
  properties JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  confidence FLOAT DEFAULT 0.0,
  INDEX idx_agent_node_id (agent_node_id),
  INDEX idx_entity_name (entity_name)
);

-- agent_memory_edges
CREATE TABLE agent_memory_edges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_node_id VARCHAR(64) NOT NULL,
  source_node_id UUID NOT NULL REFERENCES agent_memory_nodes(id),
  target_node_id UUID NOT NULL REFERENCES agent_memory_nodes(id),
  relationship_type VARCHAR(100) NOT NULL,
  properties JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  confidence FLOAT DEFAULT 0.0,
  INDEX idx_agent_node_id (agent_node_id),
  INDEX idx_source_node_id (source_node_id),
  INDEX idx_target_node_id (target_node_id)
);
```

---

## *LLM Extraction & Deduplication*

### *Extraction Prompt*

```python
MEMORY_EXTRACTION_PROMPT = """
You extract structured memory entities and relationships from conversation history.

Conversation:
{conversation_history}

Existing Graph Nodes:
{existing_nodes}

Existing Graph Edges:
{existing_edges}

Instructions:
1. Identify entities (people, products, brands, topics) mentioned
2. Extract relationships between entities
3. EXTRACT confidence score (0.0-1.0) for each extraction
4. MARK entities that are semantically similar to existing ones
5. IDENTIFY conflicts: new info contradicts old info

Output format (JSON only):
{
  "entities": [
    {"name": string, "type": string, "properties": {}, "confidence": float, "similar_to": string|null}
  ],
  "relationships": [
    {"source": string, "target": string, "type": string, "properties": {}, "confidence": float}
  ]
}
"""
```

### *Merge Logic (Automatic, No User Review)*

```python
async def extract_and_merge_memory(
    agent_node_id: str,
    conversation_history: list[dict],
    session: AsyncSession
) -> None:
    existing_nodes = await get_existing_nodes(agent_node_id, session)
    existing_edges = await get_existing_edges(agent_node_id, session)
    extraction = await llm_call(MEMORY_EXTRACTION_PROMPT.format(...))

    # Merge entities (new OVERWRITES old)
    for entity in extraction['entities']:
        if entity['similar_to']:
            existing_node = find_node(entity['similar_to'])
            existing_node.entity_name = entity['name']
            existing_node.properties = entity['properties']
            existing_node.confidence = entity['confidence']
            existing_node.updated_at = NOW()
            await update_node(existing_node, session)
        else:
            await create_node(agent_node_id, entity, session)

    # Upsert relationships (create or overwrite)
    for rel in extraction['relationships']:
        await upsert_edge(agent_node_id, rel, session)
```

***Deduplication Rules:***

- ***Semi-aggressive:** LLM identifies semantically similar entities*
- ***New overrides old:** Latest information replaces outdated info*
- ***No user review:** Fully automatic merge process*
- ***Confidence tracking:** Store LLM confidence scores*

---

## *UI Components*

### *1. Agent Node Properties Panel (Right Panel)*

*Add checkbox at bottom of agent node configuration in the right-side Properties Panel:*

```vue
<div class="agent-memory-section">
  <Label for="agent-persistent-memory">
    Persistent Memory (Graph-Based)
  </Label>
  <Checkbox
    id="agent-persistent-memory"
    v-model="nodeData.persistentMemoryEnabled"
  />
  <p class="text-xs text-muted-foreground mt-1">
    Enable to automatically build knowledge graph from conversations
  </p>
</div>
```

### *2. Memory Link on Canvas (Next to Agent Node)*

*External link icon appears **on the canvas next to the agent node** when memory is enabled (persistentMemoryEnabled = true):*

```vue
<div
  v-if="type === 'agent' && data.persistentMemoryEnabled"
  class="absolute -right-6 top-1/2 -translate-y-1/2"
>
  <a
    :href="`/memory/agent/${data.id}`"
    target="_blank"
    class="w-6 h-6 rounded-full bg-green-500/20
              flex items-center justify-center
              text-green-500 hover:bg-green-500/30"
  >
    <ExternalLink class="w-3.5 h-3.5" />
  </a>
</div>
```

### *3. Memory Graph Dialog*

*Three-panel layout:*

- *Main: Graph canvas with force-directed layout*
- *Right: Timeline of memory additions*
- *Bottom: Edit controls (add/delete/edit nodes and edges)*

***Operations:***

- *Add Node: Text input → entity name + type*
- *Edit Node: Click node → edit name, properties*
- *Delete Node: Click node → confirm delete (cascade edges)*
- *Add Edge: Select source → target → relationship type*
- *Delete Edge: Click edge → confirm delete*
- *Edit Edge: Click edge → change type or properties*

---

## *DSL Updates*

### *Agent Node Schema Extension*

```typescript
{
  "type": "agent",
  "data": {
    "label": string,
    "persistentMemoryEnabled": boolean,  // NEW FIELD
    "systemInstruction": string,
    "userMessage": string,
    "credentialId": string,
    "model": string,
    // ... existing fields
  }
}
```

### *Example Workflow*

```json
{
  "nodes": [
    {
      "id": "agent_1",
      "type": "agent",
      "data": {
        "label": "customerAssistant",
        "persistentMemoryEnabled": true,
        "model": "gpt-4",
        "userMessage": "$input.text"
      }
    }
  ],
  "edges": []
}
```

---

## *API Endpoints*

Router is mounted at **`/api/workflows`**. `canvas_node_id` is the workflow editor node id (Vue Flow id). All routes require an authenticated user with access to the workflow.

### *Implemented routes*

| Method | Path |
|--------|------|
| GET | `/api/workflows/{workflow_id}/nodes/{canvas_node_id}/agent-memory/graph` |
| POST | `/api/workflows/{workflow_id}/nodes/{canvas_node_id}/agent-memory/nodes` |
| PUT | `/api/workflows/{workflow_id}/agent-memory/nodes/{memory_node_id}` |
| DELETE | `/api/workflows/{workflow_id}/agent-memory/nodes/{memory_node_id}` |
| POST | `/api/workflows/{workflow_id}/nodes/{canvas_node_id}/agent-memory/edges` |
| PUT | `/api/workflows/{workflow_id}/agent-memory/edges/{memory_edge_id}` |
| DELETE | `/api/workflows/{workflow_id}/agent-memory/edges/{memory_edge_id}` |

User-facing documentation: `frontend/src/docs/content/reference/agent-persistent-memory.md`.

### *Pydantic Schemas*

```python
class NodeCreateRequest(BaseModel):
    entity_name: str
    entity_type: str
    properties: dict = Field(default_factory=dict)
    confidence: float = 1.0

class NodeUpdateRequest(BaseModel):
    entity_name: str | None = None
    entity_type: str | None = None
    properties: dict | None = None
    confidence: float | None = None

class EdgeCreateRequest(BaseModel):
    source_entity_name: str
    target_entity_name: str
    relationship_type: str
    properties: dict = Field(default_factory=dict)
    confidence: float = 1.0

class MemoryGraphResponse(BaseModel):
    nodes: list[NodeResponse]
    edges: list[EdgeResponse]
```

---

## *Testing Strategy*

### *Unit Tests*

- `test_extract_entities_from_conversation()`*: Verify entity extraction*

***Note:** Only one unit test required. No integration tests or service tests.*

---

## *Implementation Tasks*

### *Backend*

1. *Create database tables (*`agent_memory_nodes`*,* `agent_memory_edges`*)*
2. *Add* `persistentMemoryEnabled` *field to workflow execution logic*
3. *Implement* `extract_and_merge_memory()` *async service*
4. *Create API endpoints for graph CRUD operations*
5. *Add background task trigger after agent execution*
6. *Write unit and integration tests*

### *Frontend*

1. *Add persistent memory checkbox to PropertiesPanel.vue*
2. *Add external link icon to BaseNode.vue for agent nodes*
3. *Create AgentMemoryGraphDialog.vue component*
4. *Implement graph visualization (force-directed layout)*
5. *Implement manual edit operations (add/delete nodes and edges)*
6. *Create timeline sidebar component*

### *Documentation*

1. *Update workflow_dsL_prompt.py with agent node schema*
2. *Use* `heym-documentation` *skill to update all existing documentation with memory feature:*
  - *Update README.md with new feature description*
  - *Update heym-web website with feature listing*
  - *Add feature documentation to docs/reference/features.md*

---

## *Success Criteria*

- *✅ Agent nodes can enable/disable persistent memory via checkbox*
- *✅ Memory extraction runs asynchronously (no workflow slowdown)*
- *✅ Knowledge graph builds automatically from conversations*
- *✅ Semi-aggressive deduplication merges similar entities*
- *✅ New information overrides outdated information*
- *✅ Users can visualize graph in dialog with edit capabilities*
- *✅ Manual add/delete/edit operations work correctly*
- *✅ All endpoint tests pass (unit + integration)*
- *✅ Documentation updated across all specified locations*

---

## *Open Questions*

*None - all requirements clarified through brainstorming process.*

---

## *Next Steps*

1. *Review and approve this design document*
2. *Invoke writing-plans skill to create detailed implementation plan*
3. *Execute implementation plan in order*
4. *Update documentation as specified*

