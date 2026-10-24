import json
import uuid

from sqlalchemy import text

from app.services.embedding import EMBEDDING_DIMENSIONS, EmbeddingConfig, EmbeddingService
from app.services.vector_store import (
    CollectionStats,
    ExistingFile,
    HybridSearchResult,
    LexicalDoc,
    SearchResult,
    VectorStoreItem,
    VectorStoreSourceGroup,
    upsert_payload_metadata,
    upsert_point_id,
)

TABLE = "vector_store_items"

# The keyword leg of hybrid search reads this expression, and migration
# 142_vsi_text_search_index indexes it: change one and the index stops being used.
# Punctuation becomes a space first, so "ERR-4021" yields the words `err` and `4021` that
# hybrid_search.tokenize() produces; Postgres' own parser would keep `-4021` as a number.
# `left` keeps a pathological document under tsvector's 1 MB limit.
TEXT_SEARCH_SQL = r"to_tsvector('simple', regexp_replace(left(text, 200000), '(\W|_)+', ' ', 'g'))"

BACKEND_UNAVAILABLE_MSG = (
    "Postgres vector backend is unavailable: the pgvector extension and the "
    "vector_store_items table are not present in this database. pgvector is "
    "opt-in — install the pgvector extension on your Postgres and run "
    "'alembic upgrade head', or use Qdrant. (Qdrant RAG is unaffected.)"
)


def pgvector_dimension_message(dimensions: int) -> str:
    """Explain why a non-1536 embedding width cannot use the pgvector backend."""
    return (
        f"Postgres (pgvector) stores vectors in a fixed vector({EMBEDDING_DIMENSIONS}) "
        f"column, but this credential is configured for {dimensions} dimensions. Use an "
        f"embedding model that returns {EMBEDDING_DIMENSIONS} dimensions, or select "
        f"Qdrant as the vector store."
    )


class VectorStoreBackendUnavailableError(ValueError):
    """Raised when a pgvector operation is attempted but the backend table is missing."""


def _vec_literal(embedding: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


class PgLexicalSource:
    """Keyword leg of hybrid search, answered from Postgres full-text search on ``text``."""

    def __init__(self, engine) -> None:
        self.engine = engine

    def corpus_size(self, collection_name: str) -> int:
        with self.engine.connect() as conn:
            return (
                conn.execute(
                    text(f"SELECT COUNT(*) FROM {TABLE} WHERE collection_name = :c"),
                    {"c": collection_name},
                ).scalar()
                or 0
            )

    def document_frequencies(self, collection_name: str, terms: list[str]) -> dict[str, int]:
        sql = text(
            "SELECT t.term AS term, "
            f"(SELECT COUNT(*) FROM {TABLE} WHERE collection_name = :c "
            f"AND {TEXT_SEARCH_SQL} @@ plainto_tsquery('simple', t.term)) AS df "
            "FROM unnest(CAST(:terms AS text[])) AS t(term)"
        )
        with self.engine.connect() as conn:
            rows = conn.execute(sql, {"c": collection_name, "terms": terms}).fetchall()
        return {row.term: int(row.df) for row in rows}

    def candidates(
        self,
        collection_name: str,
        terms: list[str],
        limit: int,
        metadata_filter: dict | None,
    ) -> list[LexicalDoc]:
        params: dict = {"c": collection_name, "k": limit}
        tsquery_parts = []
        for i, term in enumerate(terms):
            params[f"t{i}"] = term
            tsquery_parts.append(f"plainto_tsquery('simple', :t{i})")
        tsquery = " || ".join(tsquery_parts)
        filter_sql = ""
        if metadata_filter:
            filter_sql = " AND metadata @> (:mf)::jsonb"
            params["mf"] = json.dumps(metadata_filter)
        sql = text(
            f"SELECT id, text, metadata FROM {TABLE} "
            f"WHERE collection_name = :c AND {TEXT_SEARCH_SQL} @@ ({tsquery}){filter_sql} "
            f"ORDER BY ts_rank_cd({TEXT_SEARCH_SQL}, ({tsquery})) DESC LIMIT :k"
        )
        with self.engine.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            LexicalDoc(
                id=str(row.id),
                text=row.text or "",
                metadata=dict(row.metadata) if row.metadata else {},
            )
            for row in rows
        ]


class PgVectorStoreService:
    """pgvector backend. Stores embeddings in Heym's own Postgres DB.

    All rows live in one shared table partitioned by ``collection_name``.
    The VectorStore row is the source of truth for existence, so
    ``create_collection`` is a no-op and ``collection_exists`` returns True.
    """

    def __init__(
        self,
        openai_api_key: str | None = None,
        engine=None,
        embedding_config: EmbeddingConfig | None = None,
    ):
        if engine is None:
            from app.db.session import sync_engine

            engine = sync_engine
        self.engine = engine
        if embedding_config is None:
            embedding_config = EmbeddingConfig(api_key=openai_api_key)
        if embedding_config.dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(pgvector_dimension_message(embedding_config.dimensions))
        self.embedding_service = EmbeddingService(embedding_config)

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

    def hybrid_search(
        self,
        collection_name: str,
        query: str,
        limit: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[HybridSearchResult]:
        """Vector search fused with BM25 keyword matches over the stored text."""
        from app.services.hybrid_search import hybrid_pool_size, run_hybrid_search

        dense = self.search(
            collection_name,
            query,
            limit=hybrid_pool_size(limit),
            metadata_filter=metadata_filter,
        )
        return run_hybrid_search(
            PgLexicalSource(self.engine), collection_name, query, dense, limit, metadata_filter
        )

    def upsert_by_field(
        self,
        collection_name: str,
        id_field: str,
        id_value: str,
        text: str,
        metadata: dict | None = None,
    ) -> tuple[str, int]:
        self._require_backend()
        embedding = self.embedding_service.embed_text(text)
        meta = upsert_payload_metadata(metadata, id_field, id_value)
        point_id = upsert_point_id(collection_name, id_field, id_value)
        # Replace and insert in one transaction so a failed embed/insert cannot
        # leave the collection without the document it was asked to update.
        with self.engine.begin() as conn:
            replaced = (
                conn.execute(
                    self._delete_by_field_stmt(),
                    {"c": collection_name, "mf": json.dumps({id_field: id_value})},
                ).rowcount
                or 0
            )
            conn.execute(
                self._insert_stmt(),
                {
                    "id": point_id,
                    "c": collection_name,
                    "t": text,
                    "e": _vec_literal(embedding),
                    "m": json.dumps(meta),
                    "s": meta.get("source"),
                    "fs": meta.get("file_size"),
                },
            )
        return point_id, replaced

    def delete_by_field(self, collection_name: str, id_field: str, id_value: str) -> int:
        if not self._table_exists():
            return 0
        with self.engine.begin() as conn:
            result = conn.execute(
                self._delete_by_field_stmt(),
                {"c": collection_name, "mf": json.dumps({id_field: id_value})},
            )
        return result.rowcount or 0

    @staticmethod
    def _delete_by_field_stmt():
        return text(f"DELETE FROM {TABLE} WHERE collection_name = :c AND metadata @> (:mf)::jsonb")

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
        # An empty source addresses the points that carry no source at all — the group
        # the UI lists separately, whose column is NULL rather than blank.
        params: dict = {"c": collection_name}
        if source:
            where = "source = :s"
            params["s"] = source
        else:
            where = "source IS NULL OR source = ''"
        with self.engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {TABLE} WHERE collection_name = :c AND ({where})"),
                params,
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
            source = r.source or ""
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
