# Context Compression Comparison Table Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Automatic context compression" row to all comparison tables to highlight it as a unique Heym advantage.

**Architecture:** Documentation-only changes - update 3 markdown comparison tables with a new row showing Heym's context compression capability vs competitors.

**Tech Stack:** Markdown, Git

---

## File Structure

**Files to modify:**
1. `heymrun/README.md` - Main comparison table (line 107-125)
2. `heymrun/frontend/src/docs/content/getting-started/why-heym.md` - Why Heym table (line 7-22)
3. `heymweb/.claude/memory/research/competitor-analysis/2026-04-07-ai-workflow-automation.md` - Competitor snapshot table

**No files created** - all modifications to existing tables.

---

### Task 1: Update Main README Comparison Table

**Files:**
- Modify: `heymrun/README.md:113`

- [ ] **Step 1: Read the README comparison table section**

```bash
cd heymrun && sed -n '107,125p' README.md
```

Expected output: Shows current table with rows 107-125

- [ ] **Step 2: Add context compression row after LLM Guardrails**

The new row to insert:
```markdown
| Automatic context compression | ✅ (80% threshold, preserves system/first/last messages) | ❌ | ❌ | ❌ |
```

This goes after line 113 (the LLM Guardrails row).

Use sed to insert:
```bash
cd heymrun && sed -i.bak '113a\
| Automatic context compression | ✅ (80% threshold, preserves system/first/last messages) | ❌ | ❌ | ❌ |\
' README.md
```

- [ ] **Step 3: Verify the row was added correctly**

```bash
cd heymrun && sed -n '107,126p' README.md
```

Expected: Table now has 19 rows (was 18) and the new row appears between LLM Guardrails and Built-in RAG

- [ ] **Step 4: Commit README changes**

```bash
cd heymrun && git add README.md && git commit -m "docs: add context compression to Why Heym comparison table"
```

---

### Task 2: Update Why Heym Comparison Table

**Files:**
- Modify: `heymrun/frontend/src/docs/content/getting-started/why-heym.md:19`

- [ ] **Step 1: Read the why-heym comparison table section**

```bash
cd heymrun && sed -n '7,22p' frontend/src/docs/content/getting-started/why-heym.md
```

Expected output: Shows current table with rows 7-22

- [ ] **Step 2: Add context compression row after LLM guardrails**

The new row to insert:
```markdown
| Automatic context compression | ✓ (80% threshold, preserves system/first/last messages) | – | – | – |
```

This goes after line 19 (the LLM guardrails row).

Use sed to insert:
```bash
cd heymrun && sed -i.bak '19a\
| Automatic context compression | ✓ (80% threshold, preserves system/first/last messages) | – | – | – |\
' frontend/src/docs/content/getting-started/why-heym.md
```

- [ ] **Step 3: Verify the row was added correctly**

```bash
cd heymrun && sed -n '7,23p' frontend/src/docs/content/getting-started/why-heym.md
```

Expected: Table now has 23 rows (was 22) and the new row appears between LLM guardrails and Parallel DAG execution

- [ ] **Step 4: Commit why-heym changes**

```bash
cd heymrun && git add frontend/src/docs/content/getting-started/why-heym.md && git commit -m "docs: add context compression to why-heym comparison table"
```

---

### Task 3: Update Competitor Analysis Table

**Files:**
- Modify: `heymweb/.claude/memory/research/competitor-analysis/2026-04-07-ai-workflow-automation.md:15-22`

- [ ] **Step 1: Read the competitor snapshot table**

```bash
cd heymweb && sed -n '15,23p' .claude/memory/research/competitor-analysis/2026-04-07-ai-workflow-automation.md
```

Expected output: Shows current table with feature rows

- [ ] **Step 2: Add context compression row after AI-native row**

The new row to insert:
```markdown
| Context compression | ✅ | ❌ | ❌ | ❌ |
```

Insert after line 16 (the AI-native row) using sed:
```bash
cd heymweb && sed -i.bak '16a\
| Context compression | ✅ | ❌ | ❌ | ❌ |\
' .claude/memory/research/competitor-analysis/2026-04-07-ai-workflow-automation.md
```

- [ ] **Step 3: Verify the row was added correctly**

```bash
cd heymweb && sed -n '15,24p' .claude/memory/research/competitor-analysis/2026-04-07-ai-workflow-automation.md
```

Expected: Table now has context compression row between AI-native and Multi-agent rows

- [ ] **Step 4: Commit competitor analysis changes**

```bash
cd heymweb && git add .claude/memory/research/competitor-analysis/2026-04-07-ai-workflow-automation.md && git commit -m "docs: add context compression to competitor analysis table"
```

---

### Task 4: Verify All Tables Are Correct

**Files:**
- Read: `heymrun/README.md`
- Read: `heymrun/frontend/src/docs/content/getting-started/why-heym.md`
- Read: `heymweb/.claude/memory/research/competitor-analysis/2026-04-07-ai-workflow-automation.md`

- [ ] **Step 1: Verify README table has 19 rows**

```bash
cd heymrun && awk '/^| Capability/,/^[| ]*$/' README.md | grep -c '^|'
```

Expected: 20 (1 header + 19 feature rows)

- [ ] **Step 2: Verify why-heym table has 23 rows**

```bash
cd heymrun && awk '/^| Capability/,/^[| ]*$/' frontend/src/docs/content/getting-started/why-heym.md | grep -c '^|'
```

Expected: 24 (1 header + 23 feature rows)

- [ ] **Step 3: Verify competitor table includes context compression**

```bash
cd heymweb && grep -A 5 "| | Heym" .claude/memory/research/competitor-analysis/2026-04-07-ai-workflow-automation.md | grep "Context compression"
```

Expected: Shows the context compression row

- [ ] **Step 4: Check table formatting is consistent**

```bash
cd heymrun && cat frontend/src/docs/content/getting-started/why-heym.md | grep -A 2 "Automatic context compression"
```

Expected: Row should be properly formatted with pipes aligned

- [ ] **Step 5: Visual check of all tables**

```bash
cd heymrun && echo "=== README Table ===" && sed -n '107,126p' README.md
echo ""
echo "=== Why Heym Table ===" && sed -n '7,23p' frontend/src/docs/content/getting-started/why-heym.md
echo ""
echo "=== Competitor Analysis ===" && cd heymweb && sed -n '15,23p' .claude/memory/research/competitor-analysis/2026-04-07-ai-workflow-automation.md
```

Expected: All tables show context compression row with correct formatting

---

### Task 5: Test in Browser (Optional Verification)

**Files:**
- Test: No files - manual browser verification

- [ ] **Step 1: Start frontend development server**

```bash
cd heymrun/frontend && bun run dev
```

Expected: Server starts on port 4017

- [ ] **Step 2: Open Why Heym documentation page**

Navigate to: `http://localhost:4017/docs/getting-started/why-heym`

Expected: Page loads and comparison table displays correctly

- [ ] **Step 3: Verify table renders correctly**

Check that:
- Context compression row appears in the table
- Check marks and dashes display properly
- Table columns align correctly
- No markdown rendering errors

- [ ] **Step 4: Stop development server**

Press Ctrl+C in the terminal where the dev server is running

---

## Self-Review Checklist

**1. Spec coverage:**
- ✅ Main README table updated (Task 1)
- ✅ Why Heym table updated (Task 2)
- ✅ Competitor analysis updated (Task 3)
- ✅ Website covered (already had it, no action needed)
- ✅ All tables use consistent cell formatting
- ✅ Heym cells show technical details (80% threshold, preservation strategy)
- ✅ Competitor cells clearly indicate absence

**2. Placeholder scan:**
- ✅ No "TBD" or "TODO" in steps
- ✅ All code snippets complete
- ✅ All commands exact with expected output
- ✅ No "add appropriate" or "handle edge cases"

**3. Type consistency:**
- ✅ Table syntax consistent across files (markdown pipes)
- ✅ Cell values: README uses ✅/❌, why-heym uses ✓/– (matching existing patterns)
- ✅ Competitor analysis uses table format matching existing rows