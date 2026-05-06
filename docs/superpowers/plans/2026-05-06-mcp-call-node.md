# MCP Call Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone `mcpCall` node type that calls a specific MCP tool directly without an LLM.

**Architecture:** New `mcpCall` node reuses the existing `AgentMCPConnection` interface, `execute_mcp_tool` function, and `/api/mcp/fetch-tools` endpoint. Backend adds a new `elif node_type == "mcpCall"` branch in `workflow_executor.py`. Frontend adds a new PropertiesPanel section with connection config, tool fetch, tool dropdown, and argument fields auto-rendered from the tool's inputSchema (which requires extending `MCPFetchToolItem` to carry schema). The node is blocked from being used as an agent tool via `BLOCKED_AS_TOOL`.

**Tech Stack:** Python 3.11 + FastAPI + Pydantic (backend), Vue 3 + TypeScript strict + Bun (frontend), pytest + unittest (tests), Next.js + TypeScript (heymweb landing page)

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `backend/app/models/schemas.py` | Modify | Add `inputSchema` field to `MCPFetchToolItem` |
| `backend/app/api/mcp.py` | Modify | Include `parameters` in fetch-tools response |
| `backend/app/services/workflow_executor.py` | Modify | Add `elif node_type == "mcpCall"` branch |
| `backend/app/services/workflow_dsl_prompt.py` | Modify | Add `### 30. mcpCall` section |
| `backend/tests/test_mcp_call_node.py` | Create | 7 unit tests for mcpCall executor logic |
| `frontend/src/types/workflow.ts` | Modify | Add `"mcpCall"` to `NodeType` union |
| `frontend/src/types/node.ts` | Modify | Add `mcpCall` entry to `NODE_DEFINITIONS` |
| `frontend/src/services/api.ts` | Modify | Add `inputSchema` to `MCPFetchToolItem` interface |
| `frontend/src/components/Canvas/WorkflowCanvas.vue` | Modify | Add `"mcpCall"` to `BLOCKED_AS_TOOL` |
| `frontend/src/components/Panels/PropertiesPanel.vue` | Modify | Add mcpCall script functions + template section |
| `frontend/src/docs/content/nodes/mcp-call-node.md` | Create | Node documentation (via heym-documentation skill) |
| `heymweb/src/components/sections/NodesSection.tsx` | Modify | Add mcpCall entry to `nodes` array |

---

## Task 1: Extend MCPFetchToolItem to carry inputSchema

**Files:**
- Modify: `backend/app/models/schemas.py` (around line 794)
- Modify: `backend/app/api/mcp.py` (around line 485)
- Modify: `frontend/src/services/api.ts` (around line 1409)

### Why this comes first
The frontend needs inputSchema to auto-render argument fields when a tool is selected. Extending the schema first means all subsequent tasks can rely on it.

- [ ] **Step 1: Update MCPFetchToolItem in schemas.py**

Find the class at line ~794:
```python
class MCPFetchToolItem(BaseModel):
    name: str
    description: str
```

Change it to:
```python
class MCPFetchToolItem(BaseModel):
    name: str
    description: str
    inputSchema: dict | None = None
```

- [ ] **Step 2: Update fetch-tools endpoint in mcp.py to include inputSchema**

Find lines ~483-487 in `backend/app/api/mcp.py`:
```python
    tools = [
        MCPFetchToolItem(name=t.get("name", ""), description=t.get("description") or "")
        for t in raw_tools
    ]
```

Replace with:
```python
    tools = [
        MCPFetchToolItem(
            name=t.get("name", ""),
            description=t.get("description") or "",
            inputSchema=t.get("parameters") or None,
        )
        for t in raw_tools
    ]
```

- [ ] **Step 3: Update MCPFetchToolItem interface in frontend api.ts**

Find lines ~1409-1413 in `frontend/src/services/api.ts`:
```typescript
export interface MCPFetchToolItem {
  name: string;
  description: string;
}
```

Replace with:
```typescript
export interface MCPFetchToolItem {
  name: string;
  description: string;
  inputSchema?: {
    type?: string;
    properties?: Record<string, { type?: string; description?: string }>;
    required?: string[];
  };
}
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/schemas.py backend/app/api/mcp.py frontend/src/services/api.ts
git commit -m "feat: extend MCPFetchToolItem with inputSchema for mcpCall node"
```

---

## Task 2: Add mcpCall executor branch with TDD

**Files:**
- Create: `backend/tests/test_mcp_call_node.py`
- Modify: `backend/app/services/workflow_executor.py`

### Context
`execute_mcp_tool` (in `mcp_tool_executor.py`) already calls `_extract_tool_result` internally and returns the smart-unwrapped value. The node output is `{"result": <that value>}`. Import pattern: local import inside the elif block, consistent with `list_mcp_tools` at line 2645.

The executor branch goes after `elif node_type == "drive":` (line ~8514). `_resolve_mcp_connection` is already a method on `WorkflowExecutor`. `resolve_expression` is also already a method.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_mcp_call_node.py`:

```python
"""Unit tests for mcpCall node executor logic."""

import unittest
from unittest.mock import MagicMock, patch

from app.services.workflow_executor import WorkflowExecutor


def _make_executor(node_data: dict) -> WorkflowExecutor:
    """Build a minimal WorkflowExecutor with a single mcpCall node."""
    node_id = "node_mcp1"
    nodes = {
        node_id: {
            "id": node_id,
            "type": "mcpCall",
            "data": node_data,
        }
    }
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor.nodes = nodes
    executor.edges = []
    executor.db = MagicMock()
    executor.workflow_id = None
    executor.cancelled_event = MagicMock()
    executor.cancelled_event.is_set.return_value = False
    executor.hitl_resume_context = {}
    executor._sub_agent_call_depth = 0
    executor.node_outputs = {}
    return executor


CONNECTION = {
    "id": "conn1",
    "transport": "sse",
    "url": "http://localhost:3000/sse",
    "timeoutSeconds": 30,
}


class MCPCallNodeTests(unittest.TestCase):

    @patch("app.services.mcp_tool_executor.execute_mcp_tool")
    def test_basic_tool_call(self, mock_exec: MagicMock) -> None:
        """execute_mcp_tool is called with correct args and result is wrapped."""
        mock_exec.return_value = {"key": "value"}
        executor = _make_executor({
            "label": "mcpCall",
            "connection": CONNECTION,
            "selectedTool": "search",
            "toolArguments": {"query": "hello"},
            "timeoutSeconds": 30,
        })
        inputs: dict = {}
        with patch.object(executor, "_resolve_mcp_connection", return_value=CONNECTION):
            result = executor._execute_node_logic(
                "node_mcp1",
                inputs,
                executor.nodes["node_mcp1"]["data"],
                "mcpCall",
                "mcpCall",
                allow_branch_skip=False,
            )
        mock_exec.assert_called_once_with(CONNECTION, "search", {"query": "hello"}, 30.0)
        self.assertEqual(result["result"], {"key": "value"})

    @patch("app.services.mcp_tool_executor.execute_mcp_tool")
    def test_json_result_unwrapped(self, mock_exec: MagicMock) -> None:
        """When tool returns a dict (already unwrapped by execute_mcp_tool), result is that dict."""
        mock_exec.return_value = {"answer": 42}
        executor = _make_executor({
            "label": "mcpCall",
            "connection": CONNECTION,
            "selectedTool": "calculate",
            "toolArguments": {},
            "timeoutSeconds": 30,
        })
        with patch.object(executor, "_resolve_mcp_connection", return_value=CONNECTION):
            result = executor._execute_node_logic(
                "node_mcp1", {}, executor.nodes["node_mcp1"]["data"],
                "mcpCall", "mcpCall", allow_branch_skip=False,
            )
        self.assertIsInstance(result["result"], dict)
        self.assertEqual(result["result"]["answer"], 42)

    @patch("app.services.mcp_tool_executor.execute_mcp_tool")
    def test_string_result_passthrough(self, mock_exec: MagicMock) -> None:
        """When tool returns plain text, result is that string."""
        mock_exec.return_value = "plain text response"
        executor = _make_executor({
            "label": "mcpCall",
            "connection": CONNECTION,
            "selectedTool": "greet",
            "toolArguments": {},
            "timeoutSeconds": 30,
        })
        with patch.object(executor, "_resolve_mcp_connection", return_value=CONNECTION):
            result = executor._execute_node_logic(
                "node_mcp1", {}, executor.nodes["node_mcp1"]["data"],
                "mcpCall", "mcpCall", allow_branch_skip=False,
            )
        self.assertEqual(result["result"], "plain text response")

    def test_missing_tool_raises(self) -> None:
        """selectedTool='' raises ValueError before any MCP call."""
        executor = _make_executor({
            "label": "mcpCall",
            "connection": CONNECTION,
            "selectedTool": "",
            "toolArguments": {},
            "timeoutSeconds": 30,
        })
        with self.assertRaises(ValueError, msg="mcpCall node requires a tool to be selected"):
            with patch.object(executor, "_resolve_mcp_connection", return_value=CONNECTION):
                executor._execute_node_logic(
                    "node_mcp1", {}, executor.nodes["node_mcp1"]["data"],
                    "mcpCall", "mcpCall", allow_branch_skip=False,
                )

    @patch("app.services.mcp_tool_executor.execute_mcp_tool")
    def test_dsl_arguments_resolved(self, mock_exec: MagicMock) -> None:
        """DSL expression in toolArguments is resolved against inputs before tool call."""
        mock_exec.return_value = "ok"
        executor = _make_executor({
            "label": "mcpCall",
            "connection": CONNECTION,
            "selectedTool": "search",
            "toolArguments": {"query": "$userInput.body.text"},
            "timeoutSeconds": 30,
        })
        inputs = {"userInput": {"body": {"text": "hello world"}}}
        with patch.object(executor, "_resolve_mcp_connection", return_value=CONNECTION):
            executor._execute_node_logic(
                "node_mcp1", inputs, executor.nodes["node_mcp1"]["data"],
                "mcpCall", "mcpCall", allow_branch_skip=False,
            )
        _args = mock_exec.call_args[0][2]
        self.assertEqual(_args["query"], "hello world")

    @patch("app.services.mcp_tool_executor.execute_mcp_tool")
    def test_connection_dsl_resolved(self, mock_exec: MagicMock) -> None:
        """_resolve_mcp_connection is called with the raw connection dict and inputs."""
        mock_exec.return_value = None
        resolved_conn = {**CONNECTION, "url": "http://resolved.example.com/sse"}
        executor = _make_executor({
            "label": "mcpCall",
            "connection": {**CONNECTION, "url": "$vars.serverUrl"},
            "selectedTool": "ping",
            "toolArguments": {},
            "timeoutSeconds": 30,
        })
        inputs = {"vars": {"serverUrl": "http://resolved.example.com/sse"}}
        with patch.object(
            executor, "_resolve_mcp_connection", return_value=resolved_conn
        ) as mock_resolve:
            executor._execute_node_logic(
                "node_mcp1", inputs, executor.nodes["node_mcp1"]["data"],
                "mcpCall", "mcpCall", allow_branch_skip=False,
            )
        mock_resolve.assert_called_once()
        mock_exec.assert_called_once_with(resolved_conn, "ping", {}, 30.0)

    @patch("app.services.mcp_tool_executor.execute_mcp_tool")
    def test_timeout_passed(self, mock_exec: MagicMock) -> None:
        """timeoutSeconds from node_data is passed to execute_mcp_tool as float."""
        mock_exec.return_value = None
        executor = _make_executor({
            "label": "mcpCall",
            "connection": CONNECTION,
            "selectedTool": "ping",
            "toolArguments": {},
            "timeoutSeconds": 60,
        })
        with patch.object(executor, "_resolve_mcp_connection", return_value=CONNECTION):
            executor._execute_node_logic(
                "node_mcp1", {}, executor.nodes["node_mcp1"]["data"],
                "mcpCall", "mcpCall", allow_branch_skip=False,
            )
        _timeout = mock_exec.call_args[0][3]
        self.assertEqual(_timeout, 60.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym/backend
uv run pytest tests/test_mcp_call_node.py -v 2>&1 | head -40
```

Expected: All 7 tests fail with `AttributeError` or `AssertionError` since `mcpCall` branch doesn't exist yet.

- [ ] **Step 3: Add the mcpCall elif branch in workflow_executor.py**

Find `elif node_type == "drive":` (line ~8514). Directly after the entire `drive` block (search for the closing pattern — look for the next `elif node_type` or end of the giant if-elif chain). Add the new branch **before** the closing `else:` clause of `_execute_node_logic`. The branch goes after the drive block.

Add this block:
```python
            elif node_type == "mcpCall":
                from app.services.mcp_tool_executor import execute_mcp_tool

                mcp_connection = node_data.get("connection") or {}
                selected_tool = node_data.get("selectedTool") or ""
                tool_arguments = node_data.get("toolArguments") or {}
                timeout = float(node_data.get("timeoutSeconds") or 30)

                if not selected_tool:
                    raise ValueError("mcpCall node requires a tool to be selected")

                mcp_connection = self._resolve_mcp_connection(mcp_connection, inputs, node_id)

                resolved_args = {
                    k: self.resolve_expression(str(v), inputs)
                    for k, v in tool_arguments.items()
                }

                mcp_result = execute_mcp_tool(mcp_connection, selected_tool, resolved_args, timeout)
                output = {"result": mcp_result}
```

> **Note on patch path:** The test patches `app.services.mcp_tool_executor.execute_mcp_tool`. The local import `from app.services.mcp_tool_executor import execute_mcp_tool` inside the elif means the mock must patch the function at its source module, which is `app.services.mcp_tool_executor.execute_mcp_tool`. This is correct.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym/backend
uv run pytest tests/test_mcp_call_node.py -v
```

Expected output:
```
PASSED tests/test_mcp_call_node.py::MCPCallNodeTests::test_basic_tool_call
PASSED tests/test_mcp_call_node.py::MCPCallNodeTests::test_connection_dsl_resolved
PASSED tests/test_mcp_call_node.py::MCPCallNodeTests::test_dsl_arguments_resolved
PASSED tests/test_mcp_call_node.py::MCPCallNodeTests::test_json_result_unwrapped
PASSED tests/test_mcp_call_node.py::MCPCallNodeTests::test_missing_tool_raises
PASSED tests/test_mcp_call_node.py::MCPCallNodeTests::test_string_result_passthrough
PASSED tests/test_mcp_call_node.py::MCPCallNodeTests::test_timeout_passed
7 passed
```

- [ ] **Step 5: Run full backend check**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym
uv run ruff format backend/ && uv run ruff check backend/
```

Fix any lint errors before committing.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_mcp_call_node.py backend/app/services/workflow_executor.py
git commit -m "feat: add mcpCall node executor branch with unit tests"
```

---

## Task 3: Frontend types — add mcpCall to NodeType and NODE_DEFINITIONS

**Files:**
- Modify: `frontend/src/types/workflow.ts` (line ~161, end of NodeType union)
- Modify: `frontend/src/types/node.ts` (after the last node entry)

- [ ] **Step 1: Add "mcpCall" to NodeType union in workflow.ts**

Find the NodeType union at line 123. It ends with `| "slackTrigger";`. Change to:
```typescript
  | "slackTrigger"
  | "mcpCall";
```

- [ ] **Step 2: Add mcpCall entry to NODE_DEFINITIONS in node.ts**

Find the last entry in `NODE_DEFINITIONS` (currently `slackTrigger` or `drive`). After it, before the closing `}` of the Record, add:

```typescript
  mcpCall: {
    type: "mcpCall",
    label: "MCP Call",
    description: "Call a specific MCP tool directly — no LLM required",
    color: "node-agent",
    icon: "Plug",
    inputs: 1,
    outputs: 1,
    defaultData: {
      label: "mcpCall",
      connection: {
        id: "",
        transport: "sse" as const,
        label: "",
        timeoutSeconds: 30,
        url: "",
        headers: {},
      },
      selectedTool: "",
      toolArguments: {},
      timeoutSeconds: 30,
    },
  },
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym/frontend
bun run typecheck 2>&1 | head -30
```

Expected: No new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/types/node.ts
git commit -m "feat: add mcpCall to NodeType union and NODE_DEFINITIONS"
```

---

## Task 4: Block mcpCall as agent tool in WorkflowCanvas

**Files:**
- Modify: `frontend/src/components/Canvas/WorkflowCanvas.vue` (line ~74)

- [ ] **Step 1: Add "mcpCall" to BLOCKED_AS_TOOL**

Find the set at line 74:
```typescript
const BLOCKED_AS_TOOL = new Set<string>([
  "merge", "switch", "loop", "agent", "llm", "condition",
  "execute", "sticky", "errorHandler",
  "cron", "textInput", "telegramTrigger", "websocketTrigger", "slackTrigger", "imapTrigger",
]);
```

Change to:
```typescript
const BLOCKED_AS_TOOL = new Set<string>([
  "merge", "switch", "loop", "agent", "llm", "condition",
  "execute", "sticky", "errorHandler",
  "cron", "textInput", "telegramTrigger", "websocketTrigger", "slackTrigger", "imapTrigger",
  "mcpCall",
]);
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym/frontend
bun run typecheck 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Canvas/WorkflowCanvas.vue
git commit -m "feat: block mcpCall from being used as agent tool"
```

---

## Task 5: PropertiesPanel — add mcpCall section

**Files:**
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue`

This is the largest change. It adds new script functions and a new template section.

### Part A — Script additions

- [ ] **Step 1: Add mcpCall connection helper functions**

Find the `fetchMCPTools` function (line ~4384). After the closing `}` of `fetchMCPTools`, add:

```typescript
// ─── mcpCall node helpers ───────────────────────────────────────────────────

interface MCPCallFetchState {
  loading: boolean;
  error: string | null;
  tools: MCPFetchToolItem[];
}

const mcpCallFetchState = ref<MCPCallFetchState>({ loading: false, error: null, tools: [] });

function updateMCPCallConnectionField(
  field: keyof AgentMCPConnection,
  value: unknown,
): void {
  if (!selectedNode.value) return;
  const current = { ...(selectedNode.value.data.connection ?? {}) };
  (current as Record<string, unknown>)[field] = value;
  updateNodeData("connection", current);
}

async function fetchMCPCallTools(): Promise<void> {
  if (!selectedNode.value) return;
  const conn = selectedNode.value.data.connection as AgentMCPConnection;
  mcpCallFetchState.value = { loading: true, error: null, tools: [] };
  const connection = {
    id: conn.id || "mcpCall",
    transport: conn.transport,
    label: conn.label,
    timeoutSeconds: conn.timeoutSeconds ?? 30,
    command: conn.command,
    args: conn.args,
    env: conn.env,
    url: conn.url,
    headers: conn.headers,
  };
  try {
    const res = await mcpApi.fetchTools(connection);
    mcpCallFetchState.value = { loading: false, error: null, tools: res.tools };
  } catch (e: unknown) {
    const msg =
      e && typeof e === "object" && "response" in e
        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : String(e);
    mcpCallFetchState.value = { loading: false, error: msg || "Failed to connect", tools: [] };
  }
}

function selectMCPCallTool(toolName: string): void {
  if (!selectedNode.value) return;
  updateNodeData("selectedTool", toolName);
  const tool = mcpCallFetchState.value.tools.find((t) => t.name === toolName);
  const props = tool?.inputSchema?.properties ?? {};
  const freshArgs: Record<string, string> = {};
  for (const key of Object.keys(props)) {
    freshArgs[key] = (selectedNode.value.data.toolArguments?.[key] as string) ?? "";
  }
  updateNodeData("toolArguments", freshArgs);
}

function updateMCPCallArgument(key: string, value: string): void {
  if (!selectedNode.value) return;
  const current = { ...(selectedNode.value.data.toolArguments ?? {}) };
  current[key] = value;
  updateNodeData("toolArguments", current);
}

const mcpCallSelectedTool = computed(() => {
  if (!selectedNode.value) return null;
  const name = selectedNode.value.data.selectedTool as string | undefined;
  if (!name) return null;
  return mcpCallFetchState.value.tools.find((t) => t.name === name) ?? null;
});
```

> **Import note:** `MCPFetchToolItem` is already imported from `api.ts` if the agent node section uses it. If not already imported, add `MCPFetchToolItem` to the import from `@/services/api`.

- [ ] **Step 2: Add mcpCall template section**

Find the `<template v-if="selectedNode.type === 'playwright'">` block (line ~10232). After its closing `</template>` tag and before the Error Handling `<div v-if="!['textInput'...">` block (line ~10921), add:

```vue
          <template v-if="selectedNode.type === 'mcpCall'">
            <div class="space-y-4">
              <!-- Connection -->
              <div class="space-y-2">
                <Label class="text-muted-foreground flex items-center gap-1">
                  <Plug class="w-3.5 h-3.5" />
                  MCP Connection
                </Label>
                <div class="rounded border p-3 space-y-2">
                  <div class="flex gap-2">
                    <div class="flex-1">
                      <Label class="text-xs">Transport</Label>
                      <Select
                        :model-value="selectedNode.data.connection?.transport ?? 'sse'"
                        :options="[
                          { value: 'stdio', label: 'stdio' },
                          { value: 'sse', label: 'SSE' },
                          { value: 'streamable_http', label: 'Streamable HTTP' },
                        ]"
                        @update:model-value="updateMCPCallConnectionField('transport', $event)"
                      />
                    </div>
                    <div class="w-24">
                      <Label class="text-xs">Timeout (s)</Label>
                      <Input
                        type="number"
                        :model-value="String(selectedNode.data.connection?.timeoutSeconds ?? 30)"
                        min="1"
                        max="300"
                        placeholder="30"
                        @update:model-value="updateMCPCallConnectionField('timeoutSeconds', parseInt($event, 10) || 30)"
                      />
                    </div>
                  </div>
                  <div>
                    <Label class="text-xs">Label (optional)</Label>
                    <Input
                      :model-value="selectedNode.data.connection?.label ?? ''"
                      placeholder="my-mcp-server"
                      @update:model-value="updateMCPCallConnectionField('label', $event)"
                    />
                  </div>
                  <template v-if="selectedNode.data.connection?.transport === 'stdio'">
                    <div>
                      <Label class="text-xs">Command</Label>
                      <Input
                        :model-value="selectedNode.data.connection?.command ?? ''"
                        placeholder="npx"
                        @update:model-value="updateMCPCallConnectionField('command', $event)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">Args (JSON array)</Label>
                      <Textarea
                        :model-value="typeof selectedNode.data.connection?.args === 'string' ? selectedNode.data.connection.args : JSON.stringify(selectedNode.data.connection?.args ?? [], null, 2)"
                        placeholder="[&quot;-y&quot;, &quot;@modelcontextprotocol/server-filesystem&quot;]"
                        :rows="2"
                        wrap="off"
                        class="overflow-x-auto whitespace-pre font-mono text-xs"
                        @update:model-value="updateMCPCallConnectionField('args', $event)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">Env (JSON object)</Label>
                      <Textarea
                        :model-value="typeof selectedNode.data.connection?.env === 'string' ? selectedNode.data.connection.env : JSON.stringify(selectedNode.data.connection?.env ?? {}, null, 2)"
                        placeholder="{&quot;API_KEY&quot;: &quot;your_key&quot;}"
                        :rows="2"
                        wrap="off"
                        class="overflow-x-auto whitespace-pre font-mono text-xs"
                        @update:model-value="updateMCPCallConnectionField('env', $event)"
                      />
                    </div>
                  </template>
                  <template v-else-if="selectedNode.data.connection?.transport === 'sse' || selectedNode.data.connection?.transport === 'streamable_http'">
                    <div>
                      <Label class="text-xs">URL</Label>
                      <Input
                        :model-value="selectedNode.data.connection?.url ?? ''"
                        :placeholder="selectedNode.data.connection?.transport === 'streamable_http' ? 'https://example.com/mcp' : 'https://example.com/mcp/sse'"
                        @update:model-value="updateMCPCallConnectionField('url', $event)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">Headers (JSON object)</Label>
                      <Textarea
                        :model-value="typeof selectedNode.data.connection?.headers === 'string' ? selectedNode.data.connection.headers : JSON.stringify(selectedNode.data.connection?.headers ?? {}, null, 2)"
                        placeholder="{&quot;Authorization&quot;: &quot;Bearer ...&quot;}"
                        :rows="2"
                        wrap="off"
                        class="overflow-x-auto whitespace-pre font-mono text-xs"
                        @update:model-value="updateMCPCallConnectionField('headers', $event)"
                      />
                    </div>
                  </template>

                  <!-- Fetch tools button -->
                  <div class="pt-2 flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      class="gap-1"
                      :disabled="
                        (selectedNode.data.connection?.transport === 'stdio' && !selectedNode.data.connection?.command) ||
                        ((selectedNode.data.connection?.transport === 'sse' || selectedNode.data.connection?.transport === 'streamable_http') && !selectedNode.data.connection?.url) ||
                        mcpCallFetchState.loading
                      "
                      @click="fetchMCPCallTools"
                    >
                      <Loader2
                        v-if="mcpCallFetchState.loading"
                        class="w-3.5 h-3.5 animate-spin"
                      />
                      <Server
                        v-else
                        class="w-3.5 h-3.5"
                      />
                      {{ mcpCallFetchState.loading ? "Connecting…" : "Fetch tools" }}
                    </Button>
                    <span
                      v-if="mcpCallFetchState.error"
                      class="text-xs text-destructive truncate min-w-0 flex-1"
                      :title="mcpCallFetchState.error"
                    >
                      {{ mcpCallFetchState.error }}
                    </span>
                    <span
                      v-else-if="mcpCallFetchState.tools.length > 0"
                      class="text-xs text-muted-foreground"
                    >
                      {{ mcpCallFetchState.tools.length }} tool(s) found
                    </span>
                  </div>
                </div>
              </div>

              <!-- Tool selection (required) -->
              <div class="space-y-2">
                <Label class="text-xs flex items-center gap-1">
                  Tool
                  <span class="text-destructive">*</span>
                </Label>
                <Select
                  :model-value="selectedNode.data.selectedTool ?? ''"
                  :options="[
                    { value: '', label: mcpCallFetchState.tools.length ? 'Select a tool…' : 'Fetch tools first' },
                    ...mcpCallFetchState.tools.map(t => ({ value: t.name, label: t.name }))
                  ]"
                  :class="!selectedNode.data.selectedTool ? 'border-destructive' : ''"
                  @update:model-value="selectMCPCallTool($event)"
                />
                <p
                  v-if="!selectedNode.data.selectedTool"
                  class="text-xs text-destructive"
                >
                  A tool must be selected — this node will not run without one.
                </p>
                <p
                  v-else-if="mcpCallSelectedTool?.description"
                  class="text-xs text-muted-foreground"
                >
                  {{ mcpCallSelectedTool.description }}
                </p>
              </div>

              <!-- Tool arguments -->
              <div
                v-if="mcpCallSelectedTool"
                class="space-y-2"
              >
                <Label class="text-xs text-muted-foreground">Arguments</Label>
                <div
                  v-if="Object.keys(mcpCallSelectedTool.inputSchema?.properties ?? {}).length === 0"
                  class="text-xs text-muted-foreground italic"
                >
                  This tool takes no arguments.
                </div>
                <div
                  v-for="(propDef, propKey) in (mcpCallSelectedTool.inputSchema?.properties ?? {})"
                  :key="propKey"
                  class="space-y-1"
                >
                  <Label class="text-xs flex items-center gap-1">
                    {{ propKey }}
                    <span
                      v-if="mcpCallSelectedTool.inputSchema?.required?.includes(String(propKey))"
                      class="text-destructive"
                    >*</span>
                    <span
                      v-if="propDef.description"
                      class="text-muted-foreground font-normal"
                    >— {{ propDef.description }}</span>
                  </Label>
                  <Input
                    :model-value="String(selectedNode.data.toolArguments?.[propKey] ?? '')"
                    placeholder="value or $expr"
                    class="font-mono text-xs"
                    @update:model-value="updateMCPCallArgument(String(propKey), $event)"
                  />
                </div>
                <p class="text-xs text-muted-foreground">
                  Values support DSL expressions: <code class="bg-muted px-1 rounded">$nodeLabel.field</code>
                </p>
              </div>

              <!-- Output reference -->
              <div class="space-y-1 pt-2 border-t">
                <Label class="text-xs text-muted-foreground">Output</Label>
                <div class="text-xs font-mono space-y-0.5">
                  <div>${{ selectedNode.data.label }}.result — tool result (object or string)</div>
                </div>
              </div>
            </div>
          </template>
```

- [ ] **Step 3: Ensure Plug icon is imported**

Check the icon imports at the top of the script section. The file uses Lucide icons via a pattern like:
```typescript
import { Bot, Plug, Server, Loader2, ... } from "lucide-vue-next";
```

If `Plug` is not already imported, add it to the Lucide import. If the file uses a different import pattern, follow that pattern.

- [ ] **Step 4: Run TypeScript check**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym/frontend
bun run typecheck 2>&1 | head -40
```

Fix any type errors before continuing.

- [ ] **Step 5: Run lint**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym/frontend
bun run lint 2>&1 | head -30
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Panels/PropertiesPanel.vue
git commit -m "feat: add mcpCall PropertiesPanel section with connection config, tool fetch, and argument fields"
```

---

## Task 6: Update workflow_dsl_prompt.py

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py`

The mcpCall section goes between the `drive` section (ends ~line 2910) and `## Expression Syntax` (line ~2911). Add it as `### 30. mcpCall`.

- [ ] **Step 1: Insert mcpCall node type section**

Find the string `## Expression Syntax` in `workflow_dsl_prompt.py`. Directly before that line, insert:

```
### 30. mcpCall (Direct MCP Tool Call)
- **Purpose**: Call a specific MCP tool directly without an LLM deciding which tool to use
- **Inputs**: 1 | **Outputs**: 1
- **WHEN TO USE**: When you know exactly which MCP tool to call. Deterministic — no LLM loop.
- **DO NOT connect** mcpCall nodes to agent `tool-input` handles.
- **Tool selection is REQUIRED** — `selectedTool` must be non-empty or the node will error.
- **Data fields**:
  - `label`: Node identifier (camelCase)
  - `connection`: MCP connection config object:
    - `transport`: `"sse"` | `"streamable_http"` | `"stdio"`
    - `url`: Server URL (sse/streamable_http only); supports DSL expressions
    - `command`: Executable (stdio only)
    - `args`: JSON array string or array (stdio only)
    - `env`: JSON object string or object of env vars (stdio only)
    - `headers`: JSON object string or object (sse/streamable_http only); supports DSL expressions
    - `timeoutSeconds`: Timeout in seconds (default: 30)
  - `selectedTool`: Name of the MCP tool to call (required, non-empty)
  - `toolArguments`: Object of key→value pairs; values support DSL expressions
  - `timeoutSeconds`: Node-level timeout (default: 30)
- **Output**: `$label.result` — smart-unwrapped tool result (JSON object if parseable, otherwise string)

**Example (SSE transport, search tool):**
```json
{
  "type": "mcpCall",
  "data": {
    "label": "searchCall",
    "connection": {
      "transport": "sse",
      "url": "https://mcp.example.com/sse",
      "timeoutSeconds": 30
    },
    "selectedTool": "search",
    "toolArguments": {
      "query": "$userInput.body.text",
      "limit": "10"
    },
    "timeoutSeconds": 30
  }
}
```

**Example (stdio transport, filesystem tool):**
```json
{
  "type": "mcpCall",
  "data": {
    "label": "readFile",
    "connection": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "--path", "/tmp"],
      "timeoutSeconds": 30
    },
    "selectedTool": "read_file",
    "toolArguments": {
      "path": "$userInput.body.filePath"
    },
    "timeoutSeconds": 30
  }
}
```

**Downstream access:**
- `$searchCall.result` → tool result (object or string)

```

- [ ] **Step 2: Run backend check**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym/backend
uv run ruff check app/services/workflow_dsl_prompt.py
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py
git commit -m "docs: add mcpCall node type section to workflow DSL prompt"
```

---

## Task 7: Landing page — add mcpCall to NodesSection

**Files:**
- Modify: `heymweb/src/components/sections/NodesSection.tsx` (in the `nodes` array, around line 115)

- [ ] **Step 1: Add mcpCall entry to nodes array**

Find the `nodes: MarketingNode[]` array in `NodesSection.tsx`. Add the following entry. Place it near the `agent` entry (around line 188) since it's in the AI/integration category:

```typescript
    {
      id: 'mcpCall',
      name: 'MCP Call',
      categories: ['ai', 'integration'],
      icon: Plug,
      description: 'Call a specific MCP tool directly — no LLM required. Configure SSE, streamable HTTP, or stdio transport; arguments resolved from workflow expressions.',
    },
```

- [ ] **Step 2: Ensure Plug icon is imported**

At the top of `NodesSection.tsx`, find the lucide-react import. Add `Plug` if not already there:
```typescript
import { ..., Plug } from "lucide-react";
```

- [ ] **Step 3: Ensure 'integration' category exists in nodeCategories**

Check the `nodeCategories` array (~line 71). If an `integration` category entry doesn't exist, either use an existing category that fits (e.g., `'ai'` alone) or add:
```typescript
  { id: 'integration', label: 'Integration', color: 'border-blue-500' },
```
Use whatever color fits the existing palette. If 'integration' already exists, no change needed.

- [ ] **Step 4: Run TypeScript check in heymweb**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heymweb
bun run tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 5: Commit**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heymweb
git add src/components/sections/NodesSection.tsx
git commit -m "feat: add MCP Call node to landing page nodes section"
```

---

## Task 8: Node documentation via heym-documentation skill

**Files:**
- Create: `frontend/src/docs/content/nodes/mcp-call-node.md`

- [ ] **Step 1: Invoke heym-documentation skill**

Run the `heym-documentation` skill to create the node documentation for `mcpCall`. The skill will guide creation of `frontend/src/docs/content/nodes/mcp-call-node.md` covering:
- What the node does
- Connection configuration (SSE/streamable_http/stdio fields)
- How tool selection works (Fetch Tools button → dropdown)
- Argument fields and DSL expression support
- Output reference (`$label.result`)
- Example workflow snippet

- [ ] **Step 2: Commit the documentation**

```bash
git add frontend/src/docs/content/nodes/mcp-call-node.md
git commit -m "docs: add mcp-call-node documentation"
```

---

## Task 9: Final verification

- [ ] **Step 1: Run full check.sh**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym
./check.sh
```

Expected: All linting, type checks, and backend tests pass.

- [ ] **Step 2: Manual smoke test**

1. Start services: `./run.sh`
2. Open editor, drag an `MCP Call` node onto the canvas
3. In PropertiesPanel: configure an SSE connection, click "Fetch Tools"
4. Select a tool from the dropdown — verify argument fields appear
5. Try to draw an edge from mcpCall to an agent's tool-input — verify it's rejected with toast
6. Run a workflow containing the mcpCall node — verify `$mcpCall.result` is accessible downstream

- [ ] **Step 3: Final commit if any fixups**

```bash
git add -p  # stage only intentional changes
git commit -m "fix: mcpCall node post-review fixups"
```

---

## Self-Review Notes

- **Spec coverage:** All 8 spec sections covered: connection config ✓, tool selection ✓, arg fields from schema ✓, smart output ✓, BLOCKED_AS_TOOL ✓, frontend validation ✓, backend tests (7 tests) ✓, DSL prompt ✓, landing page ✓, heym-documentation ✓
- **Type consistency:** `AgentMCPConnection` used throughout — same interface as agent node. `MCPFetchToolItem` extended consistently in both backend schema and frontend interface.
- **Patch path in tests:** `app.services.mcp_tool_executor.execute_mcp_tool` — correct for local import inside elif.
- **`resolve_expression` signature:** Called as `self.resolve_expression(str(v), inputs)` — coerce value to string since `toolArguments` values are typed as `string` in the data model.
- **`_execute_node_logic` signature:** Check the actual method signature in `workflow_executor.py` before writing tests — adapt `_make_executor` helper and test calls to match what the executor actually expects. The mock pattern patches `execute_mcp_tool` at source, which is correct for a local import.
