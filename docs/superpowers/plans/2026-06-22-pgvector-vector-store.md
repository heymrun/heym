# Postgres/pgvector Vector Store Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Postgres + pgvector vector store backend as a first-class alternative to Qdrant, writing embeddings to Heym's own database, with Qdrant remaining the default for full backward compatibility.

**Architecture:** A new `pgvector` credential type makes the backend derivable from a vector store's linked credential. A `VectorStoreBackend` interface fronts two implementations (`QdrantVectorStoreService`, `PgVectorStoreService`); a factory picks one by credential type. pgvector data lives in one shared `vector_store_items` table partitioned by `collection_name`. The RAG node gains a Database-type dropdown (default Qdrant) that filters selectable stores by backend.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 (sync engine for vector ops) + pgvector + Alembic; Vue 3 + TypeScript (strict); PostgreSQL 16 via `pgvector/pgvector:pg16`.

**Conventions:**
- Backend tests required (AGENTS.md). Run with `SECRET_KEY=test-secret-key-for-tests-only-32-bytes` prefix if no `SECRET_KEY` exported.
- No frontend unit tests in this repo — verify frontend with `bun run lint` + `bun run typecheck` + manual.
- Commit frequently. Work on `main`. Do **not** push (ask first).
- Run specific backend test: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/<file>::<Class>::<test> -v`

---

## File Structure

**Backend create:**
- `backend/app/services/vector_store_pg.py` — `PgVectorStoreService` (pgvector backend).
- `backend/alembic/versions/<rev>_pgvector_store_items.py` — extension + `vector_store_items` table.
- `backend/alembic/versions/<rev>_add_pgvector_credential_type.py` — enum value.
- `backend/tests/test_vector_store_pg.py` — pgvector service unit tests.
- `backend/tests/test_pgvector_credential_and_factory.py` — credential validation + factory + executor.

**Backend modify:**
- `backend/app/services/vector_store.py` — extract shared dataclasses + `VectorStoreBackend` interface; rename class to `QdrantVectorStoreService`; add factory `create_vector_store_service_for_credential`.
- `backend/app/db/models.py` — `CredentialType.pgvector`.
- `backend/app/models/schemas.py` — `CredentialConfigPgvector`; `backend` field on vector store responses.
- `backend/app/api/credentials.py` — pgvector validation + masked display.
- `backend/app/api/vector_stores.py` — accept pgvector creds; build correct backend; set `backend` in responses.
- `backend/app/services/workflow_executor.py` — RAG branch uses factory by credential type.
- `backend/pyproject.toml` — add `pgvector` dependency.
- `docker-compose.yml`, `run.sh` — `pgvector/pgvector:pg16` image.

**Frontend modify:**
- `frontend/src/types/credential.ts` — pgvector type, config, labels, description.
- `frontend/src/components/Credentials/CredentialDialog.vue` — pgvector form.
- `frontend/src/types/node.ts` — RAG node `dbType` + relabel.
- `frontend/src/components/Panels/PropertiesPanel.vue` — DB-type dropdown + backend filtering.
- `frontend/src/services/api.ts` (vector store types) — `backend` field on list item type.

**Docs modify:**
- `frontend/src/docs/content/` (multiple files listed in Task 16).
- heymweb (separate repo): `bun run sync-docs` + Qdrant-only copy audit (Task 17).

---

## Phase A — Infra & storage

### Task 1: Switch Postgres image to pgvector

**Files:**
- Modify: `docker-compose.yml`
- Modify: `run.sh`

- [ ] **Step 1: Update docker-compose image**

In `docker-compose.yml`, change the postgres service image:

```yaml
  postgres:
    image: pgvector/pgvector:pg16
```

- [ ] **Step 2: Update run.sh fallback image**

In `run.sh`, the `docker run` fallback that creates `heym-postgres` ends with `-d postgres:16`. Change it to:

```bash
        -d pgvector/pgvector:pg16
```

- [ ] **Step 3: Recreate the container and verify the image**

Run:
```bash
docker rm -f heym-postgres 2>/dev/null; docker-compose up -d postgres
docker exec heym-postgres psql -U postgres -d heym -c "SELECT 1;"
```
Expected: container starts; `SELECT 1` returns `1`. (Existing data volume in `./data/postgres` is preserved; the pgvector image is a superset of postgres:16.)

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml run.sh
git commit -m "chore: use pgvector/pgvector:pg16 postgres image"
```

---

### Task 2: Add pgvector dependency and the vector_store_items migration

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/alembic/versions/<rev>_pgvector_store_items.py` (created via alembic command)

- [ ] **Step 1: Add the pgvector Python dependency**

In `backend/pyproject.toml`, add `"pgvector>=0.3.0"` to the `dependencies` list (alphabetical-ish, near other data libs). Then:

```bash
cd backend && uv sync
```
Expected: `pgvector` resolves and installs.

- [ ] **Step 2: Generate an empty migration linked to the current head**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run alembic revision -m "pgvector_store_items"
```
Expected: a new file under `alembic/versions/` whose `down_revision` is the current head (`081_add_workflow_analysis_notes`). If alembic complains about multiple heads, run `uv run alembic heads`, create a merge with `uv run alembic merge -m "merge heads" <head1> <head2>`, then re-run this revision command.

- [ ] **Step 3: Fill in the migration body**

Replace the generated `upgrade`/`downgrade` with:

```python
from alembic import op

def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vector_store_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            collection_name TEXT NOT NULL,
            text TEXT NOT NULL,
            embedding vector(1536) NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            source TEXT,
            file_size INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vsi_collection_name "
        "ON vector_store_items (collection_name)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vsi_collection_source "
        "ON vector_store_items (collection_name, source)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vsi_embedding_hnsw "
        "ON vector_store_items USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vector_store_items")
```

Note: `gen_random_uuid()` is built into Postgres 13+ (pgcrypto not required). The `vector` extension is created idempotently here.

- [ ] **Step 4: Apply the migration**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run alembic upgrade head
docker exec heym-postgres psql -U postgres -d heym -c "\d vector_store_items"
```
Expected: migration applies; `\d` shows the table with an `embedding` column of type `vector(1536)` and the three indexes.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/alembic/versions/
git commit -m "feat(db): add pgvector extension and vector_store_items table"
```

---

## Phase B — Credential type

### Task 3: Add `pgvector` to the CredentialType enum (model + migration)

**Files:**
- Modify: `backend/app/db/models.py:43` (enum)
- Create: `backend/alembic/versions/<rev>_add_pgvector_credential_type.py`

- [ ] **Step 1: Add the enum member in the model**

In `backend/app/db/models.py`, in `class CredentialType`, add after `qdrant = "qdrant"`:

```python
    pgvector = "pgvector"
```

- [ ] **Step 2: Generate the migration**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run alembic revision -m "add_pgvector_credential_type"
```

- [ ] **Step 3: Fill in the migration body**

Mirror `072_add_elevenlabs_credential_type.py`:

```python
from alembic import op

def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'pgvector'")

def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
```

- [ ] **Step 4: Apply and verify**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run alembic upgrade head
docker exec heym-postgres psql -U postgres -d heym -c "SELECT unnest(enum_range(NULL::credential_type)) WHERE unnest(enum_range(NULL::credential_type))::text = 'pgvector';"
```
Expected: returns `pgvector`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/
git commit -m "feat(db): add pgvector credential type"
```

---

### Task 4: pgvector credential schema, validation, and masked display

**Files:**
- Modify: `backend/app/models/schemas.py` (after `CredentialConfigQdrant`)
- Modify: `backend/app/api/credentials.py` (validation block + masked display)
- Test: `backend/tests/test_pgvector_credential_and_factory.py`

- [ ] **Step 1: Write the failing validation test**

Create `backend/tests/test_pgvector_credential_and_factory.py`:

```python
import unittest

from fastapi import HTTPException

from app.api.credentials import validate_credential_config
from app.db.models import CredentialType


class TestPgvectorCredentialValidation(unittest.TestCase):
    def test_pgvector_requires_openai_api_key(self):
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.pgvector, {})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_pgvector_valid_config_passes(self):
        # Should not raise.
        validate_credential_config(
            CredentialType.pgvector, {"openai_api_key": "sk-test"}
        )


if __name__ == "__main__":
    unittest.main()
```

Note: `validate_credential_config` is defined at `backend/app/api/credentials.py:926`; the masked display function is `get_masked_value` at line 63. Both confirmed.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_pgvector_credential_and_factory.py::TestPgvectorCredentialValidation -v
```
Expected: FAIL — pgvector branch does not exist, so the empty config does not raise.

- [ ] **Step 3: Add the schema model**

In `backend/app/models/schemas.py`, right after `class CredentialConfigQdrant(BaseModel)`:

```python
class CredentialConfigPgvector(BaseModel):
    openai_api_key: str
```

- [ ] **Step 4: Add validation**

In `backend/app/api/credentials.py`, after the `elif credential_type == CredentialType.qdrant:` validation block (the one near line 1027), add:

```python
    elif credential_type == CredentialType.pgvector:
        if "openai_api_key" not in config or not config["openai_api_key"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Postgres vector credential requires openai_api_key",
            )
```

- [ ] **Step 5: Add masked display**

In `backend/app/api/credentials.py`, in the masked-display function, after `elif credential_type == CredentialType.qdrant:` (near line 100) add:

```python
    elif credential_type == CredentialType.pgvector:
        openai_api_key = config.get("openai_api_key", "")
        return mask_api_key(openai_api_key)
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_pgvector_credential_and_factory.py::TestPgvectorCredentialValidation -v
```
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/schemas.py backend/app/api/credentials.py backend/tests/test_pgvector_credential_and_factory.py
git commit -m "feat(credentials): add pgvector credential validation and display"
```

---

### Task 5: Frontend pgvector credential type, labels, and dialog form

**Files:**
- Modify: `frontend/src/types/credential.ts`
- Modify: `frontend/src/components/Credentials/CredentialDialog.vue`

- [ ] **Step 1: Add type, config, label, description**

In `frontend/src/types/credential.ts`:

Add `| "pgvector"` to the `CredentialType` union (near the `"qdrant"` line ~16).

Add the config interface near `CredentialConfigQdrant` (~line 146):

```typescript
export interface CredentialConfigPgvector {
  openai_api_key: string;
}
```

Add `| CredentialConfigPgvector` to the config union (near line 211).

In `CREDENTIAL_TYPE_LABELS`, rename the qdrant label and add pgvector:

```typescript
  qdrant: "RAG: Qdrant + OpenAI",
  pgvector: "RAG: Psql + OpenAI",
```

In `CREDENTIAL_TYPE_DESCRIPTIONS`, add:

```typescript
  pgvector: "Vector storage inside Heym's own Postgres database with OpenAI embeddings (no external DB)",
```

- [ ] **Step 2: Add the dialog form**

In `frontend/src/components/Credentials/CredentialDialog.vue`:

- Add a ref near the qdrant refs (~line 64):
  ```typescript
  const pgvectorOpenaiApiKey = ref("");
  ```
- Add to the type options list (near `{ value: "qdrant", ... }` ~line 164):
  ```typescript
  { value: "pgvector", label: CREDENTIAL_TYPE_LABELS.pgvector },
  ```
- In the reset logic (where `qdrant*` refs are reset to "", ~lines 210 and 275), add `pgvectorOpenaiApiKey.value = "";` alongside.
- Add a template block (mirroring the qdrant block but only the OpenAI key field) shown when the selected type is `pgvector`. Use the existing input/Label components used by the qdrant block. Bind `v-model="pgvectorOpenaiApiKey"`.
- In the submit/config-builder for `pgvector`, build `{ openai_api_key: pgvectorOpenaiApiKey.value }`. When editing an existing pgvector credential, hydrate `pgvectorOpenaiApiKey` from the loaded config the same way the qdrant branch hydrates its fields.

- [ ] **Step 3: Lint and typecheck**

```bash
cd frontend && bun run lint && bun run typecheck
```
Expected: both pass (no unused vars, exhaustive `Record<CredentialType, ...>` now includes `pgvector`).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/credential.ts frontend/src/components/Credentials/CredentialDialog.vue
git commit -m "feat(ui): add Psql+OpenAI credential and rename Qdrant label"
```

---

## Phase C — Service abstraction

### Task 6: Extract the backend interface and rename the Qdrant service

**Files:**
- Modify: `backend/app/services/vector_store.py`

- [ ] **Step 1: Add the interface and rename the class**

In `backend/app/services/vector_store.py`:

- Keep the shared dataclasses (`SearchResult`, `CollectionStats`, `ExistingFile`, `VectorStoreItem`, `VectorStoreSourceGroup`) where they are.
- Add a `Protocol` interface above the class:

```python
from typing import Protocol


class VectorStoreBackend(Protocol):
    def create_collection(self, collection_name: str) -> bool: ...
    def delete_collection(self, collection_name: str) -> bool: ...
    def collection_exists(self, collection_name: str) -> bool: ...
    def get_collection_stats(self, collection_name: str) -> CollectionStats | None: ...
    def insert(
        self, collection_name: str, text: str,
        metadata: dict | None = None, point_id: str | None = None,
    ) -> str: ...
    def insert_batch(
        self, collection_name: str, texts: list[str],
        metadata_list: list[dict] | None = None,
    ) -> list[str]: ...
    def search(
        self, collection_name: str, query: str,
        limit: int = 5, metadata_filter: dict | None = None,
    ) -> list[SearchResult]: ...
    def delete_points(self, collection_name: str, point_ids: list[str]) -> bool: ...
    def find_existing_files(
        self, collection_name: str, files: list[tuple[str, int]],
    ) -> list[ExistingFile]: ...
    def delete_by_source(self, collection_name: str, source: str) -> int: ...
    def clone_collection(
        self, source_collection: str, target_collection: str, batch_size: int = 100,
    ) -> int: ...
    def list_items(
        self, collection_name: str, limit: int = 100, text_truncate_length: int = 200,
    ) -> tuple[list[VectorStoreSourceGroup], int]: ...
    def delete_point(self, collection_name: str, point_id: str) -> bool: ...
```

- Rename `class VectorStoreService` → `class QdrantVectorStoreService`. Keep a backward-compatible alias so existing imports/tests do not break:

```python
# Backward-compatible alias (existing imports use VectorStoreService).
VectorStoreService = QdrantVectorStoreService
```

- Keep the existing `create_vector_store_service(...)` factory function unchanged (it already returns a Qdrant service from host/port/api_key) so current call sites compile.

- [ ] **Step 2: Run the existing vector store tests**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "vector_store or rag" -v
```
Expected: existing tests still PASS (alias keeps them green). If a test imports `VectorStoreService` directly, it resolves via the alias.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/vector_store.py
git commit -m "refactor(vector-store): add VectorStoreBackend interface, rename Qdrant service"
```

---

### Task 7: Implement PgVectorStoreService

**Files:**
- Create: `backend/app/services/vector_store_pg.py`
- Test: `backend/tests/test_vector_store_pg.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_vector_store_pg.py`:

```python
import unittest
from unittest.mock import MagicMock, patch

from app.services.vector_store import SearchResult


class TestPgVectorStoreService(unittest.TestCase):
    def _service(self, embed_return=None):
        with patch("app.services.vector_store_pg.EmbeddingService") as emb_cls:
            emb = emb_cls.return_value
            emb.embed_text.return_value = embed_return or [0.0] * 1536
            from app.services.vector_store_pg import PgVectorStoreService

            engine = MagicMock()
            svc = PgVectorStoreService("sk-test", engine=engine)
            return svc, engine, emb

    def test_search_builds_results_and_score(self):
        svc, engine, emb = self._service()
        conn = engine.connect.return_value.__enter__.return_value
        row = MagicMock()
        row.id = "11111111-1111-1111-1111-111111111111"
        row.text = "hello"
        row.distance = 0.25  # cosine distance -> score 0.75
        row.metadata = {"source": "a.txt", "file_size": 10}
        conn.execute.return_value.fetchall.return_value = [row]

        results = svc.search("col1", "query", limit=3)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], SearchResult)
        self.assertEqual(results[0].text, "hello")
        self.assertAlmostEqual(results[0].score, 0.75, places=5)
        self.assertEqual(results[0].metadata.get("source"), "a.txt")

    def test_insert_returns_point_id(self):
        svc, engine, emb = self._service()
        pid = svc.insert("col1", "doc text", {"source": "a.txt"})
        self.assertTrue(pid)
        engine.begin.assert_called()  # write used a transaction

    def test_collection_exists_is_true(self):
        svc, engine, emb = self._service()
        self.assertTrue(svc.collection_exists("anything"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_vector_store_pg.py -v
```
Expected: FAIL — `app.services.vector_store_pg` does not exist.

- [ ] **Step 3: Implement the service**

Create `backend/app/services/vector_store_pg.py`:

```python
import json
import uuid

from sqlalchemy import text

from app.services.embedding import EmbeddingService
from app.services.vector_store import (
    CollectionStats,
    ExistingFile,
    SearchResult,
    VectorStoreItem,
    VectorStoreSourceGroup,
)

TABLE = "vector_store_items"


def _vec_literal(embedding: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


class PgVectorStoreService:
    """pgvector backend. Stores embeddings in Heym's own Postgres DB.

    All rows live in one shared table partitioned by ``collection_name``.
    The VectorStore row is the source of truth for existence, so
    ``create_collection`` is a no-op and ``collection_exists`` returns True.
    """

    def __init__(self, openai_api_key: str, engine=None):
        if engine is None:
            from app.db.session import sync_engine

            engine = sync_engine
        self.engine = engine
        self.embedding_service = EmbeddingService(openai_api_key)

    def create_collection(self, collection_name: str) -> bool:
        return True

    def collection_exists(self, collection_name: str) -> bool:
        return True

    def delete_collection(self, collection_name: str) -> bool:
        with self.engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {TABLE} WHERE collection_name = :c"),
                {"c": collection_name},
            )
        return True

    def get_collection_stats(self, collection_name: str) -> CollectionStats | None:
        with self.engine.connect() as conn:
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {TABLE} WHERE collection_name = :c"),
                {"c": collection_name},
            ).scalar() or 0
        return CollectionStats(
            vector_count=count,
            indexed_vectors_count=count,
            points_count=count,
            segments_count=1,
            status="green",
        )

    def insert(
        self,
        collection_name: str,
        text_value: str,
        metadata: dict | None = None,
        point_id: str | None = None,
    ) -> str:
        embedding = self.embedding_service.embed_text(text_value)
        pid = point_id or str(uuid.uuid4())
        meta = dict(metadata or {})
        source = meta.get("source")
        file_size = meta.get("file_size")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {TABLE} "
                    "(id, collection_name, text, embedding, metadata, source, file_size) "
                    "VALUES (:id, :c, :t, (:e)::vector, (:m)::jsonb, :s, :fs)"
                ),
                {
                    "id": pid,
                    "c": collection_name,
                    "t": text_value,
                    "e": _vec_literal(embedding),
                    "m": json.dumps(meta),
                    "s": source,
                    "fs": file_size,
                },
            )
        return pid

    def insert_batch(
        self,
        collection_name: str,
        texts: list[str],
        metadata_list: list[dict] | None = None,
    ) -> list[str]:
        if not texts:
            return []
        embeddings = self.embedding_service.embed_texts(texts)
        rows = []
        ids = []
        for i, emb in enumerate(embeddings):
            pid = str(uuid.uuid4())
            ids.append(pid)
            meta = dict(metadata_list[i]) if metadata_list and i < len(metadata_list) else {}
            rows.append(
                {
                    "id": pid,
                    "c": collection_name,
                    "t": emb.text,
                    "e": _vec_literal(emb.embedding),
                    "m": json.dumps(meta),
                    "s": meta.get("source"),
                    "fs": meta.get("file_size"),
                }
            )
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {TABLE} "
                    "(id, collection_name, text, embedding, metadata, source, file_size) "
                    "VALUES (:id, :c, :t, (:e)::vector, (:m)::jsonb, :s, :fs)"
                ),
                rows,
            )
        return ids

    def search(
        self,
        collection_name: str,
        query: str,
        limit: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[SearchResult]:
        query_embedding = self.embedding_service.embed_text(query)
        params = {
            "c": collection_name,
            "e": _vec_literal(query_embedding),
            "k": limit,
        }
        filter_sql = ""
        if metadata_filter:
            filter_sql = " AND metadata @> (:mf)::jsonb"
            params["mf"] = json.dumps(metadata_filter)
        sql = (
            f"SELECT id, text, metadata, (embedding <=> (:e)::vector) AS distance "
            f"FROM {TABLE} WHERE collection_name = :c{filter_sql} "
            "ORDER BY embedding <=> (:e)::vector LIMIT :k"
        )
        with self.engine.connect() as conn:
            result_rows = conn.execute(text(sql), params).fetchall()

        results = []
        for r in result_rows:
            meta = dict(r.metadata) if r.metadata else {}
            results.append(
                SearchResult(
                    id=str(r.id),
                    text=r.text or "",
                    score=1.0 - float(r.distance),
                    metadata=meta,
                )
            )
        return results

    def delete_points(self, collection_name: str, point_ids: list[str]) -> bool:
        if not point_ids:
            return True
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"DELETE FROM {TABLE} "
                    "WHERE collection_name = :c AND id = ANY(:ids)"
                ),
                {"c": collection_name, "ids": [str(p) for p in point_ids]},
            )
        return True

    def delete_point(self, collection_name: str, point_id: str) -> bool:
        return self.delete_points(collection_name, [point_id])

    def delete_by_source(self, collection_name: str, source: str) -> int:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"DELETE FROM {TABLE} "
                    "WHERE collection_name = :c AND source = :s"
                ),
                {"c": collection_name, "s": source},
            )
        return 1

    def find_existing_files(
        self,
        collection_name: str,
        files: list[tuple[str, int]],
    ) -> list[ExistingFile]:
        if not files:
            return []
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT source, file_size, COUNT(*) AS chunk_count "
                    f"FROM {TABLE} WHERE collection_name = :c AND source IS NOT NULL "
                    "GROUP BY source, file_size"
                ),
                {"c": collection_name},
            ).fetchall()
        counts = {(r.source, r.file_size): r.chunk_count for r in rows}
        existing = []
        for filename, size in files:
            chunk_count = counts.get((filename, size))
            if chunk_count:
                existing.append(
                    ExistingFile(source=filename, file_size=size, chunk_count=chunk_count)
                )
        return existing

    def clone_collection(
        self,
        source_collection: str,
        target_collection: str,
        batch_size: int = 100,
    ) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                text(
                    f"INSERT INTO {TABLE} "
                    "(id, collection_name, text, embedding, metadata, source, file_size) "
                    "SELECT gen_random_uuid(), :tgt, text, embedding, metadata, source, file_size "
                    f"FROM {TABLE} WHERE collection_name = :src"
                ),
                {"tgt": target_collection, "src": source_collection},
            )
        return result.rowcount or 0

    def list_items(
        self,
        collection_name: str,
        limit: int = 100,
        text_truncate_length: int = 200,
    ) -> tuple[list[VectorStoreSourceGroup], int]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, text, metadata, source, file_size "
                    f"FROM {TABLE} WHERE collection_name = :c LIMIT :k"
                ),
                {"c": collection_name, "k": limit},
            ).fetchall()

        source_groups: dict[str, VectorStoreSourceGroup] = {}
        total_items = 0
        for r in rows:
            total_items += 1
            meta = dict(r.metadata) if r.metadata else {}
            text_value = r.text or ""
            source = r.source or "Unknown"
            file_size = r.file_size
            truncated = (
                text_value[:text_truncate_length] + "..."
                if len(text_value) > text_truncate_length
                else text_value
            )
            item = VectorStoreItem(
                id=str(r.id),
                text=truncated,
                source=source,
                file_size=file_size,
                metadata=meta,
            )
            if source not in source_groups:
                source_groups[source] = VectorStoreSourceGroup(
                    source=source, file_size=file_size, chunk_count=0, items=[]
                )
            source_groups[source].chunk_count += 1
            source_groups[source].items.append(item)

        sorted_groups = sorted(
            source_groups.values(),
            key=lambda g: g.source.lower() if g.source else "",
        )
        return sorted_groups, total_items
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_vector_store_pg.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/vector_store_pg.py backend/tests/test_vector_store_pg.py
git commit -m "feat(vector-store): add PgVectorStoreService backend"
```

---

### Task 8: Add the backend factory keyed on credential type

**Files:**
- Modify: `backend/app/services/vector_store.py` (add factory)
- Test: `backend/tests/test_pgvector_credential_and_factory.py` (extend)

- [ ] **Step 1: Write the failing factory test**

Append to `backend/tests/test_pgvector_credential_and_factory.py`:

```python
from unittest.mock import patch


class TestVectorStoreFactory(unittest.TestCase):
    def test_qdrant_credential_returns_qdrant_service(self):
        from app.services.vector_store import (
            QdrantVectorStoreService,
            create_vector_store_service_for_credential,
        )

        config = {
            "qdrant_host": "localhost",
            "qdrant_port": 6333,
            "openai_api_key": "sk-test",
        }
        svc = create_vector_store_service_for_credential("qdrant", config)
        self.assertIsInstance(svc, QdrantVectorStoreService)

    def test_pgvector_credential_returns_pg_service(self):
        with patch("app.services.vector_store_pg.EmbeddingService"):
            from app.services.vector_store import create_vector_store_service_for_credential
            from app.services.vector_store_pg import PgVectorStoreService

            svc = create_vector_store_service_for_credential(
                "pgvector", {"openai_api_key": "sk-test"}
            )
            self.assertIsInstance(svc, PgVectorStoreService)

    def test_unknown_type_raises(self):
        from app.services.vector_store import create_vector_store_service_for_credential

        with self.assertRaises(ValueError):
            create_vector_store_service_for_credential("nope", {})
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_pgvector_credential_and_factory.py::TestVectorStoreFactory -v
```
Expected: FAIL — `create_vector_store_service_for_credential` does not exist.

- [ ] **Step 3: Implement the factory**

At the bottom of `backend/app/services/vector_store.py`, add:

```python
def create_vector_store_service_for_credential(
    credential_type: str,
    config: dict,
) -> "VectorStoreBackend":
    """Build the vector store backend implied by the credential type."""
    type_str = (
        credential_type.value
        if hasattr(credential_type, "value")
        else str(credential_type)
    )
    if type_str == "qdrant":
        return QdrantVectorStoreService(
            qdrant_host=config.get("qdrant_host", "localhost"),
            qdrant_port=int(config.get("qdrant_port", 6333)),
            qdrant_api_key=config.get("qdrant_api_key"),
            openai_api_key=config["openai_api_key"],
        )
    if type_str == "pgvector":
        from app.services.vector_store_pg import PgVectorStoreService

        return PgVectorStoreService(openai_api_key=config["openai_api_key"])
    raise ValueError(f"Unsupported vector store credential type: {type_str}")
```

- [ ] **Step 4: Run to verify passing**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_pgvector_credential_and_factory.py -v
```
Expected: PASS (all classes).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/vector_store.py backend/tests/test_pgvector_credential_and_factory.py
git commit -m "feat(vector-store): add credential-type backend factory"
```

---

## Phase D — API wiring

### Task 9: Accept pgvector credentials and expose backend in the API

**Files:**
- Modify: `backend/app/api/vector_stores.py:89-105` (cred check + service builder)
- Modify: `backend/app/models/schemas.py` (add `backend` to list/response models)

- [ ] **Step 1: Accept pgvector in `get_credential_config`**

In `backend/app/api/vector_stores.py`, replace the type guard near line 89:

```python
    if credential.type not in (CredentialType.qdrant, CredentialType.pgvector):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be a vector store credential (Qdrant or Postgres)",
        )
```

- [ ] **Step 2: Build the service via the factory**

Replace `get_vector_store_service_from_config` (lines ~99-105) so it takes the credential type. Update its two-line body:

```python
def get_vector_store_service_from_config(config: dict, credential_type):
    from app.services.vector_store import create_vector_store_service_for_credential

    return create_vector_store_service_for_credential(credential_type, config)
```

Then update every call site in this file (there are several: `_get_store_stats`, `create_vector_store`, `delete_vector_store`, `clone_vector_store`, `check_duplicate_files`, `upload_file_to_vector_store`, `list_vector_store_items`, `delete_items_by_source`, `delete_item`) to pass the credential's type. Each already has the `credential` object in scope; pass `credential.type`. For `create_vector_store` and `clone_vector_store`, the `credential` returned by `get_credential_config` is used — pass `credential.type`.

Example for `_get_store_stats`:
```python
        service = get_vector_store_service_from_config(config, credential.type)
```

- [ ] **Step 3: Replace Qdrant-specific error strings**

In `create_vector_store` and `clone_vector_store`, change `"Failed to create QDrant collection"` / `"Failed to clone QDrant collection"` to `"Failed to create vector store collection"` / `"Failed to clone vector store collection"`.

- [ ] **Step 4: Add `backend` to response schemas**

In `backend/app/models/schemas.py`, add `backend: str = "qdrant"` to `VectorStoreListResponse` and `VectorStoreResponse`. In `backend/app/api/vector_stores.py`, when constructing these responses, set `backend=...` derived from the store's credential type. Add a small helper near the top:

```python
async def _store_backend(store: VectorStore, db: AsyncSession) -> str:
    result = await db.execute(select(Credential).where(Credential.id == store.credential_id))
    credential = result.scalar_one_or_none()
    if credential and credential.type == CredentialType.pgvector:
        return "pgvector"
    return "qdrant"
```

Use it in `list_vector_stores` (per store), `get_vector_store`, `create_vector_store` (you already have `credential`), and `update_vector_store`/`clone_vector_store`. For `create_vector_store` set `backend="pgvector" if credential.type == CredentialType.pgvector else "qdrant"` directly (credential already loaded — avoid an extra query).

- [ ] **Step 5: Run the API/vector-store tests**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "vector_store" -v
```
Expected: PASS. Fix any call site that still calls `get_vector_store_service_from_config(config)` with one arg (TypeError).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/vector_stores.py backend/app/models/schemas.py
git commit -m "feat(api): support pgvector vector stores and expose backend field"
```

---

## Phase E — RAG node (canvas + executor)

### Task 10: RAG node data — add dbType, relabel

**Files:**
- Modify: `frontend/src/types/node.ts:470-487`

- [ ] **Step 1: Update the RAG node definition**

In `frontend/src/types/node.ts`, change the `rag` node:

```typescript
  rag: {
    type: "rag",
    label: "RAG / Vector Store",
    description: "Insert or search documents in a Qdrant or Postgres vector store",
    color: "node-rag",
    icon: "Search",
    inputs: 1,
    outputs: 1,
    defaultData: {
      label: "rag",
      dbType: "qdrant",
      vectorStoreId: "",
      ragOperation: undefined,
      documentContent: "$input.text",
      documentMetadata: "{}",
      queryText: "$input.text",
      searchLimit: 5,
      metadataFilters: "{}",
    },
  },
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && bun run typecheck
```
Expected: pass. If the node data type is a strict interface, add `dbType?: "qdrant" | "pgvector"` to the RAG node data type definition wherever node data fields are typed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/node.ts
git commit -m "feat(ui): add dbType to RAG node and relabel"
```

---

### Task 11: RAG node config — DB-type dropdown and backend filtering

**Files:**
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue`
- Modify: `frontend/src/services/api.ts` (vector store list type — add `backend`)

- [ ] **Step 1: Add `backend` to the vector store list type and mapping**

In `frontend/src/services/api.ts`, find the vector store list response type and add `backend: string` (or `"qdrant" | "pgvector"`). In `PropertiesPanel.vue` line ~833 the mapping is:

```typescript
        vectorStores.value = stores.map((s) => ({ id: s.id, name: s.name, backend: s.backend }));
```

Update the `vectorStores` ref type (line ~493) to:

```typescript
const vectorStores = ref<{ id: string; name: string; backend: string }[]>([]);
```

- [ ] **Step 2: Add the DB-type options and filter the store options**

In `PropertiesPanel.vue`, near `ragOperationOptions` (~line 3980) add:

```typescript
const ragDbTypeOptions = [
  { value: "qdrant", label: "Qdrant" },
  { value: "pgvector", label: "Postgres (pgvector)" },
];
```

Change `vectorStoreOptions` (~line 3970) to filter by the node's `dbType` (default `"qdrant"`):

```typescript
const vectorStoreOptions = computed(() => {
  const node = selectedNode.value;
  const dbType =
    node && node.type === "rag"
      ? ((node.data.dbType as string | undefined) || "qdrant")
      : "qdrant";
  return [
    { value: "", label: "Select a vector store" },
    ...vectorStores.value
      .filter((s) => s.backend === dbType)
      .map((s) => ({ value: s.id, label: s.name })),
  ];
});
```

- [ ] **Step 3: Render the dropdown and reset the store on change**

In the RAG template block (`v-if="selectedNode.type === 'rag'"`, ~line 10153), above the existing "Vector Store" Label/select, add a Database-type select bound to `selectedNode.data.dbType`. When it changes, clear the selected store so a stale cross-backend id is not kept:

```vue
<Label>Database</Label>
<SelectComponent
  :model-value="selectedNode.data.dbType || 'qdrant'"
  :options="ragDbTypeOptions"
  @update:model-value="
    updateNodeData('dbType', $event);
    updateNodeData('vectorStoreId', '');
  "
/>
```

Use the same select component the existing Vector Store / operation selects use (match the tag and props already present at lines ~10157 and ~10179; do not introduce a new component).

- [ ] **Step 4: Lint and typecheck**

```bash
cd frontend && bun run lint && bun run typecheck
```
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Panels/PropertiesPanel.vue frontend/src/services/api.ts
git commit -m "feat(ui): add RAG node database-type dropdown with backend filtering"
```

---

### Task 12: Executor RAG branch uses the factory

**Files:**
- Modify: `backend/app/services/workflow_executor.py:8111-8143`
- Test: `backend/tests/test_pgvector_credential_and_factory.py` (extend)

- [ ] **Step 1: Write the failing executor test**

Append to `backend/tests/test_pgvector_credential_and_factory.py`:

```python
from unittest.mock import MagicMock


class TestExecutorRagPgvector(unittest.TestCase):
    def test_rag_search_uses_pg_backend_for_pgvector_credential(self):
        """The RAG branch must build the backend from the store's credential type."""
        from app.services.vector_store import create_vector_store_service_for_credential
        from app.services.vector_store_pg import PgVectorStoreService

        with patch("app.services.vector_store_pg.EmbeddingService"):
            svc = create_vector_store_service_for_credential(
                "pgvector", {"openai_api_key": "sk-test"}
            )
        self.assertIsInstance(svc, PgVectorStoreService)
        # collection_exists is True without a DB round-trip for pgvector
        self.assertTrue(svc.collection_exists("col"))
```

(This guards the factory contract the executor now depends on; a full executor integration test would require a live DB and is covered by E2E.)

- [ ] **Step 2: Run to verify it passes against current factory**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_pgvector_credential_and_factory.py::TestExecutorRagPgvector -v
```
Expected: PASS (factory already exists from Task 8). This locks the contract before refactoring the executor.

- [ ] **Step 3: Refactor the executor RAG branch**

In `backend/app/services/workflow_executor.py`, in the `elif node_type == "rag":` branch, replace the import and service construction (lines ~8113-8143). Change the import line:

```python
                from app.services.vector_store import (
                    create_vector_store_service_for_credential,
                )
```

Capture the credential type alongside the config:

```python
                qdrant_config: dict = {}
                credential_type = None
                collection_name: str = ""
                with SessionLocal() as db:
                    store = self._get_accessible_vector_store(db, vector_store_id)
                    if not store:
                        raise ValueError("Vector store not found or not accessible")
                    collection_name = store.collection_name
                    cred = self._get_vector_store_backing_credential(db, store.credential_id)
                    if cred:
                        qdrant_config = decrypt_config(cred.encrypted_config)
                        credential_type = cred.type

                if not qdrant_config:
                    raise ValueError("Vector store credential not found")

                service = create_vector_store_service_for_credential(
                    credential_type, qdrant_config
                )
```

Leave the rest of the branch (insert/search/reranker handling) unchanged — it only uses the `service` interface methods, which both backends implement.

- [ ] **Step 4: Run executor + factory tests**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "rag or vector_store or pgvector or executor" -v
```
Expected: PASS. Existing Qdrant RAG executor tests still pass (qdrant credential → Qdrant backend, same behavior).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflow_executor.py backend/tests/test_pgvector_credential_and_factory.py
git commit -m "feat(executor): build RAG vector backend from credential type"
```

---

## Phase F — Docs & verification

### Task 13: Update in-repo documentation

**Files:**
- Modify: `frontend/src/docs/content/nodes/rag-node.md`
- Modify: `frontend/src/docs/content/tabs/vectorstores-tab.md`
- Modify: `frontend/src/docs/content/tabs/credentials-tab.md`
- Modify: `frontend/src/docs/content/reference/credentials.md`
- Modify: `frontend/src/docs/content/reference/integrations.md`
- Modify: `frontend/src/docs/content/reference/features.md`
- Modify: `frontend/src/docs/content/reference/node-types.md`
- Modify: `frontend/src/docs/content/reference/credentials-sharing.md`
- Modify: `frontend/src/docs/content/getting-started/why-heym.md`

- [ ] **Step 1: Read each file's Qdrant mentions**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
grep -n -i "qdrant" frontend/src/docs/content/nodes/rag-node.md frontend/src/docs/content/tabs/vectorstores-tab.md frontend/src/docs/content/tabs/credentials-tab.md frontend/src/docs/content/reference/credentials.md frontend/src/docs/content/reference/integrations.md frontend/src/docs/content/reference/features.md frontend/src/docs/content/reference/node-types.md frontend/src/docs/content/reference/credentials-sharing.md frontend/src/docs/content/getting-started/why-heym.md
```

- [ ] **Step 2: Update copy to present Postgres as an option**

For each match, update the surrounding prose so vector storage is described as "Qdrant or Postgres (pgvector)". Specifically:
- `credentials.md` / `credentials-tab.md` / `credentials-sharing.md`: document two RAG credentials — "RAG: Qdrant + OpenAI" and "RAG: Psql + OpenAI" (the Postgres one needs only an OpenAI key; data lives in Heym's own database).
- `rag-node.md` / `node-types.md`: document the RAG node's Database dropdown (Qdrant default, or Postgres), noting it filters vector stores by backend.
- `vectorstores-tab.md`: note that a vector store's backend is determined by its credential.
- `integrations.md` / `features.md` / `why-heym.md`: mention pgvector as a built-in, no-external-service vector option.

Keep edits factual and minimal. Do not invent UI that the implementation does not provide (no per-store backend switching after creation; backend is fixed by the credential).

- [ ] **Step 3: Verify docs build (frontend)**

```bash
cd frontend && bun run typecheck
```
Expected: pass (markdown content changes don't affect types, but this confirms nothing else broke if docs are imported).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/docs/content/
git commit -m "docs: document Postgres/pgvector vector store backend"
```

---

### Task 14: heymweb — sync docs and audit Qdrant-only copy

**Files (separate repo `/Users/mbakgun/Projects/heym/heymweb`):**

- [ ] **Step 1: Sync the docs**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && bun run sync-docs
```
Expected: heymweb docs update from the heymrun `frontend/src/docs/content` source.

- [ ] **Step 2: Audit for Qdrant-only copy**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && grep -rn -i "qdrant" --include="*.tsx" --include="*.ts" --include="*.md" --include="*.mdx" src content 2>/dev/null
```
Review each hit. Where the site states or implies Qdrant is the **only** vector store / RAG backend (landing copy, feature lists, integration pages, blog mentions), update it to present Postgres (pgvector) as a built-in alternative that needs no external service. Leave Qdrant-specific how-to content intact; only fix exclusivity claims.

- [ ] **Step 3: Verify heymweb build**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && bunx tsc --noEmit && bun run build
```
Expected: both pass.

- [ ] **Step 4: Commit (heymweb, do not push without approval)**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && git add -A && git commit -m "docs: add Postgres/pgvector vector backend; fix Qdrant-only copy"
```

---

### Task 15: Full verification

- [ ] **Step 1: Backend checks (format, lint, tests)**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh
```
Expected: ruff format clean, ruff lint clean, frontend lint+typecheck clean, full backend test suite passes. Commit any formatting-only diffs.

- [ ] **Step 2: Migrations apply cleanly from scratch path**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run alembic upgrade head
```
Expected: `head` reached, no errors.

- [ ] **Step 3: Manual smoke test**

Start the app (`./run.sh`), then:
1. Credentials → create "RAG: Psql + OpenAI" (only OpenAI key requested).
2. Vector Stores → create a store using that credential; upload a small `.txt`.
3. New workflow → RAG node → Database dropdown shows "Postgres (pgvector)"; selecting it filters to the new store. Run a Search operation → results returned.
4. Confirm an existing Qdrant store + RAG node still works unchanged (default Qdrant).

- [ ] **Step 4: Final commit (if any formatting diffs)**

```bash
git add -A && git commit -m "chore: formatting after pgvector backend" || echo "nothing to commit"
```

---

## Self-Review Notes

- **Spec coverage:** infra (Task 1-2), pgvector credential (Task 3-5), service interface + impl + factory (Task 6-8), API (Task 9), RAG node UI + executor (Task 10-12), docs incl. heymweb audit (Task 13-14), verification (Task 15). All spec sections mapped.
- **Backward compatibility:** node `dbType` defaults `"qdrant"`; dropdown default Qdrant; `backend` response field defaults `"qdrant"`; `VectorStoreService` alias keeps old imports; existing Qdrant executor path unchanged.
- **Type consistency:** factory `create_vector_store_service_for_credential(credential_type, config)`; service class `PgVectorStoreService(openai_api_key, engine=None)`; `SearchResult.score = 1 - distance`; response field `backend`; node field `dbType`. Names consistent across tasks.
- **No external DB:** `PgVectorStoreService` uses `app.db.session.sync_engine` only.
