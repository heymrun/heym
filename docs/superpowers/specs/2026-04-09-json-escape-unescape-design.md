# JSON Escape/Unescape String Methods - Design Spec

**Status:** ✅ Implemented (2026-04-09)
**Implementation Plan:** [implementation.md](../plans/2026-04-09-json-escape-unescape-implementation.md)

## Summary

Add JSON escape/unescape functionality as string methods in the Heym expression DSL. Users will be able to use `.escape()` and `.unescape()` on string values in expressions for data format transformations.

## Problem Statement

Users need to escape and unescape strings in JSON format within workflow expressions for data format transformations. Currently, there is no built-in method to perform JSON escaping/unescaping in the expression system.

## Requirements

### Functional Requirements

1. **Frontend Expression Preview:**
   - `.escape()` method must JSON-escape string values (e.g., convert `quote"inside` to `"quote\"inside"`)
   - `.unescape()` method must JSON-unescape string values (e.g., convert `"quote\"inside"` to `quote"inside`)

2. **Backend Expression Execution:**
   - `.escape()` method must perform JSON escaping using Python's `json.dumps()`
   - `.unescape()` method must perform JSON unescaping using Python's `json.loads()`

3. **Error Handling:**
   - Frontend: Invalid JSON in `.unescape()` should be caught and handled gracefully
   - Backend: Invalid JSON in `.unescape()` should raise a structured error

4. **Autocomplete:**
   - Both methods must appear in expression autocomplete suggestions
   - Must be categorized as string methods

5. **Documentation:**
   - Update Expression DSL reference with method descriptions and examples

## Design

### Architecture

The implementation follows the existing string method pattern in Heym's expression system:

```
User Expression
    ↓
Type Definitions (STRING_METHODS array)
    ↓
Frontend Preview (executeMethod)
    ↓
Backend Execution (executeMethod)
```

### Components

#### 1. Frontend Type Definitions

**File:** `frontend/src/types/expression.ts`

**Changes:** Add two entries to `STRING_METHODS` array (after existing string methods):

```typescript
{
  label: "escape",
  insertText: "escape()",
  type: "function",
  detail: "JSON escape string",
  propertyType: "string",
},
{
  label: "unescape",
  insertText: "unescape()",
  type: "function",
  detail: "JSON unescape string",
  propertyType: "string",
}
```

**Rationale:** These follow the same pattern as other string methods like `upper()`, `lower()`, etc.

#### 2. Frontend Expression Preview

**File:** `frontend/src/components/ui/ExpressionInput.vue`

**Changes:** Add cases to `executeMethod()` function (within the string case block):

```typescript
case "escape":
  return JSON.stringify(value);
case "unescape":
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    // Return original if invalid JSON
    return value;
  }
```

**Rationale:** Uses built-in `JSON` API for reliability. Error handling prevents crashes.

#### 3. Backend Expression Executor

**File:** `backend/app/services/workflow_executor.py`

**Changes:** Add cases to `executeMethod()` method (within the string type block):

```python
case "escape":
    return json.dumps(value)
case "unescape":
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise WorkflowExecutionError(
            f"Failed to unescape JSON: {str(e)}"
        )
```

**Rationale:** Matches frontend implementation. Uses Python's standard `json` library. Raises structured error for workflow execution context.

### Data Flow

#### Frontend Preview Flow

1. User types `$input.text.escape()` in Expression Input component
2. Autocomplete shows `escape()` as a suggestion
3. User selects/copies suggestion
4. `resolveExpression()` is called for preview
5. `executeMethod()` is invoked with method name `"escape"`
6. `JSON.stringify(value)` returns escaped string
7. Preview displays the result

#### Backend Execution Flow

1. Workflow execution reaches a node with expression containing `.escape()`
2. `resolve_expression()` method processes the expression
3. `executeMethod()` is invoked with method name `"escape"`
4. `json.dumps(value)` returns escaped string
5. Result is passed to next node or returned as output

### Error Handling

#### Frontend Error Handling

**Scenario:** User calls `.unescape()` on invalid JSON string

**Action:**
- Catch `JSON.parse()` error in `try/catch` block
- Return the original string unchanged
- Do not show error to user (preview should fail gracefully)

**Rationale:** Preview is read-only; errors shouldn't block the interface

#### Backend Error Handling

**Scenario:** Runtime execution encounters invalid JSON in `.unescape()`

**Action:**
- Catch `json.JSONDecodeError` exception
- Raise `WorkflowExecutionError` with descriptive message
- Workflow execution stops with error details

**Rationale:** Backend performs actual data processing; errors must be surfaced for debugging

### Testing

#### Backend Unit Tests

**File:** `backend/tests/test_workflow_utils.py`

**Test Cases:**

```python
class TestJsonEscapeUnescape(unittest.IsolatedAsyncioTestCase):
    async def test_escape_string(self):
        """Test basic string escaping"""
        executor = self.create_executor()
        result = executor.executeMethod('quote"inside', 'escape', [])
        self.assertEqual(result, '"quote\\"inside"')

    async def test_escape_unicode(self):
        """Test unicode character escaping"""
        executor = self.create_executor()
        result = executor.executeMethod('hello 世界', 'escape', [])
        # JSON handles unicode as-is
        self.assertEqual(result, '"hello 世界"')

    async def test_unescape_string(self):
        """Test basic string unescaping"""
        executor = self.create_executor()
        result = executor.executeMethod('"quote\\"inside"', 'unescape', [])
        self.assertEqual(result, 'quote"inside')

    async def test_unescape_invalid_json(self):
        """Test error handling for invalid JSON"""
        executor = self.create_executor()
        with self.assertRaises(WorkflowExecutionError):
            executor.executeMethod('not valid json', 'unescape', [])

    async def test_escape_non_string(self):
        """Test escape on non-string types"""
        executor = self.create_executor()
        result = executor.executeMethod(123, 'escape', [])
        self.assertEqual(result, 123)

    async def test_unescape_non_string(self):
        """Test unescape on non-string types"""
        executor = self.create_executor()
        result = executor.executeMethod(123, 'unescape', [])
        self.assertEqual(result, 123)
```

#### Frontend Testing

No frontend tests are added at this time per AGENTS.md guidelines (frontend test infrastructure not yet established).

### Documentation

#### Expression DSL Reference

**File:** `frontend/src/docs/content/reference/expression-dsl.md`

**Additions to String Methods section:**

```markdown
- `.escape()` - JSON escape string (converts special characters to JSON escape sequences)
- `.unescape()` - JSON unescape string (reverts JSON escape sequences to original characters)
```

**Additions to Examples section:**

```markdown
**JSON Escape/Unescape:**
- `$input.text.escape()` → `"quote\"inside"` (escapes quotes)
- `$escaped.unescape()` → `quote"inside` (unescapes quoted string)
- `$data.unescape().upper()` → Chaining with other string methods
```

### Dependencies

- **Backend:** `json` module (Python standard library - no new dependency)
- **Frontend:** `JSON` object (JavaScript built-in - no new dependency)

### Backward Compatibility

This change is fully backward compatible:
- No existing code is modified except for adding cases to switch statements
- New methods are opt-in (users must explicitly call them)
- Existing string methods continue to work as before

## Implementation Timeline

Estimated total time: 2-3 hours

1. **Frontend Type Definitions (15 min)**
   - Update `STRING_METHODS` array in `expression.ts`

2. **Frontend Preview Implementation (30 min)**
   - Update `executeMethod()` in `ExpressionInput.vue`
   - Add error handling for invalid JSON

3. **Backend Implementation (30 min)**
   - Update `executeMethod()` in `workflow_executor.py`
   - Add error handling with structured exceptions

4. **Backend Tests (45 min)**
   - Create test class with 6 test cases
   - Verify all scenarios pass

5. **Documentation Update (15 min)**
   - Update `expression-dsl.md`
   - Add examples

6. **Build & Lint Check (15 min)**
   - Run frontend lint/typecheck
   - Run backend tests + lint

7. **Verification & Demo (30 min)**
   - Test in development environment
   - Verify autocomplete works
   - Verify preview and execution

## Success Criteria

- ✅ Frontend autocomplete shows `.escape()` and `.unescape()` suggestions
- ✅ Frontend preview correctly escapes/unesapes strings
- ✅ Backend execution correctly escapes/unesapes strings
- ✅ Backend raises appropriate error for invalid JSON in `.unescape()`
- ✅ All 6 backend unit tests pass
- ✅ Frontend lint and typecheck pass
- ✅ Backend lint checks pass
- ✅ Documentation updated with examples
- ✅ Expression evaluation in workflow execution works end-to-end

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| JSON escaping behavior differs between frontend/backend | Low | High | Use standard libraries (`json.dumps()` and `JSON.stringify()`) which have identical behavior |
| Users pass non-string values to `.unescape()` | Medium | Low | Check type and return unchanged if not string |
| Complex nested JSON objects are passed as strings | Low | Medium | Only string values are supported; objects should use JSON methods directly |

## Future Considerations

- If demand for other escape formats arises (HTML, URL), they can be added using the same pattern
- Consider adding `.escapeJSON()` alias for clarity (though `.escape()` is more concise in existing pattern)