# ExpressionInput Parametric Evaluation & Node Navigation — Design Spec

**Date:** 2026-04-12
**Status:** Approved
**Scope:** Frontend (ExpressionInput.vue)

---

## 1. Background & Problem Statement

Heym's current `ExpressionInput.vue` dialog evaluates only one expression at a time. For nodes with multiple input parameters, users must:
1. Close the dialog
2. Click a different input field
3. Re-open the dialog
4. Repeat for each parameter

There is also no way to navigate between nodes when evaluating expressions — users must close the dialog, click a different node on the canvas, and open it again.

These workflows are inefficient for complex nodes with many inputs and when debugging multi-node workflows.

### Root problems

1. **No multi-parameter support** — Cannot switch between parameters within a single dialog session
2. **No node navigation** — Must close and reopen dialog to evaluate a different node
3. **Disjointed debugging** — Makes it hard to quickly test multiple parameters across multiple nodes
4. **Missing context** — Users lose track of which field they are editing and what's available

---

## 2. Goal

Extend `ExpressionInput.vue` to support:
1. **Parameter chips** that let users switch between multiple input parameters within a node without closing the dialog
2. **Node navigation** (previous/next) that lets users move between adjacent nodes and evaluate the first parameter of each
3. **Clear visual hierarchy** showing selected node, available parameters, and navigational context

All changes are frontend-only. No backend changes required.

---

## 3. Architecture

```
[ExpressionInput.vue — expanded with header navigation]
├── New Header Section
│   ├── Left: Previous Node Nav (flex-shrink-1)
│   │   ├── ChevronLeft icon
│   │   ├── Previous node icon (from nodeIcons)
│   │   ├── Previous node name (truncated)
│   ├── Center: Parameter Chips (flex-1, overflow-x-auto)
│   │   └── Scrollable horizontal container
│   │       └── Chips (rounded-full)
│   │           ├── Active: bg-primary text-primary-foreground
│   │           └── Inactive: bg-secondary text-secondary-foreground
│   └── Right: Next Node Nav (flex-shrink-1)
│       ├── Next node name (truncated)
│       ├── Next node icon
│       └── ChevronRight icon
├── Expression Textarea (existing)
├── Output Display (existing)
└── Footer Buttons (existing)
```

### Data Flow

```
User clicks chip
    ↓
activeParamIndex updates
    ↓
dialogValue loads expression for selected parameter
    ↓
User edits and evaluates (existing behavior)
    ↓
On apply: node.data[paramName] is updated (existing)
```

```
User clicks next node button
    ↓
emit("update:modelValue") — save current expression
    ↓
emit("navigate", "next")
    ↓
Parent updates currentNodeId and availableParams
    ↓
activeParamIndex = 0 (first parameter)
    ↓
dialogValue loads first parameter's expression
```

---

## 4. Frontend Changes

### 4.1 New Props

```typescript
interface Props {
  // Existing props...
  navigationEnabled?: boolean;  // Enable node navigation (default: false)
  navigationIndex?: number;     // Current node index (optional display)
  navigationTotal?: number;     // Total nodes (optional display)
  availableParams? ParamInfo[]; // Available parameters for current node
  activeParamIndex?: number;    // Currently selected parameter index
}

interface ParamInfo {
  key: string;           // Parameter name (e.g., "text", "temperature")
  label: string;         // Display label (e.g., "Text", "Temperature")
  value: string;         // Current expression value
}
```

### 4.2 New Computed Variables

```typescript
const prevNode = computed(() => {
  if (!props.currentNodeId || !props.nodes || !props.edges) return null;
  const prevEdge = props.edges.find(e => e.target === props.currentNodeId);
  return props.nodes.find(n => n.id === prevEdge?.source) ?? null;
});

const nextNode = computed(() => {
  if (!props.currentNodeId || !props.nodes || !props.edges) return null;
  const nextEdge = props.edges.find(e => e.source === props.currentNodeId);
  return props.nodes.find(n => n.id === nextEdge?.target) ?? null;
});

const prevNodeIcon = computed(() => {
  if (!prevNode.value) return null;
  return nodeIcons[prevNode.value.type] ?? Type; // Fallback to generic icon
});

const nextNodeIcon = computed(() => {
  if (!nextNode.value) return null;
  return nodeIcons[nextNode.value.type] ?? Type;
});

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

### 4.3 New Handlers

```typescript
function handleParamSelect(index: number): void {
  if (!props.availableParams || index >= props.availableParams.length) return;

  const param = props.availableParams[index];
  dialogValue.value = param.value || "";
  activeParamIndex.value = index;

  // Clear evaluation results
  runResult.value = null;
  inspectedRunResult.value = null;
  runRequestError.value = null;

  nextTick(() => {
    dialogTextareaRef.value?.focus();
  });
}

function handleParamClear(index: number): void {
  if (!props.availableParams || index >= props.availableParams.length) return;

  const param = props.availableParams[index];
  dialogValue.value = "";

  // Update node data (debounced save happens via existing watch)
  emit("update:modelValue", "");
  emit("update:param", param.key, ""); // New event for parameter updates
}

function handleNavigatePrev(): void {
  if (!prevNode.value) return;

  // Save current expression first
  emit("update:modelValue", dialogValue.value);
  emit("navigate", "prev");
}

function handleNavigateNext(): void {
  if (!nextNode.value) return;

  // Save current expression first
  emit("update:modelValue", dialogValue.value);
  emit("navigate", "next");
}
```

### 4.4 New Emits

```typescript
const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
  (e: "navigate", direction: "prev" | "next"): void;
  (e: "update:param", paramKey: string, value: string): void; // New
}>();
```

### 4.5 Dialog Template Changes

Add new header section before `<Dialog body>`:

```vue
<Dialog
  :open="showExpandDialog"
  :title="dialogTitle"
  size="2xl"
  @close="closeExpandDialog"
>
  <!-- New Navigation Header -->
  <div v-if="navigationEnabled || (availableParams && availableParams.length > 1)" class="flex items-center gap-3 px-6 py-3 border-b border-border/40">
    <!-- Previous Node Navigation -->
    <button
      v-if="navigationEnabled && prevNode"
      type="button"
      class="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-muted/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      :disabled="!prevNode"
      @click="handleNavigatePrev"
    >
      <ChevronLeft class="w-4 h-4" />
      <component
        :is="prevNodeIcon"
        class="w-5 h-5 text-muted-foreground"
      />
      <span class="text-sm font-medium truncate max-w-[120px]">
        {{ truncateString(prevNode.data.label || prevNode.type, 24) }}
      </span>
    </button>

    <!-- Parameter Chips -->
    <div
      v-if="availableParams && availableParams.length > 1"
      class="flex-1 flex items-center gap-2 overflow-x-auto scrollbar-hide"
    >
      <button
        v-for="chip in paramChips"
        :key="chip.key"
        type="button"
        :class="cn(
          'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all shrink-0',
          chip.isActive
            ? 'bg-primary text-primary-foreground shadow-sm'
            : 'bg-muted/70 text-muted-foreground hover:bg-muted'
        )"
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
      v-if="navigationEnabled && nextNode"
      type="button"
      class="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-muted/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      :disabled="!nextNode"
      @click="handleNavigateNext"
    >
      <span class="text-sm font-medium truncate max-w-[120px]">
        {{ truncateString(nextNode.data.label || nextNode.type, 24) }}
      </span>
      <component
        :is="nextNodeIcon"
        class="w-5 h-5 text-muted-foreground"
      />
      <ChevronRight class="w-4 h-4" />
    </button>
  </div>

  <!-- Rest of existing dialog content -->
  ...
</Dialog>
```

### 4.6 Helper Functions

```typescript
function truncateString(str: string, maxLength: number): string {
  if (!str || str.length <= maxLength) return str || "";
  return `${str.slice(0, maxLength - 3)}...`;
}

function toTitleCase(str: string): string {
  return str
    .replace(/([A-Z])/g, " $1")
    .replace(/^./, (char) => char.toUpperCase())
    .trim();
}
```

### 4.7 CSS Updates

Add to ExpressionInput.vue `<style>`:

```css
.scrollbar-hide {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.scrollbar-hide::-webkit-scrollbar {
  display: none;
}
```

### 4.8 Parent Component Integration

Example usage in `PropertiesPanel.vue`:

```typescript
const availableParams = computed(() => {
  if (!selectedNode.value) return [];
  const paramKeys = Object.keys(selectedNode.value.data)
    .filter(k => k !== 'label' && k !== 'pinnedData' && k !== 'visible');

  return paramKeys.map(key => ({
    key,
    label: toTitleCase(key),
    value: selectedNode.value?.data[key]?.toString() ?? "",
  }));
});

const activeParamIndex = ref(0);

function handleNavigate(direction: "prev" | "next"): void {
  const nodes = workflowStore.currentWorkflow?.nodes ?? [];
  const currentNode = selectedNode.value;
  if (!currentNode) return;

  const currentIndex = nodes.findIndex(n => n.id === currentNode.id);
  const targetIndex = direction === "next" ? currentIndex + 1 : currentIndex - 1;

  if (targetIndex >= 0 && targetIndex < nodes.length) {
    selectedNode.value = nodes[targetIndex];
    activeParamIndex.value = 0; // Reset to first parameter
    // Force ExpressionInput to re-render with new props
    // ...
  }
}
```

---

## 5. Responsive & Edge Case Handling

### Responsive Behavior

| Breakpoint | Behavior |
|------------|----------|
| Desktop (md+) | Full layout: left nav + chips + right nav |
| Tablet (sm) | Navigation buttons compressed, chips scrollable |
| Mobile | Navigation icon-only (chevron), chips swipe gesture optional |

### Edge Cases

| Case | Behavior |
|------|----------|
| No previous node | Left nav button disabled (opacity-50, cursor-not-allowed) |
| No next node | Right nav button disabled |
| Single node | Navigation buttons hidden |
| Single parameter | Chips area shows single chip, no scroll |
| No parameters | Chips area hidden |
| Long param name | Chip text truncated (ellipsis), tooltip on hover |
| Long node name | Node name truncated (max 24 chars) |
| No navigationEnabled flag | Navigation buttons hidden |
| Empty parameter selection | Chips hidden navigation shown |

---

## 6. Test Plan

**No backend tests needed** — feature is frontend-only. Manual testing scenarios:

### 6.1 Parameter Chips

- ✅ Select different parameter loads correct expression
- ✅ Active styling shows correct parameter
- ✅ Clearing X button removes expression
- ✅ Scrolling works with 10+ parameters
- ✅ Long parameter names truncate correctly
- ✅ Expression persists when switching parameters

### 6.2 Node Navigation

- ✅ Next button moves to correct node
- ✅ Previous button moves to correct node
- ✅ Parameters reset to first when navigating
- ✅ Expression saved before navigation
- ✅ Disabled state for boundary nodes
- ✅ Navigation buttons hidden when navigationEnabled=false

### 6.3 Edge Cases

- ✅ Single node scenario
- ✅ Single parameter scenario
- ✅ No parameters scenario
- ✅ Workflow with 3+ nodes
- ✅ Rapid clicking (no state corruption)

---

## 7. Migration & Backward Compatibility

### Backward Compatibility

- All changes are additive. Existing usage without new props works exactly as before.
- Default behavior: No navigation chips, no node buttons (same as current).
- `navigationEnabled` defaults to `false` — opt-in feature.

### Migration Steps

1. Extend `ExpressionInput.vue` with new props, computed, handlers
2. Add header navigation section to dialog template
3. Update `PropertiesPanel.vue` to pass navigation props when evaluating nested inputs
4. Test in development environment
5. No database migrations or backend changes required

---

## 8. Out of Scope

- Backend API changes
- Database schema changes
- Workflow JSON structure changes
- Expression syntax changes
- Multi-select parameters
- Parameter reordering
- Parameter descriptions/tooltips in chips (can be added later)

---

## 9. Success Criteria

- [ ] Users can switch between parameters without closing dialog
- [ ] Previous/next node navigation works correctly
- [ ] Active parameter is visually distinct
- [ ] Navigation buttons show correct node icons and names
- [ ] Expressions persist when switching parameters
- [ ] Backward compatibility maintained (existing usage unchanged)
- [ ] `bun run lint` passes
- [ ] `bun run typecheck` passes
- [ ] Manual testing of all scenarios in §6 passes