# Keyboard Shortcuts

Heym provides keyboard shortcuts across the workflow editor and canvas to speed up common actions.

## Global Editor Shortcuts

These shortcuts are active anywhere in the workflow editor.

| Shortcut | Action |
|----------|--------|
| `Ctrl + K` / `Cmd + K` | Open the Command Palette |
| `Ctrl + Enter` / `Cmd + Enter` | Run the current workflow |
| `Ctrl + S` / `Cmd + S` | Save the workflow |
| `Ctrl + Z` / `Cmd + Z` | Undo |
| `Ctrl + Shift + Z` / `Cmd + Shift + Z` | Redo |
| `Ctrl + Y` / `Cmd + Y` | Redo (alternate) |
| `Escape` | Dismiss open overlays, dialogs, and panels |

## Canvas Shortcuts

These shortcuts apply when the canvas is focused (no text input is active).

### Selection & Navigation

| Shortcut | Action |
|----------|--------|
| `Ctrl + A` / `Cmd + A` | Select all nodes |
| `Shift` (hold) | Drag to select multiple nodes |
| `Ctrl` / `Cmd` (hold) | Click to add individual nodes to the selection |
| `Escape` | Deselect all nodes; close inline node search |

### Editing Nodes

| Shortcut | Action |
|----------|--------|
| `Ctrl + C` / `Cmd + C` | Copy selected node(s) |
| `Ctrl + X` / `Cmd + X` | Cut selected node(s) |
| `Ctrl + V` / `Cmd + V` | Paste node(s) |
| `Delete` or `Backspace` | Delete selected node(s) and/or edge(s) |
| `D` | Toggle selected node(s) enabled / disabled |
| `P` | Toggle pinned data on the selected node |

### Inline Node Search

Typing any printable character on the canvas (when no text input is focused) opens the inline node search popup. The typed character becomes the first character of the search query.

| Shortcut | Action |
|----------|--------|
| Any printable character | Open inline node search and start typing |
| `Backspace` | Remove the last character from the search query |
| `Escape` | Close the inline node search |

## Command Palette (`Ctrl + K`)

The Command Palette is available from the editor, dashboard, docs, and evals views. It lets you quickly navigate to workflows, tabs, and documentation pages without leaving the keyboard.

| Shortcut | Action |
|----------|--------|
| `Ctrl + K` / `Cmd + K` | Open the Command Palette |
| `↑` / `↓` | Navigate the results list |
| `Tab` / `Shift + Tab` | Navigate the results list |
| `Enter` | Open the selected item |
| `Escape` | Close the palette |

## Properties Panel Shortcuts

These shortcuts are active while a node is selected and the properties panel is open.

| Shortcut | Action |
|----------|--------|
| `Ctrl + Shift + O` / `Cmd + Shift + O` | Open the linked sub-workflow in a new tab (Execute node only) |

## Evaluate Dialog Shortcuts

These shortcuts are active while the Evaluate dialog is open.

| Shortcut | Action |
|----------|--------|
| `Ctrl + Enter` / `Cmd + Enter` | Run the evaluator |
| `Ctrl + Z` / `Cmd + Z` | Undo changes in the expression editor |
| `Ctrl + Shift + Z` / `Cmd + Shift + Z` | Redo changes in the expression editor |
| `Ctrl + Y` / `Cmd + Y` | Redo changes in the expression editor (alternate) |

## History & Traces Shortcuts

These shortcuts are available in the Execution History dialog and the Traces panel.

| Shortcut | Action |
|----------|--------|
| `S` | Toggle the search input to filter entries |

## Related

- [Canvas Features](./canvas-features.md) – Data pin, enable/disable, extract to sub-workflow
- [Workflow Structure](./workflow-structure.md) – Node and edge format
- [Execute Node](../nodes/execute-node.md) – Calls sub-workflows (`Ctrl + Shift + O`)
- [Quick Start](../getting-started/quick-start.md) – Build your first workflow
