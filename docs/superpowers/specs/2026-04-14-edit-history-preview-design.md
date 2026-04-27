# Edit History — Version Preview

**Date:** 2026-04-14
**Status:** Approved

## Summary

Add a **Preview** button next to the existing **Revert** button in the Edit History dialog. Clicking it opens a read-only canvas dialog (same `4xl` size) showing the workflow's nodes and edges as they were at the selected version.

---

## Architecture

### New component: `WorkflowVersionPreviewDialog.vue`

**Location:** `frontend/src/components/Dialogs/WorkflowVersionPreviewDialog.vue`

**Props:**
```typescript
interface Props {
  open: boolean;
  version: WorkflowVersion | null;
}
```

**Emits:** `close`

**Behaviour:**
- Wraps the existing `Dialog` component with `size="4xl"` (matches Edit History dialog)
- Title: `"Version {version_number} Preview"`
- Body: Full-height VueFlow canvas fed directly from `version.nodes` and `version.edges` — **no extra API call**
- Canvas options: `nodes-draggable: false`, `nodes-connectable: false`, `elements-selectable: false`; pan and zoom enabled
- Includes `Background`, `Controls`, `MiniMap` to match the live canvas aesthetic
- When `version` is `null` nothing is rendered (guard)

### Changes to `WorkflowEditHistoryDialog.vue`

1. Add `previewOpen = ref(false)` and `previewVersion = ref<WorkflowVersion | null>(null)`
2. Add `openPreview(version: WorkflowVersion)` helper that sets both refs
3. In the template, inside the Changes panel header (same `v-if` condition as Revert: `selectedVersion && !isCurrentVersion`), add a **Preview** button with `Eye` icon, positioned to the **left** of Revert
4. Register and render `<WorkflowVersionPreviewDialog>` at the bottom of the template

---

## Data Flow

```
User selects version → selectedVersion computed
User clicks Preview  → openPreview(selectedVersion)
                     → previewVersion = selectedVersion
                     → previewOpen = true
WorkflowVersionPreviewDialog receives version.nodes + version.edges
VueFlow renders read-only canvas (no API call)
User closes dialog  → previewOpen = false
```

---

## Backend Tests

No new backend endpoint is introduced. `WorkflowVersion` already returns `nodes` and `edges` from the existing versions API.

Changes to `backend/tests/test_workflow_version.py`:
- Add edge-case tests for `calculate_workflow_diff` with empty node/edge lists (if not already covered) to improve coverage alongside this feature.

---

## Documentation

File: `frontend/src/docs/content/reference/edit-history.md`

Add a **Preview** section between the existing **Diff View** and **Revert** sections:

```markdown
## Preview

To see what the workflow looked like at a past version, click **Preview** next to Revert.
A read-only canvas opens showing the nodes and edges of that version. You can pan and zoom to explore the layout; no changes can be made from this view.
```

---

## Out of Scope

- Diff overlay on the preview canvas (highlight added/removed nodes)
- Side-by-side comparison of two versions
- Exporting the previewed version
