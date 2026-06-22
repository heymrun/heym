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

BACKEND_UNAVAILABLE_MSG = (
    "Postgres vector backend is unavailable: the pgvector extension and the "
    "vector_store_items table are not present in this database. pgvector is "
    "opt-in — install the pgvector extension on your Postgres and run "
    "'alembic upgrade head', or use Qdrant. (Qdrant RAG is unaffected.)"
)


class VectorStoreBackendUnavailableError(ValueError):
    """Raised when a pgvector operation is attempted but the backend table is missing."""


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

    def _table_exists(self) -> bool:
        with self.engine.connect() as conn:
            return bool(
                conn.exec_driver_sql(
                    "SELECT to_regclass('public.vector_store_items') IS NOT NULL"
                ).scalar()
            )

    def _require_backend(self) -> None:
        if not self._table_exists():
            raise VectorStoreBackendUnavailableError(BACKEND_UNAVAILABLE_MSG)

    def create_collection(self, collection_name: str) -> bool:
        # Validate the backend is provisioned so a store cannot be created on a
        # database where pgvector operations would later fail.
        self._require_backend()
        return True

    def collection_exists(self, collection_name: str) -> bool:
        return self._table_exists()

    def delete_collection(self, collection_name: str) -> bool:
        if not self._table_exists():
            return True
        with self.engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {TABLE} WHERE collection_name = :c"),
                {"c": collection_name},
            )
        return True

    def get_collection_stats(self, collection_name: str) -> CollectionStats | None:
        if not self._table_exists():
            return None
        with self.engine.connect() as conn:
            count = (
                conn.execute(
                    text(f"SELECT COUNT(*) FROM {TABLE} WHERE collection_name = :c"),
                    {"c": collection_name},
                ).scalar()
                or 0
            )
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
        text: str,
        metadata: dict | None = None,
        point_id: str | None = None,
    ) -> str:
        self._require_backend()
        embedding = self.embedding_service.embed_text(text)
        pid = point_id or str(uuid.uuid4())
        meta = dict(metadata or {})
        source = meta.get("source")
        file_size = meta.get("file_size")
        with self.engine.begin() as conn:
            conn.execute(
                self._insert_stmt(),
                {
                    "id": pid,
                    "c": collection_name,
                    "t": text,
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
        self._require_backend()
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
            conn.execute(self._insert_stmt(), rows)
        return ids

    @staticmethod
    def _insert_stmt():
        return text(
            f"INSERT INTO {TABLE} "
            "(id, collection_name, text, embedding, metadata, source, file_size) "
            "VALUES (:id, :c, :t, (:e)::vector, (:m)::jsonb, :s, :fs)"
        )

    def search(
        self,
        collection_name: str,
        query: str,
        limit: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[SearchResult]:
        self._require_backend()
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
            "SELECT id, text, metadata, (embedding <=> (:e)::vector) AS distance "
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
                text(f"DELETE FROM {TABLE} WHERE collection_name = :c AND id::text = ANY(:ids)"),
                {"c": collection_name, "ids": [str(p) for p in point_ids]},
            )
        return True

    def delete_point(self, collection_name: str, point_id: str) -> bool:
        return self.delete_points(collection_name, [point_id])

    def delete_by_source(self, collection_name: str, source: str) -> int:
        if not self._table_exists():
            return 0
        with self.engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {TABLE} WHERE collection_name = :c AND source = :s"),
                {"c": collection_name, "s": source},
            )
        return 1

    def find_existing_files(
        self,
        collection_name: str,
        files: list[tuple[str, int]],
    ) -> list[ExistingFile]:
        if not files or not self._table_exists():
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
        if not self._table_exists():
            return 0
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
        if not self._table_exists():
            return [], 0
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
