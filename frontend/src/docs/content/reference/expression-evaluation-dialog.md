# Expression Evaluation Dialog

The Expression Evaluation Dialog is the expanded editor for expression-capable fields. It opens from the expand button next to an expression input and gives you a larger workspace, autocomplete, live backend preview, and output browsing in one place.

## Opening the Dialog

- Click the expand button next to an expression field in the Properties panel.
- Multi-line fields show the button inside the input.
- Single-line fields show the button to the right of the input.

## Dialog Layout

- The dialog opens as a centered modal at roughly **80vw × 80vh**.
- The header shows **Evaluate — {field name}** when the field label is known.
- The editor keeps autocomplete, field-to-field navigation, and the usual **Apply** / **Cancel** actions.
- The preview refreshes automatically about **300 ms** after you stop typing.
- Press `Ctrl` / `Cmd` + `Enter` to apply the current text back to the field without closing the dialog.

## Output Section

The Output area refreshes automatically after you pause typing in the editor.

### Evaluation

| Expression type | Result |
|---|---|
| Single `$expr` (entire field) | Native value is preserved |
| Single bare dot path (entire field, no `$`, no embedded newline) | Same as `$` + that path (backend normalizes for evaluation) |
| Text with embedded `$refs` | Final result is always a string |
| Literal text (no `$`, not a single dot path) | Returned as-is |

**Examples**

| Input | Result |
|---|---|
| `$input.items` | `[1, 2, 3]` |
| `input.items` (same as `$input.items` when the whole value is this path) | `[1, 2, 3]` |
| `Hello $input.name` | `Hello John` |
| `$input.count + 1` | `6` |
| `just text` | `just text` |

Evaluation context is built in this order:

- **Pinned data** on upstream nodes
- **Last run outputs** from the canvas
- `null` when no upstream data is available

If the current node has upstream dependencies but none of them have pinned data or a recent run result, the dialog first performs a test run to build context and then evaluates the current text.

### Output Path Picker

When the backend result is an object or array, the Output area can show an interactive path picker instead of raw JSON.

- Double-click a row to append that path to the current `$node.path` reference.
- Single-click expandable rows to open or close branches.
- Use the built-in query box to search keys, values, and path strings.

## Autocomplete

- Type `$` to open suggestions for upstream nodes, built-ins, and methods.
- Press `Tab` or `Enter` to insert the selected suggestion.
- Use `↑` / `↓` to move through the suggestion list.

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| Typing pause (~300 ms) | Refresh backend preview |
| `Ctrl` / `Cmd` + `Enter` | Apply without closing |
| `Escape` | Close autocomplete first, otherwise close the dialog |

## Nested `$` in method arguments

For dialog / backend evaluation, you can pass another reference with a nested `$` inside calls such as `.get($other.field)` when you need a dynamic key. You can also use a bare path inside `.get(...)` (for example `other.field`); the backend resolves it the same way. Saved workflow fields should still follow the [Expression DSL](./expression-dsl.md) rules; the evaluate API also accepts a full-line bare dot path for convenience (see table above).

## Navigation

Set and Execute mapping editors can show **Prev** / **Next** buttons so you can move between fields without closing the dialog.

## Related

- [Expression DSL](./expression-dsl.md)
- [Node Types](./node-types.md)
- [LLM Node](../nodes/llm-node.md)
- [Output Node](../nodes/output-node.md)
- [Condition Node](../nodes/condition-node.md)
