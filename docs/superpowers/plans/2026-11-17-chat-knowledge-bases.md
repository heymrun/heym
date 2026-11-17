# Knowledge Bases in Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The dashboard chat engine (Chat tab, Heym Work Chat, MCP `heym_chat`, A2A) lists the user's knowledge bases and their documents, and searches them before running a workflow when a knowledge base covers an information question.

**Architecture:** A new chat tool module `backend/app/api/chat_knowledge_bases.py`, shaped like `chat_data_tables.py`, exposes `list_knowledge_bases` and `search_knowledge_base`. Listing reads `vector_store_access_rows` (Heym Work's helper); documents and search call the `app.api.vector_stores` route functions, the same endpoints Heym Work uses. A per-turn prompt block lists the knowledge bases next to the workflow list, and a prompt section makes information questions knowledge-first.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, unittest + AsyncMock, real-PostgreSQL tests via `tests/board_pg_support.py`.

Spec: `docs/superpowers/specs/2026-11-17-chat-knowledge-bases-design.md`.

---

## File map

- Create `backend/app/api/chat_knowledge_bases.py`: tool schemas, argument models, list/documents/search, prompt block and prompt rules, labels and summaries.
- Modify `backend/app/api/ai_assistant.py`: import, add schemas to `DASHBOARD_CHAT_TOOLS`, dispatch branch in `stream_dashboard_chat`, summary in `_summarize_tool_result`, prompt wording (knowledge-first, capability list), append `KNOWLEDGE_BASE_PROMPT`, add the block in `dashboard_chat_stream`, count it in `_emit_context`.
- Modify `backend/app/api/chats.py`: `SystemPromptParts.knowledge_bases_block`, add the block in `_assemble_system_prompt_parts`, count it in the context summary.
- Modify `backend/app/api/vector_stores.py`: run `service.list_items` in a thread.
- Modify `backend/app/services/heym_agent/profile.py`: capability text and a `knowledge-bases` skill.
- Create `backend/tests/test_chat_knowledge_bases.py` (unit) and `backend/tests/test_chat_knowledge_bases_postgres.py` (access on real PostgreSQL).
- Docs: `frontend/src/docs/content/tabs/chat-tab.md`, `tabs/mcp-tab.md`, `reference/a2a.md`, `reference/chat-with-heym.md`, `reference/features.md`, and the vector store tab page.

---

### Task 1: Tool module with failing unit tests first

**Files:**
- Create: `backend/tests/test_chat_knowledge_bases.py`
- Create: `backend/app/api/chat_knowledge_bases.py`

- [ ] **Step 1: Write the failing unit tests**

Tests cover: listing maps rows and calls `vector_store_access_rows(user.id)`; the prompt block format, 50 cap, description cut, newline flattening and empty case; documents from the items route with the workflow-chunk `source: null` and the 200 cap; an unreachable id errors without calling the route; search calls the route per id with query and limit, keeps order, dedupes ids, reports partial failures under `errors`, sets a top-level `error` only when every store failed; chunk text cut at 1,500 characters; metadata keeps at most 10 scalar keys; invalid arguments error; summaries carry counts only.

(Full test code is in the committed test file.)

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_chat_knowledge_bases.py -q`
Expected: collection error, `chat_knowledge_bases` does not exist.

- [ ] **Step 3: Implement the module**

Public surface:

```python
LIST_TOOL = "list_knowledge_bases"
SEARCH_TOOL = "search_knowledge_base"
KNOWLEDGE_BASE_TOOL_NAMES: frozenset[str]
KNOWLEDGE_BASE_TOOL_SCHEMAS: list[dict[str, Any]]
KNOWLEDGE_BASE_PROMPT: str

@dataclass(frozen=True)
class KnowledgeBase:
    id: uuid.UUID
    name: str
    description: str | None
    access: str  # "owner" or "shared"
    updated_at: datetime | None
    def to_dict(self) -> dict[str, Any]: ...

async def list_accessible_knowledge_bases(
    db: AsyncSession, user_id: uuid.UUID, ids: Sequence[uuid.UUID] | None = None
) -> list[KnowledgeBase]: ...
def format_knowledge_bases_for_prompt(bases: Sequence[KnowledgeBase]) -> str: ...
async def knowledge_bases_prompt_block(db: AsyncSession, user_id: uuid.UUID) -> str: ...
async def call_knowledge_base_tool(
    db: AsyncSession, user: User, name: str, arguments: dict[str, Any]
) -> dict[str, Any]: ...
def knowledge_base_tool_label(name: str) -> str: ...
def summarize_knowledge_base_tool(name: str, result: dict[str, Any]) -> str: ...
```

Behavior:
- Listing: `select(VectorStore.id, name, description, updated_at, access.c.grant).join(vector_store_access_rows(user_id).subquery())`, ordered by `lower(name)`, then id; `ids` adds `VectorStore.id.in_(ids)`.
- Documents: resolve the store through the listing (unknown → `{"error": "Knowledge base not found"}`), then `vector_stores.list_vector_store_items(id, limit=1000, text_truncate_length=0, current_user=user, db=db)`.
- Search: resolve names through the listing, then for each unique id in order call `vector_stores.search_vector_store(id, VectorStoreSearchRequest(query=..., limit=...), current_user=user, db=db)`; `HTTPException` → entry in `errors`.
- No top-level `status` key anywhere: the chat reads it as the tool's own outcome.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_chat_knowledge_bases.py -q`
Expected: all pass.

### Task 2: Wire the tools into the chat engine

**Files:**
- Modify: `backend/app/api/ai_assistant.py`
- Test: `backend/tests/test_chat_knowledge_bases.py`

- [ ] **Step 1: Add failing wiring tests**

```python
class ChatWiringTests(unittest.TestCase):
    def test_tools_are_offered_to_every_dashboard_chat_turn(self) -> None:
        names = {tool["function"]["name"] for tool in ai_assistant.DASHBOARD_CHAT_TOOLS}
        self.assertLessEqual(chat.KNOWLEDGE_BASE_TOOL_NAMES, names)

    def test_prompt_makes_information_questions_knowledge_first(self) -> None:
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT
        self.assertIn(chat.KNOWLEDGE_BASE_PROMPT, prompt)
        self.assertIn("search_knowledge_base", prompt.split("CRITICAL - Workflow-first")[1][:600])
        self.assertIn("search what is in them", prompt)

    def test_progress_summary_never_copies_chunk_text(self) -> None:
        ...
```

- [ ] **Step 2: Implement**
- Import the module's names next to `chat_data_tables`.
- `*KNOWLEDGE_BASE_TOOL_SCHEMAS` after `*DATA_TABLE_TOOL_SCHEMAS` in `DASHBOARD_CHAT_TOOLS`.
- In `_summarize_tool_result`: `if tool_name in KNOWLEDGE_BASE_TOOL_NAMES: return summarize_knowledge_base_tool(tool_name, data if isinstance(data, dict) else {})`.
- In `stream_dashboard_chat`, an `elif name in KNOWLEDGE_BASE_TOOL_NAMES:` branch identical in shape to the DataTable branch (tool_start, call, run_steps, `_tool_end_yield`).
- Prompt: the workflow-first paragraph checks knowledge bases first; the "cannot do" list gains `(11) I can list your knowledge bases and search what is in them`; `DASHBOARD_CHAT_SYSTEM_PROMPT += KNOWLEDGE_BASE_PROMPT`.

- [ ] **Step 3: Run** `uv run pytest tests/test_chat_knowledge_bases.py tests/test_dashboard_chat_api.py -q`; expect pass.

### Task 3: Per-turn knowledge base block

**Files:**
- Modify: `backend/app/api/chats.py` (`SystemPromptParts`, `_assemble_system_prompt_parts`, context summary)
- Modify: `backend/app/api/ai_assistant.py` (`dashboard_chat_stream`, `_emit_context`)
- Test: `backend/tests/test_chat_knowledge_bases.py`

- [ ] **Step 1: Failing test** that `_assemble_system_prompt_parts` puts the block after the workflow list and before the credentials section, and stores it on `parts.knowledge_bases_block`; and that `dashboard_chat_stream` passes a system prompt containing the block to `stream_dashboard_chat`.
- [ ] **Step 2: Implement**: `knowledge_bases_block: str = ""` on `SystemPromptParts`; `system_prompt += knowledge_bases_block` right after the workflows block in both builders; add the block to `base_system_prompt` in `_emit_context` and in `get_conversation_context` so the breakdown stays complete without a new category.
- [ ] **Step 3: Run** the chat prompt suites: `uv run pytest tests/test_chat_credential_mode.py tests/test_dashboard_chat_api.py tests/test_chat_documentation.py tests/test_chat_knowledge_bases.py -q`.

### Task 4: Items route off the event loop

**Files:** Modify `backend/app/api/vector_stores.py` (`list_vector_store_items`).

- [ ] Replace the direct `service.list_items(...)` call with `await asyncio.to_thread(service.list_items, store.collection_name, limit=limit, text_truncate_length=text_truncate_length)`.
- [ ] Unit test in `test_chat_knowledge_bases.py` drives `list_knowledge_bases` with an id through the real route function, with the service patched, and checks the call arguments.

### Task 5: Real-PostgreSQL access test

**Files:** Create `backend/tests/test_chat_knowledge_bases_postgres.py`.

- [ ] Owner, direct share, team member and outsider; stores "Policies" (shared directly), "Handbook" (team), "Private". Assert each user's `list_knowledge_bases` and prompt block, and that the outsider's search of "Policies" lands in `errors` without calling the vector backend. Skips when PostgreSQL is unreachable (`connect_or_skip`).
- [ ] Run against a throwaway `postgres:16` with migrations applied.

### Task 6: Agent profile

**Files:** Modify `backend/app/services/heym_agent/profile.py`; test in `test_chat_knowledge_bases.py`.

- [ ] `AGENT_CAPABILITIES` gains "list the user's knowledge bases and the documents in each, and search their content to answer questions with the source documents;". `AGENT_SKILLS` gains `knowledge-bases` after `data-tables`.
- [ ] Test: `"knowledge bases" in AGENT_CAPABILITIES`, the skill id is present, and `MCP_TOOL_DESCRIPTION` contains the capability text.

### Task 7: Docs

- [ ] Chat tab, MCP tab (heym_chat capabilities), A2A (skills list), Chat with Heym, features reference, vector store tab: a short "Ask the chat" note.

### Task 8: Verify and open the draft PR

- [ ] `uv run ruff format . && uv run ruff check .` in `backend/`.
- [ ] `SECRET_KEY=... DATABASE_URL=<throwaway> ENCRYPTION_KEY=<64 hex> ./check.sh` from the repo root.
- [ ] Branch `chat-knowledge-bases`, commit without attribution lines, push, `gh pr create --draft` without attribution.
