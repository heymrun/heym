# ExpressionInput Parametric Evaluation & Node Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add parameter chips and node navigation to ExpressionInput.vue for efficient multi-parameter evaluation

**Architecture:** Extend ExpressionInput.vue with new props, computed variables for navigation/parameters, and header UI; parent components pass node/param data

**Tech Stack:** Vue 3 Composition API, TypeScript, Tailwind CSS, Lucide icons

---

## Task 1: Add New Props to ExpressionInput Interface

**Files:**
- Modify: `frontend/src/components/ui/ExpressionInput.vue:44-84` (Props interface)

- [ ] **Step 1: Add ParamInfo interface and extend Props**

Add before the Props interface:

```typescript
interface ParamInfo {
  key: string;
  label: string;
  value: string;
}
```

Extend the Props interface by adding at the end of the `withDefaults(defineProps<Props>(), { ... })` definition:

```typescript
navigationEnabled?: boolean;
navigationIndex?: number;
navigationTotal?: number;
availableParams?: ParamInfo[];
activeParamIndex?: number;
```

Update the defaults section to include:

```typescript
navigationEnabled: false,
navigationIndex: 0,
navigationTotal: 0,
availableParams: () => [],
activeParamIndex: 0,
```

- [ ] **Step 2: Verify type checking**

Run: `cd frontend && bun run typecheck`
Expected: No type errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/ExpressionInput.vue
git commit -m "feat: add navigation and param props to ExpressionInput"
```

---

## Task 2: Add Node Navigation Imports

**Files:**
- Modify: `frontend/src/components/ui/ExpressionInput.vue:1-43` (script setup imports and imports)

- [ ] **Step 1: Add ChevronLeft and ChevronRight to existing icon imports**

Modify the icon import block (around line 12-25) to include:

```typescript
import {
  AlertCircle,
  Braces,
  ChevronLeft,
  ChevronRight,
  Code2,
  Hash,
  List,
  Loader2,
  Maximize2,
  Play,
  Type,
  Variable,
  X,
} from "lucide-vue-next";
```

- [ ] **Step 2: Import nodeIcons**

Add after the existing imports (around line 42):

```typescript
import { nodeIcons } from "@/lib/nodeIcons";
```

- [ ] **Step 3: Verify no import errors**

Run: `cd frontend && bun run typecheck`
Expected: No errors for icon imports

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/ExpressionInput.vue
git commit -m "feat: add icon imports for node navigation"
```

---

## Task 3: Add New Computed Variables for Node Navigation

**Files:**
- Modify: `frontend/src/components/ui/ExpressionInput.vue:130-177` (computed variables section)

- [ ] **Step 1: Add prevNode computed variable**

Add after the `availableNodeResults` computed (around line 160):

```typescript
const prevNode = computed((): WorkflowNode | null => {
  if (!props.currentNodeId || !props.nodes || !props.edges) {
    return null;
  }
  const prevEdge = props.edges.find((e) => e.target === props.currentNodeId);
  return props.nodes.find((n) => n.id === prevEdge?.source) ?? null;
});
```

- [ ] **Step 2: Add nextNode computed variable**

Add after prevNode:

```typescript
const nextNode = computed((): WorkflowNode | null => {
  if (!props.currentNodeId || !props.nodes || !props.edges) {
    return null;
  }
  const nextEdge = props.edges.find((e) => e.source === props.currentNodeId);
  return props.nodes.find((n) => n.id === nextEdge?.target) ?? null;
});
```

- [ ] **Step 3: Add prevNodeIcon computed variable**

Add after nextNode:

```typescript
const prevNodeIcon = computed(() => {
  if (!prevNode.value) {
    return null;
  }
  return nodeIcons[prevNode.value.type] ?? Type;
});
```

- [ ] **Step 4: Add nextNodeIcon computed variable**

Add after prevNodeIcon:

```typescript
const nextNodeIcon = computed(() => {
  if (!nextNode.value) {
    return null;
  }
  return nodeIcons[nextNode.value.type] ?? Type;
});
```

- [ ] **Step 5: Add paramChips computed variable**

Add after nextNodeIcon:

```typescript
const paramChips = computed(() => {
  return (props.availableParams ?? []).map((param, index) => ({
    name: param.label || param.key,
    key: param.key,
    index,
    isActive: index === props.activeParamIndex,
    hasValue: !!param.value?.trim(),
  }));
});
```

- [ ] **Step 6: Verify type checking**

Run: `cd frontend && bun run typecheck`
Expected: No errors for new computed variables

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ui/ExpressionInput.vue
git commit -m "feat: add computed variables for node navigation and parameter chips"
```

---

## Task 4: Add Helper Functions

**Files:**
- Modify: `frontend/src/components/ui/ExpressionInput.vue:750-802` (function definitions section)

- [ ] **Step 1: Add truncateString helper function**

Add after the `findDollarExpressions` function (around line 802):

```typescript
function truncateString(str: string, maxLength: number): string {
  if (!str || str.length <= maxLength) {
    return str || "";
  }
  return `${str.slice(0, maxLength - 3)}...`;
}
```

- [ ] **Step 2: Add toTitleCase helper function**

Add after truncateString:

```typescript
function toTitleCase(str: string): string {
  return str
    .replace(/([A-Z])/g, " $1")
    .replace(/^./, (char) => char.toUpperCase())
    .trim();
}
```

- [ ] **Step 3: Verify type checking**

Run: `cd frontend && bun run typecheck`
Expected: No errors for helper functions

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/ExpressionInput.vue
git commit -m "feat: add helper functions for truncation and title case"
```

---

## Task 5: Add New Event Handlers

**Files:**
- Modify: `frontend/src/components/ui/ExpressionInput.vue:690-750` (handler functions section)

- [ ] **Step 1: Add handleParamSelect handler**

Add after the `closeExpandDialog` function (around line 690):

```typescript
function handleParamSelect(index: number): void {
  if (!props.availableParams || index >= props.availableParams.length) {
    return;
  }

  const param = props.availableParams[index];
  dialogValue.value = param.value || "";
  activeParamIndex.value = index;

  runResult.value = null;
  inspectedRunResult.value = null;
  runRequestError.value = null;

  nextTick((): void => {
    dialogTextareaRef.value?.focus();
  });
}
```

- [ ] **Step 2: Add handleParamClear handler**

Add after handleParamSelect:

```typescript
function handleParamClear(index: number): void {
  if (!props.availableParams || index >= props.availableParams.length) {
    return;
  }

  const param = props.availableParams[index];
  dialogValue.value = "";

  emit("update:modelValue", "");
  emit("update:param", param.key, "");
}
```

- [ ] **Step 3: Add handleNavigatePrev handler**

Add after handleParamClear:

```typescript
function handleNavigatePrev(): void {
  if (!prevNode.value) {
    return;
  }

  emit("update:modelValue", dialogValue.value);
  emit("navigate", "prev");
}
```

- [ ] **Step 4: Add handleNavigateNext handler**

Add after handleNavigatePrev:

```typescript
function handleNavigateNext(): void {
  if (!nextNode.value) {
    return;
  }

  emit("update:modelValue", dialogValue.value);
  emit("navigate", "next");
}
```

- [ ] **Step 5: Verify type checking**

Run: `cd frontend && bun run typecheck`
Expected: No errors for new handlers

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ui/ExpressionInput.vue
git commit -m "feat: add handlers for param selection, clearing, and node navigation"
```

---

## Task 6: Add New Event to Emits Interface

**Files:**
- Modify: `frontend/src/components/ui/ExpressionInput.vue:86-90` (emits definition)

- [ ] **Step 1: Extend emits interface with update:param event**

Replace the existing emits definition with:

```typescript
const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
  (e: "navigate", direction: "prev" | "next"): void;
  (e: "update:param", paramKey: string, value: string): void;
}>();
```

- [ ] **Step 2: Verify type checking**

Run: `cd frontend && bun run typecheck`
Expected: No errors for emit definition

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/ExpressionInput.vue
git commit -m "feat: add update:param event emit"
```

---

## Task 7: Add Navigation Header to Dialog Template

**Files:**
- Modify: `frontend/src/components/ui/ExpressionInput.vue:880-920` (Dialog section in template)

- [ ] **Step 1: Find the Dialog component opening tag**

Find `<Dialog` tag in the template (around line 880), then add the navigation header section immediately after the opening Dialog tag but before any existing dialog content:

```vue
  <!-- New Navigation Header -->
  <div
    v-if="
      props.navigationEnabled ||
      (props.availableParams && props.availableParams.length > 1)
    "
    class="flex items-center gap-3 px-6 py-3 border-b border-border/40"
  >
    <!-- Previous Node Navigation -->
    <button
      v-if="props.navigationEnabled && prevNode"
      type="button"
      class="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-muted/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      :disabled="!prevNode"
      @click="handleNavigatePrev"
    >
      <ChevronLeft class="w-4 h-4" />
      <component :is="prevNodeIcon" class="w-5 h-5 text-muted-foreground" />
      <span class="text-sm font-medium truncate max-w-[120px]">
        {{ truncateString(prevNode.data.label || prevNode.type, 24) }}
      </span>
    </button>

    <!-- Parameter Chips -->
    <div
      v-if="props.availableParams && props.availableParams.length > 1"
      class="flex-1 flex items-center gap-2 overflow-x-auto scrollbar-hide"
    >
      <button
        v-for="chip in paramChips"
        :key="chip.key"
        type="button"
        :class="
          cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all shrink-0',
            chip.isActive
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'bg-muted/70 text-muted-foreground hover:bg-muted',
          )
        "
        @click="handleParamSelect(chip.index)"
      >
        <span>{{ truncateString(chip.name, 20) }}</span>
        <X
          v-if="chip.hasValue"
          class="w-3.5 h-3 opacity-70 hover:opacity-100 transition-opacity"
          @click.stop="handleParamClear(chip.index)"
        />
      </button>
    </div>

    <!-- Next Node Navigation -->
    <button
      v-if="props.navigationEnabled && nextNode"
      type="button"
      class="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-muted/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      :disabled="!nextNode"
      @click="handleNavigateNext"
    >
      <span class="text-sm font-medium truncate max-w-[120px]">
        {{ truncateString(nextNode.data.label || nextNode.type, 24) }}
      </span>
      <component :is="nextNodeIcon" class="w-5 h-5 text-muted-foreground" />
      <ChevronRight class="w-4 h-4" />
    </button>
  </div>
```

- [ ] **Step 2: Verify no syntax errors**

Run: `cd frontend && bun run typecheck`
Expected: No Vue template or TypeScript errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/ExpressionInput.vue
git commit -m "feat: add navigation header to ExpressionInput dialog"
```

---

## Task 8: Add CSS for Scrollbar Hiding

**Files:**
- Modify: `frontend/src/components/ui/ExpressionInput.vue:1240-1260` (style section)

- [ ] **Step 1: Add scrollbar-hide utility class to style section**

Find the `<style scoped>` section at the end of the file and add these CSS rules before the closing `</style>` tag:

```css
.scrollbar-hide {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.scrollbar-hide::-webkit-scrollbar {
  display: none;
}
```

- [ ] **Step 2: Verify no CSS linting errors**

Run: `cd frontend && bun run lint`
Expected: No linting errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/ExpressionInput.vue
git commit -m "style: add scrollbar-hide CSS utility"
```

---

## Task 9: Final Verification

**Files:**
- Test: Frontend development environment

- [ ] **Step 1: Run type checking**

Run: `cd frontend && bun run typecheck`
Expected: All TypeScript checks pass

- [ ] **Step 2: Run linting**

Run: `cd frontend && bun run lint`
Expected: All ESLint checks pass

- [ ] **Step 3: Commit final changes**

```bash
git add frontend/src/components/ui/ExpressionInput.vue
git commit -m "refactor: complete ExpressionInput parametric evaluation implementation"
```

- [ ] **Step 4: Start development server**

Run: `cd frontend && bun run dev`
Expected: Development server starts successfully on port 4017

- [ ] **Step 5: Manual test - Backward compatibility**

1. Open workflow canvas
2. Click on a node property that uses ExpressionInput
3. Verify dialog opens without navigation header (default behavior)
4. Verify existing functionality still works

- [ ] **Step 6: Manual test - Parameter chips**

1. Add a new node with multiple numeric/string inputs (e.g., LLM node with "text", "temperature", "system_prompt")
2. Open ExpressionInput dialog for one field
3. Set navigationEnabled=true, availableParams with array of parameters
4. Verify parameter chips appear in header
5. Click different chips - verify expression changes
6. Verify active chip styling
7. Click X on a chip - verify value clears

- [ ] **Step 7: Manual test - Node navigation**

1. Create a workflow with 3 nodes connected in sequence (Node A → Node B → Node C)
2. Select Node B, set navigationEnabled=true
3. Click "Next" button - verify moves to Node C
4. Click "Previous" button - verify moves back to Node B
5. Verify node icons and names display correctly
6. Test at boundary nodes (first and last node) - verify buttons disabled

- [ ] **Step 8: Document any findings**

If you find any issues or edge cases not covered, note them for future improvement.

---

**Plan End**

**Next Steps:** After completing all tasks, the feature is ready for production use. Parent components can now pass the new props (`navigationEnabled`, `availableParams`, `activeParamIndex`, etc.) to enable parametric evaluation and node navigation.