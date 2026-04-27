# Quick Drawer

The **Quick Drawer** is a right-side fast-run panel for workflows. It appears on authenticated pages such as the dashboard [Workflows tab](../tabs/workflows-tab.md), Docs, and Evals.

## Access

- Click the fixed **Quick / Workflows** trigger on the right-middle edge of the screen
- When the [Contextual Showcase](./contextual-showcase.md) is also available, its **Page Guide** trigger sits above Quick Workflows
- The drawer opens from the right and shifts the current page left with a subtle rescale
- On mobile, the Quick Drawer is hidden
- The drawer is not shown on the workflow editor, login/register, portal, or HITL review pages

## Workflow Search

Use the filter field at the top of the drawer to search workflows by:

- Workflow name
- Workflow description

Search is case-insensitive and updates the list immediately.

## Pinned Workflows

Pin workflows to keep them at the top of the drawer.

- Pinned workflows appear in their own section above the full list
- New pins are added to the top
- Pin order is preserved across reloads in browser storage

## Running Workflows

Select a workflow to open its input form.

- Input fields are shown vertically in drawer order
- Click **Run Workflow** to execute the selected workflow
- Click **Stop Workflow** to cancel a running execution from the drawer
- Workflows without Input fields can still be run directly

The drawer uses the same workflow execution API as other Heym run surfaces, so outputs and runtime behavior stay consistent.

Stopping a run from the drawer also cancels the active backend execution, including any in-flight Playwright browser job for that workflow run.

## Progress and Results

After starting a run, the drawer shows:

- Streaming step progress for nodes as they start and finish
- Final status: `success`, `error`, or `pending`
- Final outputs in a compact JSON panel
- History entries tagged with `Quick Drawer`

`pending` means the workflow is waiting for a later action such as human review.

## Browser Storage

The Quick Drawer stores personal preferences in `localStorage`:

- Pinned workflow IDs
- Last selected workflow

The drawer does **not** persist input values in this version.

## Scope

The Quick Drawer is intentionally a lightweight execution surface.

- Included: search, pinning, select, input, run, progress, result
- Excluded: workflow creation, editing, folder management, and canvas actions

## Related

- [Workflows Tab](../tabs/workflows-tab.md) – Main workflow list, folders, and management
- [Quick Start](../getting-started/quick-start.md) – Build and run your first workflow
- [Execution History](./execution-history.md) – Review past runs
- [Webhooks](./webhooks.md) – Trigger workflows over HTTP
- [Contextual Showcase](./contextual-showcase.md) – Page-level guidance rail that complements Quick Drawer
