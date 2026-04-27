# Expression DSL

Heym uses a simple expression language to reference data from upstream nodes. Use expressions in node configuration such as LLM `userMessage`, Condition `condition`, Output `message`, Set mappings, and Variable values. Use the [Expression Evaluation Dialog](./expression-evaluation-dialog.md) for a larger editor, backend-powered live preview, and output path picking.

## Basic References

### Input Node vs Named Nodes

- **`$input`** – Use only when there is a single upstream [Input](../nodes/input-node.md) node and you want to reference its output. Example: `$input.text`. This is a shorthand for "the data from the connected input."
- **`$nodeLabel.field`** – Use to reference any upstream node by its **label** (the `label` in the node's data). Prefer this when you have multiple nodes or when the AI Assistant / workflow DSL expects explicit labels. Example: `$userInput.body.text`, `$myLLM.text`.

**When to use which:**

| Context | Prefer | Example |
|--------|--------|---------|
| Single input node, simple flow | `$input.text` | Output message from one Input |
| Multiple nodes or named references | `$nodeLabel.field` | `$userInput.body.text`, `$fetchLLM.text` |
| [AI Assistant](./ai-assistant.md) / workflow JSON | Always `$nodeLabel.field` | The workflow builder expects labels, not `$input` |

### Input Node

Use `$input` to reference the Input node's data when there is a single upstream input:

```
$input.text
```

### Named Nodes

Reference any upstream node by its label. When a node has [pinned data](./canvas-features.md#data-pin), expression completion uses that instead of execution output.

```
$llm.text
$httpResponse.body
$condition
```

### Credentials

Use `$credentials.CredentialName` to reference credential values (e.g. API keys) by name. See [Credentials Sharing](./credentials-sharing.md).

```
$credentials.MyBearerToken
```

### Global Variables

Use `$global.variableName` to reference [Global Variables](./global-variables.md) – persistent, user-scoped key-value data managed in the [Variables tab](../tabs/global-variables-tab.md).

```
$global.apiKey
$global.settings.baseUrl
```

### Nested Fields

Use dot notation for nested objects:

```
$llm.choices[0].message.content
$input.metadata.userId
```

## Literals

- **Strings**: `"hello"` or `'hello'`
- **Numbers**: `42`, `3.14`
- **Booleans**: `true`, `false`
- **Null**: `null`

## Type Preservation

When the **entire** value is a single `$expr`, the backend preserves the native type:

- `$node.items` → `[1, 2, 3]`
- `$node.meta` → `{"key": "value"}`
- `$node.active` → `true`

When an expression is part of a larger string, the final result is always a string:

- `Count: $node.count` → `"Count: 5"`
- `Hello $node.name` → `"Hello Ada"`

## Arithmetic

Supported operators: `+`, `-`, `*`, `/`, `%`

```
$input.count + 1
$llm.tokens * 2
```

## Comparisons

Use in [Condition](../nodes/condition-node.md) nodes: `==`, `!=`, `>`, `<`, `>=`, `<=`, `&&`, `||`

```
$input.text.length > 0
$llm.text != ""
```

## Loop Context

Inside a [Loop](../nodes/loop-node.md) node, use `item` to reference the current array element:

```
item.name
item.value
```

## Special Variables
- `$now` - Current datetime with formatting methods
- `$Date()` - Create/parse date (e.g. `$Date("2024-01-15")`)
- `$UUID` - Generate 32-character unique identifier (NO parentheses; use `$UUID` not `$UUID()`)
- `$vars` - Workflow-local variables (access via `$vars.variableName`; updated via `variable` node)
- `$global` - Persistent global variable store (access via `$global.variableName`)

### $vars Usage
- `$vars.counter` - Access a variable named `counter`
- `$vars.myArray.add("item")` - Add item to an array variable

### $global Usage
- `$global.apiKey` - Access a global variable named `apiKey`
- `$global.settings.baseUrl` - Access nested fields in an object-type global variable

## Request Context (API Execution)
When a workflow is executed via HTTP API, input nodes receive additional request metadata:
- `$textInputLabel.body` - HTTP request body object (raw JSON payload)
- `$textInputLabel.headers` - HTTP request headers object (all header keys are lowercase)
- `$textInputLabel.query` - URL query parameters object

Access request data like:
- `$userInput.body.fieldName`
- `$userInput.query.paramName`
- `$userInput.headers["x-api-key"]`

## Type Conversion Functions
- `str(value)` - Convert to string
- `int(value)` - Convert to integer
- `float(value)` - Convert to float
- `bool(value)` - Convert to boolean
- `list(value)` - Convert to list
- `dict(key=value, ...)` - Create dictionary with keyword arguments (e.g. `$dict(name="Ali", age=30)`)

## Math Functions
- `len(value)` - Get length
- `abs(value)` - Absolute value
- `min(a, b)` - Minimum value
- `max(a, b)` - Maximum value
- `round(value)` - Round number
- `sum(list)` - Sum of list
- `sorted(list)` - Sort list
- `randomInt(min, max)` - Random integer

## Array Functions
- `$array(a, b, c)` - Create array from arguments (e.g. `$array(1, 2, 3)` -> `[1, 2, 3]`)
- `$range(a, b)` - Create integer range from `a` to `b` with `b` excluded (e.g. `$range(1, 5)` -> `[1, 2, 3, 4]`)
  - Fails when `a > b`
- `notNull(list)` - Remove null values from array

## String Building Function (for map/filter expressions)
- `concat(a, b, c, ...)` - Concatenate N arguments
  - Use inside `.map()` as an expression string (no `$` inside the string)
  - Use single quotes inside the concat string:
    - Correct: `concat('prefix', 'item.field', 'suffix')`

## Object Literals / Dictionaries
Create objects/dictionaries using curly brace syntax with any string keys:
- `${"name": "Ali", "age": 30}` -> `{"name": "Ali", "age": 30}`

### Dynamic Keys
- `${now.format("MMMM DD"): "Today's value"}`
- `${"item_" + str(loopNode.index): loopNode.item}`

### Object Literal Rules
- Keys can be any string (including spaces/special characters)
- Keys MUST be quoted with double quotes (e.g. `"key"`)
- Values can be strings/numbers/booleans/expressions/nested objects

## String Functions
- `upper(text)` - Uppercase
- `lower(text)` - Lowercase
- `strip(text)` - Trim whitespace
- `capitalize(text)` - Capitalize first letter
- `title(text)` - Title case
- `split(text, separator)` - Split string
- `join(separator, list)` - Join list
- `replace(text, old, new)` - Replace text
- `regexReplace(text, pattern, replacement)` - Replace with regex pattern

## String Methods (on string values)
- `.upper()` / `.lower()` - Case conversion
- `.strip()` - Trim whitespace
- `.capitalize()` / `.title()` - Capitalize
- `.length` - String length
- `.toString()` - Convert to string
- `.substring(start, end)` - Extract substring
- `.contains(text)` - Check if contains substring
- `.startswith(prefix)` / `.endswith(suffix)` - Check prefix/suffix
- `.indexOf(text)` - Find position (returns -1 if not found)
- `.replace(old, new)` - Replace first occurrence
- `.replaceAll(old, new)` - Replace all occurrences
- `.regexReplace(pattern, replacement)` - Replace with regex pattern
- `.hash()` - MD5 hash of the string
- `.urlEncode()` - URL encode string
- `.urlDecode()` - URL decode string
- `.escape()` - JSON escape string (convert special characters to JSON format)
- `.unescape()` - JSON unescape string (convert JSON format to original string)

### String Method Examples
- `$text.upper()` - Convert to uppercase
- `$text.lower()` - Convert to lowercase
- `$text.strip()` - Remove whitespace
- `$text.replace("old", "new")` - Replace text
- `$text.replaceAll("a", "b")` - Replace all occurrences
- `$text.length` - Get string length
- `$text.escape()` - Escape special JSON characters (e.g., quotes, newlines)
- `$escapedText.unescape()` - Unescape JSON formatted string back to original
- `$text.urlEncode()` - URL encode for API parameters
- `$encodedText.urlDecode()` - Decode URL encoded text

## Array Methods (on arrays)
- `.first()` - Get first element
- `.last()` - Get last element
- `.random()` - Get random element
- `.reverse()` - Reverse array
- `.flat()` - Flatten nested arrays into a single array
- `.flat(depth)` - Flatten with depth limit
- `.distinct()` - Remove duplicates
- `.distinctBy(expr)` - Remove duplicates by expression (e.g. `$array.distinctBy("item.id")`)
- `.notNull()` - Remove null values
- `.add(item)` - Append item (returns new array)
- `.contains(item)` - Check if array contains item (returns boolean)
- `.join(separator)` - Join array elements into a string
- `.filter(expr)` - Filter array using `item` variable (e.g. `$array.filter("item > 5")`)
- `.map(expr)` - Transform each element using `item` variable (e.g. `$array.map("item.name")`)
- `.sort(expr, order)` - Sort by expression, order is `"asc"` (default) or `"desc"`
- `.take(n)` - Take first N (positive) or last N (negative) elements
- `.length` - Array length
- `.toString()` - Convert to JSON string

### Filter / Map / Sort Examples
- `$numbers.filter("item > 5")`
- `$users.filter("item.active == true")`
- `$users.map("item.name")`
- `$numbers.map("item * 2")`
- `$users.sort("item.age")`
- `$numbers.sort("item", "desc")`
- `$numbers.take(3)`
- `$numbers.take(-2)`

## Object/Dictionary Methods (on objects)
- `.get(key)` - Get value by key (returns null if not found)
- `.get(key, default)` - Get value by key with default fallback
- `.keys()` - Return a list of all keys
- `.values()` - Return a list of all values
- `.entries()` - Return a list of `{key, value}` objects (one per property)
- `.filter(expr)` - Iterate `{key, value}` entries and return matching entries as a list (use `item.key` / `item.value` inside `expr`)
- `.map(expr)` - Iterate `{key, value}` entries and return a list of transformed values (use `item.key` / `item.value` inside `expr`)
- `.toString()` - Convert to JSON string

### Object Iteration Examples
When iterating an object with `.map()` or `.filter()`, each `item` is a `{key, value}` pair:

- `$readSheet.rows.first().keys()` → `["colA", "colB"]`
- `$readSheet.rows.first().values()` → `["foo", "bar"]`
- `$readSheet.rows.first().map("item.value")` → `["foo", "bar"]`
- `$readSheet.rows.first().map("concat('item.key', ': ', 'item.value')")` → `["colA: foo", "colB: bar"]`
- `$profile.filter("item.value != null").map("item.key")` → list of property names that are not null

## Date/Time
- `$now` - Current datetime
- `$now.format("YYYY-MM-DD")` - Format date/time
- `$now.toISO()` / `.toDate()` / `.toTime()` - Convert formats
- `$now.addDays(n)` / `.addHours(n)` - Date math
- `$Date("2024-01-15")` - Parse date string

## Numeric Operations
- Basic math: `+`, `-`, `*`, `/`, `%`
- Comparisons: `>`, `<`, `>=`, `<=`, `==`, `!=`
- Boolean operators: `and`, `or`, `not`

## Boolean Conditions
For booleans, write the expression directly (do not force `== true`):
- Wrong: `$nodeName.isValid == true`
- Correct: `$nodeName.isValid`
- Negation: `not $nodeName.isValid`

## Rules & Whitelist (Critical)
### $ Placement Rules
- A standalone expression usually starts with a leading `$`.
- Template strings can contain multiple `$refs`.
- Method parameters can also contain nested `$refs` when you want to pass another expression result (dynamic key or nested resolution).
  - Valid: `$node.method(other.field)` — `other` is resolved from context like a top-level label (no `$` inside the argument).
  - Valid: `$node.method($other.field)` — nested `$` is supported in the evaluate dialog preview and condition evaluation.
  - Valid: `$array($a.x, $b.y)`
  - Autocomplete inside `.get(` inserts **bare** `label.field` paths (no leading `$`), same as inside `$array(...)` / `$notNull(...)`.
- **Evaluate API (Run):** If the entire submitted value is a single dot path **without** a leading `$` (for example text selected in the editor, like `execute.outputs.output.result.today`), the backend treats it the same as `$execute.outputs.output.result.today`. Values that contain a newline or carriage return after trimming are not rewritten (avoids ambiguous multi-line payloads). Prefer writing `$` in saved workflow fields; the rewrite is mainly for inspection and tooling.
- The Evaluate dialog `Run` result is the source of truth for how a concrete expression resolves.

### Array String Quoting
When creating arrays with string values, ALWAYS use double quotes:
- Correct: `$array("hello", "world")`
- Wrong: `$array('hello', 'world')`

### ONLY USE THESE FUNCTIONS (Whitelist)
Use ONLY:
- `str()`, `int()`, `float()`, `bool()`, `list()`, `dict(key=value, ...)`
- `len()`, `abs()`, `min()`, `max()`, `round()`, `sum()`, `sorted()`
- `randomInt()`, `range()`, `array()`, `notNull()`
- `upper()`, `lower()`, `strip()`, `capitalize()`, `title()`
- `split()`, `join()`, `replace()`, `regexReplace()`, `hash()`
- documented string/array/object methods

If a function is not listed above, it does not exist.

### Arrays / Dicts Method Limits
- Arrays can ONLY use: `.first()`, `.last()`, `.random()`, `.reverse()`, `.flat()`, `.distinct()`, `.distinctBy()`, `.notNull()`, `.add()`, `.contains()`, `.join()`, `.filter()`, `.map()`, `.sort()`, `.take()`, `.length`, `.toString()`
- Objects/Dicts can ONLY use: `.get(key)`, `.get(key, default)`, `.keys()`, `.values()`, `.entries()`, `.filter(expr)`, `.map(expr)`, `.toString()`

### Reserved Node Label Names
Do not use these names as node labels: `length`, `toString`, `toUpperCase`, `toLowerCase`, `substring`, `indexOf`, `contains`, `startsWith`, `endsWith`, `replace`, `replaceAll`, `regexReplace`, `hash`, `first`, `last`, `random`, `reverse`, `distinct`, `notNull`, `filter`, `map`, `entries`, `keys`, `values`, `sort`, `join`, `headers`, `query`, `value`, `list`, `result`, `array`, `vars`, `items`, `name`, `type`, `status`, `body`, `outputs`, `result`, `item`, `index`, `total`, `isFirst`, `isLast`, `branch`, `results`, `merged`, `error`, `errorNode`, `errorNodeType`, `timestamp`, `input`, `now`, `date`.

## Examples

**Condition**: `$input.text.length > 0`

**LLM user message**: `$input.text`

**Output message**: `$llm.text`

**Variable value**: `$input.count + 1`

### DSL Example

```dsl
$input.text
$llm.text
$input.count + 1
item.name
```

## Related

- [Expression Evaluation Dialog](./expression-evaluation-dialog.md) – Expandable editor with backend live preview and autocomplete
- [Canvas Features](./canvas-features.md) – Data pin for testing expressions without re-running nodes
- [Node Types](./node-types.md) – Nodes that use expressions ([LLM](../nodes/llm-node.md), [Condition](../nodes/condition-node.md), [Output](../nodes/output-node.md), [Set](../nodes/set-node.md), etc.)
- [Agent Node](../nodes/agent-node.md) – Using expressions in agent prompts
- [Agent Persistent Memory](./agent-persistent-memory.md) – `persistentMemoryEnabled` and `memoryShares` in agent `data` (not expression fields)
- [Workflow Structure](./workflow-structure.md) – Node `data` fields that accept expressions
- [Credentials Tab](../tabs/credentials-tab.md) – Credentials referenced by nodes
- [Credentials Sharing](./credentials-sharing.md) – Share credentials and use `$credentials` in expressions
- [Global Variables](./global-variables.md) – Persistent variables with `$global`
