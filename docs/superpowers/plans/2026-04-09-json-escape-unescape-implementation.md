# JSON Escape/Unescape String Methods Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `.escape()` and `.unescape()` string methods to the Heym expression DSL for JSON escaping/unescaping in workflow expressions.

**Architecture:** Extend existing string method pattern by adding type definitions to STRING_METHODS array and implementing escape/unespace logic in both frontend preview and backend execution using standard JSON libraries.

**Tech Stack:** TypeScript (Vue.js), Python 3.11+, pytest, json/JSON standard libraries

---

### Task 1: Frontend Type Definitions - Add String Methods to Autocomplete

**Files:**
- Modify: `frontend/src/types/expression.ts` (add to STRING_METHODS array after line 710)

- [ ] **Step 1: Add escape method to STRING_METHODS array**

Locate the `STRING_METHODS` array definition (around line 570). After the `urlDecode` method entry (around line 705), add the escape method:

```typescript
{
  label: "escape",
  insertText: "escape()",
  type: "function",
  detail: "JSON escape string",
  propertyType: "string",
},
```

- [ ] **Step 2: Add unescape method to STRING_METHODS array**

Immediately after the escape method entry, add the unescape method:

```typescript
{
  label: "unescape",
  insertText: "unescape()",
  type: "function",
  detail: "JSON unescape string",
  propertyType: "string",
},
```

- [ ] **Step 3: Verify syntax with frontend typecheck**

Run:
```bash
cd frontend && bun run typecheck
```
Expected: PASS (no type errors)

- [ ] **Step 4: Commit type definitions**

```bash
git add frontend/src/types/expression.ts
git commit -m "feat: add escape/unescape string methods to autocomplete"
```

---

### Task 2: Frontend Expression Preview - Escape Implementation

**Files:**
- Modify: `frontend/src/components/ui/ExpressionInput.vue` (add case to executeMethod function)

- [ ] **Step 1: Locate executeMethod function for string type**

Find the `executeMethod()` function (around line 1725). Locate the string type switch statement. Find the case for "upper" (around line 1732) as a reference point.

- [ ] **Step 2: Add escape case to string switch statement**

After the existing string method cases (before the closing brace of the string case block, around line 1850), add the escape case:

```typescript
case "escape":
  return JSON.stringify(value);
```

- [ ] **Step 3: Verify syntax with frontend lint**

Run:
```bash
cd frontend && bun run lint
```
Expected: PASS (no lint errors)

- [ ] **Step 4: Commit escape implementation**

```bash
git add frontend/src/components/ui/ExpressionInput.vue
git commit -m "feat: implement escape() method in frontend preview"
```

---

### Task 3: Frontend Expression Preview - Unescape Implementation

**Files:**
- Modify: `frontend/src/components/ui/ExpressionInput.vue` (add case to executeMethod function)

- [ ] **Step 1: Add unescape case to string switch statement**

Immediately after the escape case you just added, add the unescape case with error handling:

```typescript
case "unescape":
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
```

- [ ] **Step 2: Verify syntax with frontend lint**

Run:
```bash
cd frontend && bun run lint
```
Expected: PASS

- [ ] **Step 3: Commit unescape implementation**

```bash
git add frontend/src/components/ui/ExpressionInput.vue
git commit -m "feat: implement unescape() method with error handling"
```

---

### Task 4: Backend Expression Executor - Escape Implementation

**Files:**
- Modify: `backend/app/services/workflow_executor.py` (add case to executeMethod method)

- [ ] **Step 1: Locate executeMethod method for string type**

Find the `executeMethod()` method (around line 3729). Locate the string case (use `match value:` to find string type handling). Find the case for "upper" or similar string method as reference.

- [ ] **Step 2: Add escape case to string match statement**

After the existing string method cases (before the closing of the string case block), add the escape case. Note: This uses Python's `match` statement (not switch):

```python
case "escape":
    return json.dumps(value)
```

- [ ] **Step 3: Verify Python syntax with backend lint**

Run:
```bash
cd backend && uv run ruff check .
```
Expected: PASS (no lint errors)

- [ ] **Step 4: Commit escape implementation**

```bash
git add backend/app/services/workflow_executor.py
git commit -m "feat: implement escape() method in backend executor"
```

---

### Task 5: Backend Expression Executor - Unescape Implementation

**Files:**
- Modify: `backend/app/services/workflow_executor.py` (add case to executeMethod method)

- [ ] **Step 1: Import WorkflowExecutionError if not already present**

Check if `WorkflowExecutionError` is imported at the top of the file. If not, add it to the imports section (around line 1-50):

```python
from app.utils.exceptions import WorkflowExecutionError
```

- [ ] **Step 2: Add unescape case to string match statement**

Immediately after the escape case you just added, add the unescape case with proper error handling:

```python
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

- [ ] **Step 3: Verify Python syntax with backend lint**

Run:
```bash
cd backend && uv run ruff check .
```
Expected: PASS

- [ ] **Step 4: Commit unescape implementation**

```bash
git add backend/app/services/workflow_executor.py
git commit -m "feat: implement unescape() method with structured error handling"
```

---

### Task 6: Backend Test - Test Escape String

**Files:**
- Modify: `backend/tests/test_workflow_utils.py`

- [ ] **Step 1: Create test class for escape/unescape**

Find the end of the existing test classes in `test_workflow_utils.py` (around line 200-250). Add a new test class:

```python
class TestJsonEscapeUnescape(unittest.IsolatedAsyncioTestCase):
    """Test JSON escape and unescape string methods"""

    async def test_escape_string(self):
        """Test basic string escaping"""
        # Create a simple executor instance for testing
        from app.services.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor(
            nodes={},
            edges=[],
            workflow_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
        )
        result = executor.executeMethod('quote"inside', 'escape', [])
        self.assertEqual(result, '"quote\\"inside"')

    async def test_escape_unicode(self):
        """Test unicode character escaping"""
        from app.services.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor(
            nodes={},
            edges=[],
            workflow_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
        )
        result = executor.executeMethod('hello 世界', 'escape', [])
        # JSON handles unicode as-is
        self.assertEqual(result, '"hello 世界"')
```

- [ ] **Step 2: Run test to verify it passes**

Run:
```bash
cd backend && uv run pytest tests/test_workflow_utils.py::TestJsonEscapeUnescape::test_escape_string -v
cd backend && uv run pytest tests/test_workflow_utils.py::TestJsonEscapeUnescape::test_escape_unicode -v
```
Expected: PASS for both tests

- [ ] **Step 3: Commit escape tests**

```bash
git add backend/tests/test_workflow_utils.py
git commit -m "test: add escape() method unit tests"
```

---

### Task 7: Backend Test - Test Unescape String

**Files:**
- Modify: `backend/tests/test_workflow_utils.py`

- [ ] **Step 1: Add unescape test to TestJsonEscapeUnescape class**

Add these test methods to the `TestJsonEscapeUnescape` class you created in Task 6:

```python
async def test_unescape_string(self):
    """Test basic string unescaping"""
    from app.services.workflow_executor import WorkflowExecutor

    executor = WorkflowExecutor(
        nodes={},
        edges=[],
        workflow_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )
    result = executor.executeMethod('"quote\\"inside"', 'unescape', [])
    self.assertEqual(result, 'quote"inside')
```

- [ ] **Step 2: Run test to verify it passes**

Run:
```bash
cd backend && uv run pytest tests/test_workflow_utils.py::TestJsonEscapeUnescape::test_unescape_string -v
```
Expected: PASS

- [ ] **Step 3: Commit unescape test**

```bash
git add backend/tests/test_workflow_utils.py
git commit -m "test: add unescape() method unit test"
```

---

### Task 8: Backend Test - Test Error Handling

**Files:**
- Modify: `backend/tests/test_workflow_utils.py`

- [ ] **Step 1: Add error handling tests to TestJsonEscapeUnescape class**

Add these test methods to the `TestJsonEscapeUnescape` class:

```python
async def test_unescape_invalid_json(self):
    """Test error handling for invalid JSON"""
    from app.services.workflow_executor import WorkflowExecutor
    from app.utils.exceptions import WorkflowExecutionError

    executor = WorkflowExecutor(
        nodes={},
        edges=[],
        workflow_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )
    with self.assertRaises(WorkflowExecutionError) as context:
        executor.executeMethod('not valid json', 'unescape', [])
    self.assertIn("Failed to unescape JSON", str(context.exception))
```

- [ ] **Step 2: Run test to verify it passes**

Run:
```bash
cd backend && uv run pytest tests/test_workflow_utils.py::TestJsonEscapeUnescape::test_unescape_invalid_json -v
```
Expected: PASS

- [ ] **Step 3: Commit error handling tests**

```bash
git add backend/tests/test_workflow_utils.py
git commit -m "test: add escape/unescape error handling tests"
```

---

### Task 9: Backend Test - Test Non-String Values

**Files:**
- Modify: `backend/tests/test_workflow_utils.py`

- [ ] **Step 1: Add non-string type tests to TestJsonEscapeUnescape class**

Add these test methods to the `TestJsonEscapeUnescape` class:

```python
async def test_escape_non_string(self):
    """Test escape on non-string types"""
    from app.services.workflow_executor import WorkflowExecutor

    executor = WorkflowExecutor(
        nodes={},
        edges=[],
        workflow_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )
    result = executor.executeMethod(123, 'escape', [])
    self.assertEqual(result, 123)

    result = executor.executeMethod(None, 'escape', [])
    self.assertEqual(result, None)

async def test_unescape_non_string(self):
    """Test unescape on non-string types"""
    from app.services.workflow_executor import WorkflowExecutor

    executor = WorkflowExecutor(
        nodes={},
        edges=[],
        workflow_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )
    result = executor.executeMethod(123, 'unescape', [])
    self.assertEqual(result, 123)

    result = executor.executeMethod(None, 'unescape', [])
    self.assertEqual(result, None)
```

- [ ] **Step 2: Run all escape/unescape tests**

Run:
```bash
cd backend && uv run pytest tests/test_workflow_utils.py::TestJsonEscapeUnescape -v
```
Expected: PASS for all tests (6 total tests now)

- [ ] **Step 3: Commit all tests**

```bash
git add backend/tests/test_workflow_utils.py
git commit -m "test: complete escape/unescape test coverage"
```

- [ ] **Step 4: Run full backend test suite**

Run:
```bash
cd backend && uv run pytest tests/ -v
```
Expected: PASS for all tests (no regressions)

---

### Task 10: Documentation Update - Expression DSL Reference

**Files:**
- Modify: `frontend/src/docs/content/reference/expression-dsl.md`

- [ ] **Step 1: Locate String Methods section**

Find the "String Methods (on string values)" section in the markdown file (around line 178).

- [ ] **Step 2: Add escape/unescape to String Methods section**

Find the end of the list of string methods (after `.urlDecode()` around line 193). Add the two new methods:

```markdown
- `.escape()` - JSON escape string (converts special characters to JSON escape sequences)
- `.unescape()` - JSON unescape string (reverts JSON escape sequences to original characters)
```

- [ ] **Step 3: Locate Examples section**

Find the "Examples" section (around line 278).

- [ ] **Step 4: Add escape/unescape examples to Examples section**

Find the end of the examples and add a new subsection before "### DSL Example":

```markdown
**JSON Escape/Unescape:**
- `$input.text.escape()` → `"quote\"inside"` (escapes quotes)
- `$escaped.unescape()` → `quote"inside` (unescapes quoted string)
- `$data.unescape().upper()` → Chaining with other string methods

```

- [ ] **Step 5: Commit documentation updates**

```bash
git add frontend/src/docs/content/reference/expression-dsl.md
git commit -m "docs: add escape/unescape methods to expression DSL reference"
```

---

### Task 11: Comprehensive Build & Lint Checks

**Files:** No file modifications, verification tasks

- [ ] **Step 1: Frontend typecheck**

Run:
```bash
cd frontend && bun run typecheck
```
Expected: PASS

- [ ] **Step 2: Frontend lint**

Run:
```bash
cd frontend && bun run lint
```
Expected: PASS

- [ ] **Step 3: Backend lint**

Run:
```bash
cd backend && uv run ruff check .
```
Expected: PASS

- [ ] **Step 4: Backend format check**

Run:
```bash
cd backend && uv run ruff format --check .
```
Expected: PASS

- [ ] **Step 5: Format backend code if needed**

If Step 4 failed, run:
```bash
cd backend && uv run ruff format .
git add -A
git commit -m "style: auto-format backend code"
```

- [ ] **Step 6: Run all backend tests**

Run:
```bash
cd backend && uv run pytest tests/ -v
```
Expected: PASS for all tests

- [ ] **Step 7: Run specific escape/unescape tests**

Run:
```bash
cd backend && uv run pytest tests/test_workflow_utils.py::TestJsonEscapeUnescape -v
```
Expected: PASS for all 6 tests

- [ ] **Step 8: Commit build verification success**

```bash
git commit --allow-empty -m "chore: all build checks passed for escape/unescape feature"
```

---

### Task 12: Verification & Optional Demo in Development

**Files:** No file modifications, manual verification

- [ ] **Step 1: Start development environment**

Run:
```bash
./run.sh
```
Wait for all services (postgres, backend, frontend) to start successfully.

- [ ] **Step 2: Test autocomplete in browser**

1. Open browser to `http://localhost:4017`
2. Create a new workflow or open existing one
3. Add any node with expression input (e.g., Set node, Output node)
4. Click on expression input field
5. Type a string reference like `$input.text.`
6. Verify autocomplete shows `.escape()` in suggestions
7. Verify autocomplete shows `.unescape()` in suggestions

- [ ] **Step 3: Test frontend preview**

1. In expression input dialog, type `$input.text.escape()`
2. Verify preview shows properly escaped string (with quotes around it)
3. Type `$escaped.unescape()`
4. Verify preview shows unescaped string (without quotes)
5. Type invalid JSON and call `.unescape()`
6. Verify preview shows original string (graceful failure)

- [ ] **Step 4: Test backend execution (optional integration test)**

1. Create a simple workflow with:
   - Input node with text value
   - Set node with expression `$input.text.escape()`
   - Output node with output expression from Set node
2. Run the workflow
3. Verify output shows escaped JSON string
4. Test with unescape as well
5. Verify execution completes successfully

- [ ] **Step 5: Verify no console errors**

1. Open browser developer console
2. Check for no JavaScript errors
3. Check backend logs for no Python errors

- [ ] **Step 6: Document any issues found (if any)**

If any verification steps failed:
1. Document the specific failure
2. Identify which task needs to be revisited
3. Create bug fix tasks as needed

- [ ] **Step 7: Final commit verification changes (if any)**

If you made any bug fixes during verification:
```bash
git add -A
git commit -m "fix: resolve verification issues found during testing"
```

---

### Task 13: Design Spec Handoff - Update Implementation Status

**Files:**
- Modify: `docs/superpowers/specs/2026-04-09-json-escape-unescape-design.md`

- [ ] **Step 1: Add implementation status to design spec**

At the end of the design spec (after the "Future Considerations" section), add:

```markdown
## Implementation Status

- ✅ Spec: 2026-04-09
- ✅ Implementation: 2026-04-09
- ✅ Tests: All 6 backend unit tests passing
- ✅ Documentation: Updated expression-dsl.md
- ✅ Verification: Manual verification completed
```

- [ ] **Step 2: Commit design spec update**

```bash
git add docs/superpowers/specs/2026-04-09-json-escape-unescape-design.md
git commit -m "docs: mark JSON escape/unescape as implemented"
```

---

## Self-Review Checklist

After completing all tasks, verify:

- [ ] All 13 tasks completed
- [ ] Frontend type definitions (STRING_METHODS) updated
- [ ] Frontend preview implementation (escape + unescape) with error handling
- [ ] Backend executor implementation (escape + unescape) with structured errors
- [ ] All 6 backend unit tests pass
- [ ] Documentation updated in expression-dsl.md
- [ ] Frontend typecheck passes
- [ ] Frontend lint passes
- [ ] Backend lint passes
- [ ] Backend format passes
- [ ] All backend tests pass
- [ ] Manual verification completed (autocomplete, preview, execution)
- [ ] Design spec marked as implemented
- [ ] All commits have descriptive messages
- [ ] No placeholder code or TBD comments remain
- [ ] No console errors in browser
- [ ] No errors in backend logs

---

## Success Criteria Verification

After implementation completion, verify all success criteria from the design spec:

- ✅ Frontend autocomplete shows `.escape()` and `.unescape()` suggestions (Task 1, 12)
- ✅ Frontend preview correctly escapes/unesapes strings (Task 2-3, 12)
- ✅ Backend execution correctly escapes/unesapes strings (Task 4-5, 12)
- ✅ Backend raises appropriate error for invalid JSON in `.unescape()` (Task 5, 8)
- ✅ All 6 backend unit tests pass (Task 6-9, 11)
- ✅ Frontend lint and typecheck pass (Task 11)
- ✅ Backend lint checks pass (Task 11)
- ✅ Documentation updated with examples (Task 10)
- ✅ Expression evaluation in workflow execution works end-to-end (Task 12)