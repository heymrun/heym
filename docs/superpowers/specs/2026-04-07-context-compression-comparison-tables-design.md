# Context Compression Comparison Table Updates - Design Spec

**Date:** 2026-04-07
**Status:** Approved
**Goal:** Highlight automatic context compression as a unique Heym advantage in all comparison tables

---

## Overview

Add "Automatic context compression" as a new row to all comparison tables across Heym documentation and website. This feature is a key differentiator that Heym has but competitors (n8n, Zapier, Make.com, Flowise, Langflow) lack.

---

## Research Findings

### Competitor Status

| Platform | Context Compression | Details |
|----------|---------------------|---------|
| **Heym** | ✅ | Automatic at 80% threshold, preserves system/first/last messages |
| **n8n** | ❌ | No automatic context compression in LLM/agent nodes |
| **Zapier** | ❌ | No automatic context compression in AI features |
| **Make.com** | ❌ | No automatic context compression in agent nodes |
| **Flowise** | ❌ | No automatic context compression mentioned |
| **Langflow** | ❌ | No automatic context compression mentioned |

### Heym Implementation Details

- **Trigger:** When accumulated message history reaches 80% of model's context window
- **Preservation:** System prompt, first user message, and most recent user message always preserved
- **Compression:** Everything in between is summarized using the same model and credential
- **Visibility:** Compression events appear in Debug panel, Execution History, and Traces tab
- **Technical Docs:** `/Users/mbakgun/Projects/heym/heymrun/frontend/src/docs/content/nodes/agent-node.md:192-209`

---

## Implementation Specification

### New Row Content

```
| Automatic context compression | ✓ (80% threshold, preserves system/first/last messages) | – | – | – |
```

### Files to Update

#### 1. Main README (`heymrun/README.md`)

- **Location:** Line 107-125 (Why Heym comparison table)
- **Insert After:** "LLM Guardrails" row (line 113)
- **Change:** 18 rows → 19 rows

**Before:**
```markdown
| LLM Guardrails | ✅ | ✅⁸ | ✅⁸ | limited⁸ |
| Built-in RAG / vector store | ✅ | ✅ | limited¹ | plugin² |
```

**After:**
```markdown
| LLM Guardrails | ✅ | ✅⁸ | ✅⁸ | limited⁸ |
| Automatic context compression | ✅ (80% threshold, preserves system/first/last messages) | ❌ | ❌ | ❌ |
| Built-in RAG / vector store | ✅ | ✅ | limited¹ | plugin² |
```

#### 2. Why Heym Documentation (`heymrun/frontend/src/docs/content/getting-started/why-heym.md`)

- **Location:** Line 7-22 (AI-Native vs AI as an Add-On table)
- **Insert After:** "LLM guardrails" row (line 19)
- **Change:** 22 rows → 23 rows

**Before:**
```markdown
| LLM guardrails | ✓ | ✓⁸ | ✓⁸ | limited⁸ |
| Parallel DAG execution | ✓ | limited⁹ | – | – |
```

**After:**
```markdown
| LLM guardrails | ✓ | ✓⁸ | ✓⁸ | limited⁸ |
| Automatic context compression | ✓ (80% threshold, preserves system/first/last messages) | – | – | – |
| Parallel DAG execution | ✓ | limited⁹ | – | – |
```

#### 3. Competitor Analysis (`heymweb/.claude/memory/research/competitor-analysis/2026-04-07-ai-workflow-automation.md`)

- **Location:** Line 15-22 (Competitor Snapshot table)
- **Add Row:** Context compression row
- **Change:** +1 row

**Before:**
```markdown
| | Heym | n8n | Flowise | Zapier |
|---|------|-----|---------|--------|
| AI-native | ✅ | ⚠️ | ⚠️ | ❌ |
| Multi-agent | ✅ | ❌ | ⚠️ | ❌ |
```

**After:**
```markdown
| | Heym | n8n | Flowise | Zapier |
|---|------|-----|---------|--------|
| AI-native | ✅ | ⚠️ | ⚠️ | ❌ |
| Context compression | ✅ | ❌ | ❌ | ❌ |
| Multi-agent | ✅ | ❌ | ⚠️ | ❌ |
```

#### 4. Website Homepage (`heymweb/src/app/page.tsx`)

- **Status:** Already covered
- **Evidence:** Lines 67, 103 already mention context compression in SEO text
- **Action Needed:** None

---

## Design Rationale

### Why This Feature?

Context compression is a **critical production feature** for AI agents that:
- Run long conversations with many tool iterations
- Process large documents or web scraping results
- Execute multi-step workflows with accumulated context

Without automatic compression, agents hit context limits and fail mid-execution. Users must either:
1. Manually truncate context (error-prone, loses information)
2. Implement custom compression logic (requires engineering work)
3. Accept agent failures (unacceptable for production)

### Why As Table Row?

**Clarity:** Rows provide instant feature-by-feature comparison
**Scannability:** Users can quickly identify unique Heym advantages
**Consistency:** Matches existing pattern for other features (skills, RAG, etc.)
**SEO Benefit:** Clear differentiation signals for search engines

### Placement Strategy

Placing after "LLM Guardrails" makes sense because it groups:
1. **Agent capabilities** (LLM, tools, orchestration)
2. **Safety features** (guardrails)
3. **Context management** (compression)

This flows logically from "what agents do" → "how we keep them safe" → "how we keep them efficient".

---

## Testing Checklist

- [ ] Verify README table has correct row count (19 rows)
- [ ] Verify why-heym.md table has correct row count (23 rows)
- [ ] Verify competitor analysis includes context compression row
- [ ] Check all "–" cells are consistent in all tables
- [ ] Validate that Heym cell has complete technical details
- [ ] Ensure all markdown tables render correctly
- [ ] No broken table formatting or alignment issues

---

## Success Criteria

1. ✅ All comparison tables include context compression row
2. ✅ Heym implementation details are accurate and specific
3. ✅ Competitor cells clearly indicate absence
4. ✅ Table formatting is consistent across all files
5. ✅ Content highlights this as a unique Heym advantage

---

## Reference Links

- **Agent Node Context Compression Docs:** `/Users/mbakgun/Projects/heym/heymrun/frontend/src/docs/content/nodes/agent-node.md:192-209`
- **Context Compression Implementation:** `/Users/mbakgun/Projects/heym/heymrun/docs/superpower/specs/2026-04-07-agent-context-compression-design.md`
- **LLM Service Implementation:** `/Users/mbakgun/Projects/heym/heymrun/backend/app/services/llm_service.py:660-690`