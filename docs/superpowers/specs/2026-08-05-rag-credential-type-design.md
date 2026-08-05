# RAG Credential Type — Design

**Date:** 2026-08-05
**Status:** Approved, implementation local-only (no commit)

## Problem

Heym has two vector-store credential types, `qdrant` ("RAG: Qdrant + OpenAI") and
`pgvector` ("RAG: Psql + OpenAI"). Both hardcode the embedding provider: the config
carries only an `openai_api_key`, and `EmbeddingService` always calls OpenAI's
`text-embedding-3-large` at 1536 dimensions. Users who run their own embedding
endpoint (Ollama, TEI, vLLM, LM Studio, Together, Voyage, any OpenAI-compatible
server) cannot use RAG at all.

We need a credential that points at an arbitrary embedding endpoint by URL, with an
optional API key, and that also picks which of the two existing vector-store backends
to write into.

## Goals

- New `rag` credential type: custom embedding base URL, optional API key, model name,
  embedding dimensions.
- Single-select vector store DB type inside the same credential dialog, limited to the
  two backends that exist today: Qdrant and Postgres (pgvector).
- Works everywhere RAG already works: the RAG node, the Vector Stores panel, agent RAG
  tooling, file upload/indexing.
- Existing `qdrant` and `pgvector` credentials keep working untouched.

## Non-goals

- Making the pgvector column dimension-flexible. The `pgvector_store_items.embedding`
  column is `vector(1536)` (migration `5ba5b9aaf6ba`) and stays that way.
- Migrating existing `qdrant`/`pgvector` credentials to the new type.
- Reranker changes. Reranking stays on the separate `cohere` credential.
- Frontend UI tests (repo convention: backend pytest only).

## Key decisions

### Dimensions: configurable, with a hard pgvector constraint

Qdrant sizes its vectors per collection, so it can hold any dimension as long as
`create_collection` is told the number. Postgres cannot, without a schema migration we
explicitly ruled out.

So: the credential carries `embedding_dimensions` (default 1536). Qdrant honors it.
Choosing `pgvector` with anything other than 1536 is rejected at credential-save time
with a clear message, and the dialog warns *before* the user gets there.

### Coexistence, not replacement

`rag` is added as a third type. `qdrant` and `pgvector` remain in the credential type
dropdown and keep functioning. No data migration, no deprecation. Zero regression risk
for existing stores; the cost is three similar-looking entries in the dropdown.

### `dimensions=` is not sent to custom endpoints

OpenAI accepts a `dimensions` request parameter for `text-embedding-3-*`. Most
OpenAI-compatible servers reject unknown parameters. The parameter is therefore sent
only on the legacy OpenAI path (no custom base URL); for a `rag` credential the model's
native output width is used and validated instead.

### Returned vector width is always validated

Every embedding response is checked against the configured `embedding_dimensions`. A
mismatch raises `ValueError("... model returned 768 dimensions, credential expects
1024")` rather than surfacing as an opaque Qdrant/Postgres write failure.

### Connection test in the dialog

Dimension mismatch is the dominant failure mode and would otherwise only appear during
a workflow run. `POST /credentials/test` accepts `rag`, embeds a short probe string, and
reports the real dimension count back into the dialog.

## Architecture

### Backend

**Enum and schema** — `backend/app/models/schemas.py`, `backend/app/db/models.py`

Add `rag = "rag"` to both `CredentialType` enums, plus an Alembic migration doing
`ALTER TYPE ... ADD VALUE 'rag'` (follows `081_add_notion_credential_type.py`).

```python
class CredentialConfigRag(BaseModel):
    embedding_base_url: str
    embedding_api_key: str | None = None
    embedding_model: str
    embedding_dimensions: int = 1536
    db_type: str                      # "qdrant" | "pgvector"
    qdrant_host: str | None = None    # required when db_type == "qdrant"
    qdrant_port: int = 6333
    qdrant_api_key: str | None = None
```

**Validation** — `validate_credential_config` in `backend/app/api/credentials.py`

- `embedding_base_url`, `embedding_model` required and non-empty.
- `db_type` must be `qdrant` or `pgvector`.
- `db_type == "pgvector"` and `embedding_dimensions != 1536` → HTTP 400 naming both the
  configured value and the requirement.
- `db_type == "qdrant"` → `qdrant_host` required.
- `embedding_dimensions` must be a positive int.

**Masking** — the secret-preview branch in `credentials.py` masks `embedding_api_key`.

**Embedding layer** — `backend/app/services/embedding.py`

Introduce an `EmbeddingConfig` dataclass (`base_url`, `api_key`, `model`, `dimensions`)
and let `EmbeddingService` be constructed from it. The existing positional
`EmbeddingService(openai_api_key)` signature is preserved so the two legacy call sites
(`vector_store.py:131`, `vector_store_pg.py:47`) keep compiling; that path defaults to
the current OpenAI model/dimensions and keeps sending `dimensions=`.

- `tiktoken.encoding_for_model(model)` with `cl100k_base` fallback for unknown names.
  Token batching stays approximate for non-OpenAI models, which is acceptable — it only
  drives request chunking.
- Both `embed_text` and `embed_texts` verify `len(embedding) == config.dimensions`.

**Vector store factory** — `backend/app/services/vector_store.py:533`

`create_vector_store_service_for_credential` gains a `rag` branch that reads
`config["db_type"]` and builds `QdrantVectorStoreService` or `PgVectorStoreService` with
an `EmbeddingConfig` derived from the credential. Only two call sites exist
(`api/vector_stores.py:103`, `node_execution/nodes/rag_node.py:45`), so this stays the
single dispatch point.

`QdrantVectorStoreService` takes the dimension count and uses it in `create_collection`
instead of the module-level `EMBEDDING_DIMENSIONS` constant.
`PgVectorStoreService` continues to assume 1536 (guarded by the validation above).

**Backend derivation** — `backend/app/api/vector_stores.py`

- The credential-type guard at line 92 accepts `CredentialType.rag`.
- `_backend_for_credential_type` and `_store_backend` return `config["db_type"]` for
  `rag` credentials. `_store_backend` already loads the credential row, so it only needs
  to decrypt the config.

**Pool warm-up** — `backend/app/services/qdrant_pool.py`

`warm_up_pools` also collects `rag` credentials whose `db_type` is `qdrant`.

**Connection test** — `backend/app/api/credentials.py:823`

Add `CredentialType.rag` to the permitted set. The handler builds an `EmbeddingService`
from the (possibly merged, possibly stored) config, embeds a short probe string in a
threadpool, and returns either
`"Connected. Model returned N dimensions."` or a failure naming both N and the
configured value.

### Frontend

**Types** — `frontend/src/types/credential.ts`

Add `"rag"` to the `CredentialType` union, a `RagCredentialConfig` interface, a label
(`"RAG"`), and a description covering custom embedding endpoints.

**Dialog** — `frontend/src/components/Credentials/CredentialDialog.vue`

A new type block following the existing per-type pattern: base URL, API key (optional),
model, dimensions, then a single-select vector DB control. Selecting Qdrant reveals
host/port/API key. Selecting Postgres shows an inline notice above the fields:

> Postgres (pgvector) stores vectors in a fixed `vector(1536)` column. Your embedding
> model must return 1536 dimensions.

Wire the type into: reset-on-open, load-for-edit, `canSave` validation, the save
payload, and the secret-dirty check. Add the `Test connection` button for this type.

**Vector Stores panel** — `frontend/src/components/VectorStores/VectorStoresPanel.vue`

Add `credentialsApi.listByType("rag")` to the credential fetch, and filter the
credential options by the selected backend — a `rag` credential matches the chosen
backend when its `db_type` equals it.

**RAG node** — no change. `node.data.dbType` is only a list filter; rag-backed stores
report the correct `backend` value, so filtering keeps working.

## Testing

Backend pytest (`backend/tests/`):

- `validate_credential_config` accepts a well-formed rag config; rejects missing base
  URL, missing model, bad `db_type`, missing `qdrant_host` under Qdrant, and
  `pgvector` + non-1536 dimensions.
- `create_vector_store_service_for_credential` dispatches a rag credential to the Qdrant
  or the pgvector service according to `db_type`, and raises on an unknown `db_type`.
- Qdrant `create_collection` uses the credential's dimension count.
- `EmbeddingService` raises on a width mismatch, and omits `dimensions=` when a custom
  base URL is configured (assert on the mocked client call kwargs).
- `POST /credentials/test` with `type=rag` returns success with the reported dimension,
  and failure text on mismatch.
- `_store_backend` / `_backend_for_credential_type` return `db_type` for rag
  credentials.
- Credential secret masking covers `embedding_api_key`.

No frontend UI tests. Verification is `bun run lint` + `bun run typecheck`.

## Documentation

Per the repository feature-documentation policy this is a medium feature, so update via
the `heym-documentation` skill:

- `frontend/src/docs/content/tabs/credentials-tab.md`
- `frontend/src/docs/content/tabs/vectorstores-tab.md`
- `frontend/src/docs/content/nodes/rag-node.md`
- `frontend/src/docs/content/reference/credentials.md`
- `frontend/src/docs/content/reference/credentials-sharing.md`
- `frontend/src/docs/content/reference/integrations.md`
- the RAG node SETUP paragraph in
  `backend/app/services/workflow_dsl_prompt.py` (~line 1939)

## Delivery

Work happens on `main` in the working tree. **Nothing is committed** — the user will
review the local diff. `./check.sh` is run for verification only.
