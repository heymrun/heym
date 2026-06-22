# Postgres/pgvector Vector Store Backend — Design

**Date:** 2026-06-22
**Status:** Approved (brainstorming) — pending implementation plan

## Goal

Add a **Postgres + pgvector** vector store backend as a first-class alternative to
Qdrant in Heym. Heym writes embeddings to **its own Postgres database** (never an
external DB). Every existing RAG/vector-store feature that works with Qdrant must work
identically on the Postgres backend. Qdrant remains the default for full backward
compatibility. The website (heymweb) docs and any "Qdrant-only" copy get updated.

## Decisions (locked during brainstorming)

1. **Backend selection model:** a new credential type `pgvector`. The vector store's
   backend is derived from its linked credential's type. No `db_type` column on
   `VectorStore`.
2. **Storage layout:** one shared table `vector_store_items` keyed by `collection_name`
   (no runtime DDL, no table-per-collection).
3. **Postgres image:** switch to `pgvector/pgvector:pg16` (drop-in superset of
   `postgres:16`) and run `CREATE EXTENSION IF NOT EXISTS vector` via Alembic.
4. **ANN index:** HNSW with `vector_cosine_ops` (no training step, good recall from the
   first row).
5. **heymweb scope:** sync in-repo docs to heymweb (`bun run sync-docs`) **and** audit
   the heymweb site for "Qdrant only" / "Qdrant is the vector store" copy and update it
   to present Postgres/pgvector as an option. No new blog post in this task.

## Current architecture (as-is)

- `Credential` of type `qdrant` holds `qdrant_host`, `qdrant_port`, `qdrant_api_key`,
  `openai_api_key`.
- `VectorStore` row: `name`, `description`, `collection_name`, `owner_id`,
  `credential_id`.
- `VectorStoreService` (`backend/app/services/vector_store.py`) wraps a sync
  `QdrantClient` + `EmbeddingService` (OpenAI, fixed **1536** dims). ~13 methods:
  `create_collection`, `delete_collection`, `collection_exists`,
  `get_collection_stats`, `insert`, `insert_batch`, `search`, `delete_points`,
  `find_existing_files`, `delete_by_source`, `clone_collection`, `list_items`,
  `delete_point`.
- Used in three places:
  - `backend/app/api/vector_stores.py` (CRUD, upload, clone, items, stats, duplicates).
  - `backend/app/services/workflow_executor.py` RAG node branch (`node_type == "rag"`,
    operations `insert` / `search`, incl. reranker flow).
  - `_get_store_stats` in the API.
- `backend/app/services/qdrant_pool.py` warms Qdrant client pools at startup.
- Sync DB access already exists: `SessionLocal` over a `postgresql://` (psycopg2)
  `sync_engine` in `backend/app/db/session.py`.

## Target architecture

### 1. Infra — enable pgvector

- `docker-compose.yml`: `image: postgres:16` → `image: pgvector/pgvector:pg16`.
- `run.sh`: the `docker run ... -d postgres:16` fallback → `pgvector/pgvector:pg16`.
- Alembic migration `*_pgvector_store_items`:
  - `CREATE EXTENSION IF NOT EXISTS vector;`
  - Create table `vector_store_items`:
    - `id UUID PK`
    - `collection_name TEXT NOT NULL`
    - `text TEXT NOT NULL`
    - `embedding vector(1536) NOT NULL`
    - `metadata JSONB NOT NULL DEFAULT '{}'`
    - `source TEXT NULL`
    - `file_size INTEGER NULL`
    - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - Indexes: btree on `collection_name`; HNSW `vector_cosine_ops` on `embedding`;
    optional btree on `(collection_name, source)` for `find_existing_files` /
    `delete_by_source`.
- Add `pgvector` to backend dependencies (`pyproject.toml`). Use it for vector literal
  binding through the sync engine; embeddings are JSON-serialized text cast to
  `::vector` if the package binding is not used.
- Migration is non-destructive; running `alembic upgrade head` is required after pull
  (per AGENTS.md).

### 2. New credential type `pgvector` ("RAG: Psql + OpenAI")

**Backend**

- `CredentialType.pgvector` enum value in `backend/app/db/models.py`.
- Alembic migration: `ALTER TYPE credential_type ADD VALUE 'pgvector'` (idempotent
  guard; enum value adds cannot run inside a transaction block on older PG — use the
  standard Alembic pattern already used for prior enum additions in this repo).
- `CredentialConfigPgvector(BaseModel)` in `backend/app/models/schemas.py`:
  `{ openai_api_key: str }`.
- `backend/app/api/credentials.py` validation branch for `pgvector`: require
  `openai_api_key`; **no** host/port (uses the app's own DB).

**Frontend**

- `frontend/src/types/credential.ts`:
  - Add `"pgvector"` to the `CredentialType` union.
  - `CredentialConfigPgvector { openai_api_key: string }` and add to the config union.
  - `CREDENTIAL_TYPE_LABELS`: rename `qdrant` → **"RAG: Qdrant + OpenAI"**, add
    `pgvector` → **"RAG: Psql + OpenAI"** (UI labels only; enum keys unchanged).
  - `CREDENTIAL_TYPE_DESCRIPTIONS`: add a pgvector description ("Vector storage inside
    Heym's own Postgres database with OpenAI embeddings — no external DB").
- `frontend/src/components/Credentials/CredentialDialog.vue`: add `pgvector` to the type
  list and a minimal form (single OpenAI API key field). Reset logic mirrors the qdrant
  branch.

### 3. Service abstraction

- Move shared dataclasses (`SearchResult`, `CollectionStats`, `ExistingFile`,
  `VectorStoreItem`, `VectorStoreSourceGroup`) and a `VectorStoreBackend` interface
  (Protocol/ABC declaring the ~13 methods) into the vector-store module (or a small
  `vector_store_base.py`).
- Existing Qdrant implementation → `QdrantVectorStoreService` (behavior unchanged).
- New `PgVectorStoreService(openai_api_key)`:
  - Uses `SessionLocal` / `sync_engine` + raw SQL against `vector_store_items` filtered
    by `collection_name`. Reuses `EmbeddingService`.
  - `collection_name` is the per-store partition; the `VectorStore` row stays the source
    of truth, so `create_collection` is a no-op returning `True` and `collection_exists`
    returns `True` (or `EXISTS`-checks rows) — matching the interface contract used by
    callers.
  - `get_collection_stats` → `COUNT(*)`/status from the table.
  - `insert` / `insert_batch` → parameterized `INSERT` with `embedding::vector`.
  - `search` → `ORDER BY embedding <=> :query_vec LIMIT :k`, score =
    `1 - cosine_distance`; metadata filter via JSONB containment; preserves the existing
    reranker path in the executor (returns the same `SearchResult` shape).
  - `delete_points` / `delete_point` / `delete_by_source` / `find_existing_files` /
    `list_items` / `clone_collection` → straightforward SQL (clone = `INSERT ... SELECT`
    with the new `collection_name`).
- `create_vector_store_service(...)` becomes a factory that branches on the credential
  type and returns the matching backend. Keep a thin backward-compatible signature or a
  new `create_vector_store_service_for_credential(credential_type, config)` helper used
  by all call sites.

### 4. API (`vector_stores.py`)

- `get_credential_config`: accept `qdrant` **and** `pgvector` (currently rejects
  non-qdrant).
- `get_vector_store_service_from_config(config, credential_type)`: build the right
  backend. The pgvector branch needs no host/port.
- All other endpoints (create/list/get/update/delete/clone/upload/check-duplicates/
  items/stats/shares) work unchanged through the interface. Error strings that say
  "QDrant" become backend-neutral ("vector store").

### 5. RAG node (canvas + executor)

- `frontend/src/types/node.ts`: add `dbType: "qdrant" | "pgvector"` to the RAG node data
  (default `"qdrant"`); update the node label/description to be backend-neutral
  (e.g. "RAG / Vector Store").
- `frontend/src/components/Panels/PropertiesPanel.vue` RAG config: add a **Database type
  dropdown (Qdrant / Postgres), default Qdrant**, which filters the selectable vector
  stores to those whose backing credential matches the chosen backend. Selecting a store
  still drives `vectorStoreId`.
- `backend/app/services/workflow_executor.py` RAG branch: replace the hardcoded
  `qdrant_host/port` construction with the factory keyed on the store's credential type.
  Existing qdrant stores keep working unchanged (default path).

### 6. Docs (heymrun → heymweb)

- Update `frontend/src/docs/content/`: `nodes/rag-node.md`, `tabs/vectorstores-tab.md`,
  `tabs/credentials-tab.md`, `reference/credentials.md`, `reference/integrations.md`,
  `reference/features.md`, `reference/node-types.md`,
  `reference/credentials-sharing.md`, `getting-started/why-heym.md` — present Postgres
  as a supported vector backend alongside Qdrant.
- heymweb: run `bun run sync-docs` to propagate, then audit the site for "Qdrant only"
  style copy (landing, feature pages, blog mentions that imply Qdrant is the only vector
  store) and update to mention the Postgres option. No new blog post in this task.

### 7. Tests (backend required, per AGENTS.md)

- `PgVectorStoreService` unit tests (mocked sync session / engine): insert, search
  ordering + score, metadata filter, delete_by_source, find_existing_files, list_items,
  clone, stats.
- Credential validation: `pgvector` requires `openai_api_key`.
- Factory selection: qdrant credential → Qdrant backend, pgvector credential → pg
  backend.
- Executor RAG node with a pgvector credential (insert + search), including the
  no-reranker path.
- E2E (optional): create a "RAG: Psql + OpenAI" credential, create a Postgres vector
  store, upload a file, run a RAG search node.

## Backward compatibility

- Every default remains Qdrant: node `dbType` defaults to `"qdrant"`, the credential
  dropdown defaults to Qdrant, existing `VectorStore` rows keep their qdrant credentials.
- Enum addition and the new table are additive/non-destructive.
- No external DB connection is ever made for pgvector — embeddings live in Heym's own
  Postgres.

## Out of scope

- Configurable embedding dimensions (stays fixed at 1536).
- Migrating existing Qdrant collections into Postgres (or vice versa).
- A heymweb blog/announcement post (separate future task).
