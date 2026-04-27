# Edit History Version Preview — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Preview button next to Revert in the Edit History dialog; clicking it opens a read-only, pannable/zoomable canvas showing the selected version's nodes and edges.

**Architecture:** A new `WorkflowVersionPreviewDialog.vue` component holds a read-only VueFlow canvas fed directly from `version.nodes` and `version.edges` (no extra API call). `WorkflowEditHistoryDialog.vue` gets a Preview button (Eye icon) and refs to drive the new dialog. Backend tests gain two edge-case coverage tests.

**Tech Stack:** Vue 3 `<script setup>` + TypeScript strict, `@vue-flow/core`, `@vue-flow/background`, `@vue-flow/controls`, `@vue-flow/minimap`, Lucide Vue Next, Python 3.11 + pytest/unittest.

---

## File Map

| Action | Path |
|--------|------|
| **Create** | `frontend/src/components/Dialogs/WorkflowVersionPreviewDialog.vue` |
| **Modify** | `frontend/src/components/Dialogs/WorkflowEditHistoryDialog.vue` |
| **Modify** | `frontend/src/docs/content/reference/edit-history.md` |
| **Modify** | `backend/tests/test_workflow_version.py` |

---

## Task 1: Backend edge-case tests

**Files:**
- Modify: `backend/tests/test_workflow_version.py`

- [ ] **Step 1: Add two new test cases to `CalculateWorkflowDiffTests`**

Open `backend/tests/test_workflow_version.py`. After the existing `test_full_diff_aggregates_all_change_types` test (currently the last test, around line 153), append:

```python
    def test_nodes_only_no_edges(self) -> None:
        """Version with nodes but empty edges produces only node changes."""
        old_node = {"id": "n1", "type": "llm", "data": {"label": "A"}}
        new_node = {"id": "n1", "type": "llm", "data": {"label": "B"}}
        result = calculate_workflow_diff(
            old_nodes=[old_node],
            old_edges=[],
            old_config={},
            new_nodes=[new_node],
            new_edges=[],
            new_config={},
            version_id=_V2,
            version_number=2,
            compared_to_version_id=_V1,
            compared_to_version_number=1,
        )
        self.assertEqual(len(result.node_changes), 1)
        self.assertEqual(result.edge_changes, [])
        self.assertEqual(result.config_changes, [])

    def test_edges_only_no_nodes(self) -> None:
        """Version with edges but empty nodes produces only edge changes."""
        old_edge = {"id": "e1", "source": "a", "target": "b"}
        new_edge = {"id": "e1", "source": "a", "target": "c"}
        result = calculate_workflow_diff(
            old_nodes=[],
            old_edges=[old_edge],
            old_config={},
            new_nodes=[],
            new_edges=[new_edge],
            new_config={},
            version_id=_V2,
            version_number=2,
            compared_to_version_id=_V1,
            compared_to_version_number=1,
        )
        self.assertEqual(result.node_changes, [])
        self.assertGreater(len(result.edge_changes), 0)
        self.assertEqual(result.config_changes, [])
```

- [ ] **Step 2: Run the new tests**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend
uv run pytest tests/test_workflow_version.py -v
```

Expected: All tests pass (green). The two new tests should show `PASSED`.

- [ ] **Step 3: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
git add backend/tests/test_workflow_version.py
git commit -m "test: add edge-case coverage for nodes/edges-only workflow diffs"
```

---

## Task 2: Create `WorkflowVersionPreviewDialog.vue`

**Files:**
- Create: `frontend/src/components/Dialogs/WorkflowVersionPreviewDialog.vue`

This component receives a `WorkflowVersion` and renders its nodes/edges in a read-only VueFlow canvas inside a `Dialog` of size `4xl`.

Important VueFlow mapping rules (same as `WorkflowCanvas.vue`):
- VueFlow node: `{ id, type: "custom", position, data: { ...node.data, nodeType: node.type } }`
- VueFlow edge: `{ id, type: "insertable", source, target, sourceHandle, targetHandle, animated: true }`
- Custom node component registered as `"custom"` → `BaseNode`
- Custom edge component registered as `"insertable"` → `InsertableEdge`

- [ ] **Step 1: Create the file**

Create `frontend/src/components/Dialogs/WorkflowVersionPreviewDialog.vue` with the following content:

```vue
<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import { VueFlow, useVueFlow } from "@vue-flow/core";
import { MiniMap } from "@vue-flow/minimap";

import BaseNode from "@/components/Nodes/BaseNode.vue";
import InsertableEdge from "@/components/Canvas/InsertableEdge.vue";
import Dialog from "@/components/ui/Dialog.vue";
import type { WorkflowVersion } from "@/types/workflow";

import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";
import "@vue-flow/controls/dist/style.css";
import "@vue-flow/minimap/dist/style.css";

interface Props {
  open: boolean;
  version: WorkflowVersion | null;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "close"): void;
}>();

const flowKey = ref(0);
const { fitView } = useVueFlow({ id: computed(() => `preview-${flowKey.value}`).value });

const vueFlowNodes = computed(() => {
  if (!props.version) return [];
  return props.version.nodes.map((node) => ({
    id: node.id,
    type: "custom" as const,
    position: node.position,
    data: { ...node.data, nodeType: node.type },
  }));
});

const vueFlowEdges = computed(() => {
  if (!props.version) return [];
  return props.version.edges.map((edge) => ({
    id: edge.id,
    type: "insertable" as const,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle,
    targetHandle: edge.targetHandle,
    animated: true,
  }));
});

watch(
  () => props.open,
  (open) => {
    if (open) {
      flowKey.value += 1;
      nextTick(() => {
        fitView({ padding: 0.2 });
      });
    }
  },
);

const nodeTypes = { custom: BaseNode };
const edgeTypes = { insertable: InsertableEdge };
</script>

<template>
  <Dialog
    :open="open"
    :title="version ? `Version ${version.version_number} Preview` : 'Preview'"
    size="4xl"
    @close="emit('close')"
  >
    <div class="h-[65vh] w-full rounded-lg overflow-hidden border border-border/40">
      <VueFlow
        :key="flowKey"
        :nodes="vueFlowNodes"
        :edges="vueFlowEdges"
        :node-types="nodeTypes"
        :edge-types="edgeTypes"
        :nodes-draggable="false"
        :nodes-connectable="false"
        :elements-selectable="false"
        :pan-on-drag="true"
        :zoom-on-scroll="true"
        fit-view-on-init
        class="w-full h-full"
      >
        <Background />
        <Controls :show-interactive="false" />
        <MiniMap />
      </VueFlow>
    </div>
  </Dialog>
</template>
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend
bun run typecheck
```

Expected: No errors. If `useVueFlow` id binding causes a type issue, change the `useVueFlow` call to just `const { fitView } = useVueFlow();` (the id is optional).

- [ ] **Step 3: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
git add frontend/src/components/Dialogs/WorkflowVersionPreviewDialog.vue
git commit -m "feat: add WorkflowVersionPreviewDialog with read-only VueFlow canvas"
```

---

## Task 3: Wire Preview button into `WorkflowEditHistoryDialog.vue`

**Files:**
- Modify: `frontend/src/components/Dialogs/WorkflowEditHistoryDialog.vue`

Three changes:
1. Import `Eye` icon and the new dialog component
2. Add `previewOpen` / `previewVersion` refs and `openPreview` helper
3. Add Preview button left of Revert; add dialog to template

- [ ] **Step 1: Add imports**

In `WorkflowEditHistoryDialog.vue`, find the existing import block (lines 2–16):

```typescript
import {
  Clock,
  GitBranch,
  Loader2,
  RotateCcw,
  ChevronDown,
  ChevronRight,
  Plus,
  Minus,
  Edit,
  AlertCircle,
  Trash2,
  RefreshCw,
} from "lucide-vue-next";
```

Replace with (adds `Eye`):

```typescript
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  Edit,
  Eye,
  GitBranch,
  Loader2,
  Minus,
  Plus,
  RefreshCw,
  RotateCcw,
  Trash2,
} from "lucide-vue-next";
```

Then, below the line `import { useWorkflowStore } from "@/stores/workflow";`, add:

```typescript
import WorkflowVersionPreviewDialog from "@/components/Dialogs/WorkflowVersionPreviewDialog.vue";
```

- [ ] **Step 2: Add state and helper**

In the `<script setup>` section, after the line `const clearing = ref(false);` (around line 50), add:

```typescript
const previewOpen = ref(false);
const previewVersion = ref<WorkflowVersion | null>(null);

function openPreview(version: WorkflowVersion): void {
  previewVersion.value = version;
  previewOpen.value = true;
}
```

- [ ] **Step 3: Add Preview button in template**

In the template, find the Changes panel header block — specifically the `<div class="flex items-center justify-between">` that contains the "Changes" heading and Revert button (around line 489–505):

```html
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold">
              Changes
            </h3>
            <Button
              v-if="selectedVersion && !isCurrentVersion"
              variant="outline"
              size="sm"
              class="gap-2"
              :loading="reverting"
              :disabled="reverting"
              @click="revertToVersion"
            >
              <RotateCcw class="w-4 h-4" />
              Revert
            </Button>
          </div>
```

Replace with:

```html
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold">
              Changes
            </h3>
            <div
              v-if="selectedVersion && !isCurrentVersion"
              class="flex items-center gap-2"
            >
              <Button
                variant="outline"
                size="sm"
                class="gap-2"
                @click="openPreview(selectedVersion!)"
              >
                <Eye class="w-4 h-4" />
                Preview
              </Button>
              <Button
                variant="outline"
                size="sm"
                class="gap-2"
                :loading="reverting"
                :disabled="reverting"
                @click="revertToVersion"
              >
                <RotateCcw class="w-4 h-4" />
                Revert
              </Button>
            </div>
          </div>
```

- [ ] **Step 4: Add preview dialog to template**

At the very end of the `<template>` block, just before `</template>`, add:

```html
  <WorkflowVersionPreviewDialog
    :open="previewOpen"
    :version="previewVersion"
    @close="previewOpen = false"
  />
```

- [ ] **Step 5: Run lint and typecheck**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/frontend
bun run lint && bun run typecheck
```

Expected: No errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
git add frontend/src/components/Dialogs/WorkflowEditHistoryDialog.vue
git commit -m "feat: add Preview button to edit history dialog"
```

---

## Task 4: Update documentation

**Files:**
- Modify: `frontend/src/docs/content/reference/edit-history.md`

- [ ] **Step 1: Insert Preview section**

In `frontend/src/docs/content/reference/edit-history.md`, find this block (currently between "Diff View" and "Revert"):

```markdown
## Revert
```

Insert the following **before** the `## Revert` heading:

```markdown
## Preview

To see what the workflow looked like at a past version, click **Preview** next to Revert.

A read-only canvas opens showing the nodes and edges of that version. You can pan and zoom to explore the layout; no changes can be made from this view.
```

- [ ] **Step 2: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
git add frontend/src/docs/content/reference/edit-history.md
git commit -m "docs: add Preview section to edit-history reference"
```

---

## Task 5: Full check

- [ ] **Step 1: Run backend tests**

```bash
cd /Users/mbakgun/Projects/heym/heymrun/backend
uv run pytest tests/test_workflow_version.py -v
```

Expected: All tests PASSED.

- [ ] **Step 2: Run full check script**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
./check.sh
```

Expected: Ruff format/lint pass, all backend tests pass, frontend lint/typecheck pass.

- [ ] **Step 3: Manual smoke test**

1. Start dev server: `cd frontend && bun run dev`
2. Open the editor, open Edit History dialog
3. Select any non-current version → "Preview" button appears next to "Revert"
4. Click Preview → dialog opens at `4xl` size
5. Canvas renders the version's nodes/edges; pan and zoom work; no editing possible
6. Close dialog → returns to Edit History dialog

---

## Self-Review

**Spec coverage:**
- ✅ Preview button next to Revert — Task 3
- ✅ Opens as dialog, same size (4xl) — Task 2
- ✅ Pan/zoom enabled, read-only — Task 2 (VueFlow props)
- ✅ No API call needed — Task 2 (uses `version.nodes`/`version.edges` directly)
- ✅ Backend unit tests updated — Task 1
- ✅ Documentation updated — Task 4

**Placeholder scan:** No TBDs or TODOs.

**Type consistency:**
- `WorkflowVersion` type imported everywhere from `@/types/workflow`
- `openPreview(version: WorkflowVersion)` called with `selectedVersion!` (non-null asserted; safe because button only shown when `selectedVersion && !isCurrentVersion`)
- `previewVersion` typed as `WorkflowVersion | null`, prop in dialog typed the same way
