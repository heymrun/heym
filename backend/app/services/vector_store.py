import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    HasIdCondition,
    IsEmptyCondition,
    MatchText,
    MatchValue,
    PayloadField,
    PointStruct,
    TextIndexParams,
    TextIndexType,
    TokenizerType,
    VectorParams,
)

from app.services.embedding import (
    EmbeddingConfig,
    EmbeddingService,
    embedding_config_from_credential,
)

logger = logging.getLogger(__name__)

QDRANT_PAYLOAD_LIMIT_BYTES = 30 * 1024 * 1024

# Vector store backends a `rag` credential can target.
VECTOR_STORE_BACKENDS = ("qdrant", "pgvector")

# Namespace for point ids derived from a payload id field. Fixed forever: changing
# it would make every previously upserted document unreachable by its own id.
UPSERT_ID_NAMESPACE = uuid.UUID("1b3f0c5e-9f1a-4d6b-8c2e-5a7d4f10b921")

DEFAULT_DOCUMENT_ID_FIELD = "doc_id"

# A document stored by a workflow that named no source of its own gets the workflow as
# its source. The prefix keeps it apart from an uploaded filename, and lets the
# Vectorstores tab say which workflow wrote the group. Mirrored in VectorStoresPanel.vue.
WORKFLOW_SOURCE_PREFIX = "workflow:"


def upsert_point_id(collection_name: str, id_field: str, id_value: str) -> str:
    """Stable point id for a document addressed by a payload field."""
    return str(uuid.uuid5(UPSERT_ID_NAMESPACE, f"{collection_name}\x00{id_field}\x00{id_value}"))


def upsert_payload_metadata(metadata: dict | None, id_field: str, id_value: str) -> dict:
    """Metadata with the id field forced to the addressed value."""
    meta = dict(metadata or {})
    meta[id_field] = id_value
    return meta


@dataclass
class SearchResult:
    id: str
    text: str
    score: float
    metadata: dict = field(default_factory=dict)


@dataclass
class HybridSearchResult(SearchResult):
    """A fused hit: ``score`` is the 0-1 rank fusion, the two source scores stay visible.

    A score is ``None`` when that leg did not return the document.
    """

    vector_score: float | None = None
    keyword_score: float | None = None


@dataclass
class LexicalDoc:
    """A stored document as the keyword leg of hybrid search sees it."""

    id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class CollectionStats:
    vector_count: int
    indexed_vectors_count: int
    points_count: int
    segments_count: int
    status: str


@dataclass
class ExistingFile:
    source: str
    file_size: int
    chunk_count: int


@dataclass
class VectorStoreItem:
    id: str
    text: str
    source: str | None
    file_size: int | None
    metadata: dict


@dataclass
class VectorStoreSourceGroup:
    source: str
    file_size: int | None
    chunk_count: int
    items: list[VectorStoreItem]


class VectorStoreBackend(Protocol):
    """Common interface implemented by every vector store backend."""

    def create_collection(self, collection_name: str) -> bool: ...
    def delete_collection(self, collection_name: str) -> bool: ...
    def collection_exists(self, collection_name: str) -> bool: ...
    def get_collection_stats(self, collection_name: str) -> CollectionStats | None: ...
    def insert(
        self,
        collection_name: str,
        text: str,
        metadata: dict | None = None,
        point_id: str | None = None,
    ) -> str: ...
    def insert_batch(
        self,
        collection_name: str,
        texts: list[str],
        metadata_list: list[dict] | None = None,
    ) -> list[str]: ...
    def search(
        self,
        collection_name: str,
        query: str,
        limit: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[SearchResult]: ...
    def hybrid_search(
        self,
        collection_name: str,
        query: str,
        limit: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[HybridSearchResult]: ...
    def delete_points(self, collection_name: str, point_ids: list[str]) -> bool: ...
    def upsert_by_field(
        self,
        collection_name: str,
        id_field: str,
        id_value: str,
        text: str,
        metadata: dict | None = None,
    ) -> tuple[str, int]: ...
    def delete_by_field(
        self,
        collection_name: str,
        id_field: str,
        id_value: str,
    ) -> int: ...
    def find_existing_files(
        self,
        collection_name: str,
        files: list[tuple[str, int]],
    ) -> list[ExistingFile]: ...
    def delete_by_source(self, collection_name: str, source: str) -> int: ...
    def clone_collection(
        self,
        source_collection: str,
        target_collection: str,
        batch_size: int = 100,
    ) -> int: ...
    def list_items(
        self,
        collection_name: str,
        limit: int = 100,
        text_truncate_length: int = 200,
    ) -> tuple[list[VectorStoreSourceGroup], int]: ...
    def delete_point(self, collection_name: str, point_id: str) -> bool: ...


def _metadata_conditions(metadata_filter: dict | None) -> list[FieldCondition]:
    """Exact-match conditions for a search metadata filter."""
    return [
        FieldCondition(key=key, match=MatchValue(value=value))
        for key, value in (metadata_filter or {}).items()
    ]


class QdrantLexicalSource:
    """Keyword leg of hybrid search, answered from Qdrant's full-text index on ``text``."""

    TEXT_FIELD = "text"

    def __init__(self, client: QdrantClient) -> None:
        self.client = client

    def ensure_text_index(self, collection_name: str) -> None:
        """Index the ``text`` payload so term lookups use tokens instead of scanning substrings.

        Collections created before hybrid search have none; Qdrant builds it from the
        points already stored, so no re-indexing is needed.
        """
        try:
            info = self.client.get_collection(collection_name)
            if self.TEXT_FIELD in (info.payload_schema or {}):
                return
            self.client.create_payload_index(
                collection_name=collection_name,
                field_name=self.TEXT_FIELD,
                field_schema=TextIndexParams(
                    type=TextIndexType.TEXT,
                    tokenizer=TokenizerType.WORD,
                    lowercase=True,
                    min_token_len=1,
                    max_token_len=64,
                ),
                wait=True,
            )
        except Exception:
            # Without the index Qdrant still answers term matches, only slower.
            logger.warning(
                "Could not create the full-text index on %s.%s; hybrid search falls back "
                "to unindexed term matching",
                collection_name,
                self.TEXT_FIELD,
                exc_info=True,
            )

    def _term_filter(self, term: str, metadata_filter: dict | None) -> Filter:
        return Filter(
            must=[
                FieldCondition(key=self.TEXT_FIELD, match=MatchText(text=term)),
                *_metadata_conditions(metadata_filter),
            ]
        )

    def corpus_size(self, collection_name: str) -> int:
        return self.client.count(collection_name, exact=True).count

    def document_frequencies(self, collection_name: str, terms: list[str]) -> dict[str, int]:
        return {
            term: self.client.count(
                collection_name=collection_name,
                count_filter=self._term_filter(term, None),
                exact=True,
            ).count
            for term in terms
        }

    def candidates(
        self,
        collection_name: str,
        terms: list[str],
        limit: int,
        metadata_filter: dict | None,
    ) -> list[LexicalDoc]:
        found: dict[str, LexicalDoc] = {}
        # Qdrant cannot rank a text match, so spend the budget on the rarest terms first:
        # they carry the most BM25 weight and match the fewest documents.
        for term in terms:
            if len(found) >= limit:
                break
            points, _ = self.client.scroll(
                collection_name=collection_name,
                scroll_filter=self._term_filter(term, metadata_filter),
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = dict(point.payload) if point.payload else {}
                text = payload.pop(self.TEXT_FIELD, "")
                found.setdefault(
                    str(point.id), LexicalDoc(id=str(point.id), text=text, metadata=payload)
                )
        return list(found.values())[:limit]


class QdrantVectorStoreService:
    def __init__(
        self,
        qdrant_host: str,
        qdrant_port: int,
        qdrant_api_key: str | None,
        openai_api_key: str | None = None,
        embedding_config: EmbeddingConfig | None = None,
    ):
        if qdrant_api_key:
            self.client = QdrantClient(
                host=qdrant_host,
                port=qdrant_port,
                api_key=qdrant_api_key,
                check_compatibility=False,
            )
        else:
            self.client = QdrantClient(
                host=qdrant_host,
                port=qdrant_port,
                check_compatibility=False,
            )
        if embedding_config is None:
            embedding_config = EmbeddingConfig(api_key=openai_api_key)
        self.embedding_service = EmbeddingService(embedding_config)

    @property
    def embedding_dimensions(self) -> int:
        return self.embedding_service.config.dimensions

    def create_collection(self, collection_name: str) -> bool:
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=self.embedding_dimensions,
                distance=Distance.COSINE,
            ),
        )
        return True

    def delete_collection(self, collection_name: str) -> bool:
        self.client.delete_collection(collection_name=collection_name)
        return True

    def collection_exists(self, collection_name: str) -> bool:
        collections = self.client.get_collections()
        return any(c.name == collection_name for c in collections.collections)

    def get_collection_stats(self, collection_name: str) -> CollectionStats | None:
        if not self.collection_exists(collection_name):
            return None

        # Use the count API for the point total: it is reliable across Qdrant
        # versions, unlike CollectionInfo.vectors_count (deprecated / sometimes
        # removed, which would raise and hide the real count behind "N/A").
        points_count = self.client.count(collection_name, exact=True).count

        status = "green"
        indexed_count = 0
        segments_count = 0
        try:
            info = self.client.get_collection(collection_name)
            status = str(getattr(info, "status", "green"))
            indexed_count = getattr(info, "indexed_vectors_count", None) or 0
            segments = getattr(info, "segments", None)
            segments_count = len(segments) if segments else 0
        except Exception:
            pass

        return CollectionStats(
            vector_count=points_count,
            indexed_vectors_count=indexed_count,
            points_count=points_count,
            segments_count=segments_count,
            status=status,
        )

    def insert(
        self,
        collection_name: str,
        text: str,
        metadata: dict | None = None,
        point_id: str | None = None,
    ) -> str:
        embedding = self.embedding_service.embed_text(text)
        pid = point_id or str(uuid.uuid4())

        payload = {"text": text}
        if metadata:
            payload.update(metadata)

        self.client.upsert(
            collection_name=collection_name,
            points=[
                PointStruct(
                    id=pid,
                    vector=embedding,
                    payload=payload,
                )
            ],
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
        point_ids = []
        points = []

        for i, emb_result in enumerate(embeddings):
            pid = str(uuid.uuid4())
            point_ids.append(pid)

            payload = {"text": emb_result.text}
            if metadata_list and i < len(metadata_list):
                payload.update(metadata_list[i])

            points.append(
                PointStruct(
                    id=pid,
                    vector=emb_result.embedding,
                    payload=payload,
                )
            )

        batch_start = 0
        while batch_start < len(points):
            batch_points = []
            batch_size_bytes = 0

            for j in range(batch_start, len(points)):
                point = points[j]
                point_json = json.dumps(
                    {"id": point.id, "vector": point.vector, "payload": point.payload}
                )
                point_size = len(point_json.encode("utf-8"))

                if batch_size_bytes + point_size > QDRANT_PAYLOAD_LIMIT_BYTES and batch_points:
                    break

                batch_points.append(point)
                batch_size_bytes += point_size
                batch_start = j + 1

            if batch_points:
                self.client.upsert(
                    collection_name=collection_name,
                    points=batch_points,
                )

        return point_ids

    def search(
        self,
        collection_name: str,
        query: str,
        limit: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[SearchResult]:
        query_embedding = self.embedding_service.embed_text(query)

        conditions = _metadata_conditions(metadata_filter)
        search_filter = Filter(must=conditions) if conditions else None

        # Use query_points for qdrant-client >= 1.7
        response = self.client.query_points(
            collection_name=collection_name,
            query=query_embedding,
            limit=limit,
            query_filter=search_filter,
        )

        search_results = []
        for result in response.points:
            payload = dict(result.payload) if result.payload else {}
            text = payload.pop("text", "")
            search_results.append(
                SearchResult(
                    id=str(result.id),
                    text=text,
                    score=result.score,
                    metadata=payload,
                )
            )
        return search_results

    def hybrid_search(
        self,
        collection_name: str,
        query: str,
        limit: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[HybridSearchResult]:
        """Vector search fused with BM25 keyword matches over the stored text."""
        from app.services.hybrid_search import hybrid_pool_size, run_hybrid_search

        source = QdrantLexicalSource(self.client)
        source.ensure_text_index(collection_name)
        dense = self.search(
            collection_name,
            query,
            limit=hybrid_pool_size(limit),
            metadata_filter=metadata_filter,
        )
        return run_hybrid_search(source, collection_name, query, dense, limit, metadata_filter)

    def delete_points(self, collection_name: str, point_ids: list[str]) -> bool:
        self.client.delete(
            collection_name=collection_name,
            points_selector=point_ids,
        )
        return True

    @staticmethod
    def _field_filter(id_field: str, id_value: str) -> Filter:
        return Filter(must=[FieldCondition(key=id_field, match=MatchValue(value=id_value))])

    def _count_by_field(self, collection_name: str, id_field: str, id_value: str) -> int:
        return self.client.count(
            collection_name=collection_name,
            count_filter=self._field_filter(id_field, id_value),
            exact=True,
        ).count

    def upsert_by_field(
        self,
        collection_name: str,
        id_field: str,
        id_value: str,
        text: str,
        metadata: dict | None = None,
    ) -> tuple[str, int]:
        replaced = 0
        if self.collection_exists(collection_name):
            replaced = self._count_by_field(collection_name, id_field, id_value)

        # Embed and write the new point first, then drop the stale ones, so a
        # failed embed cannot leave the collection without the document.
        point_id = upsert_point_id(collection_name, id_field, id_value)
        self.insert(
            collection_name,
            text,
            upsert_payload_metadata(metadata, id_field, id_value),
            point_id=point_id,
        )
        if replaced:
            stale = Filter(
                must=[FieldCondition(key=id_field, match=MatchValue(value=id_value))],
                must_not=[HasIdCondition(has_id=[point_id])],
            )
            self.client.delete(
                collection_name=collection_name,
                points_selector=FilterSelector(filter=stale),
            )
        return point_id, replaced

    def delete_by_field(self, collection_name: str, id_field: str, id_value: str) -> int:
        if not self.collection_exists(collection_name):
            return 0

        matched = self._count_by_field(collection_name, id_field, id_value)
        if not matched:
            return 0

        self.client.delete(
            collection_name=collection_name,
            points_selector=FilterSelector(filter=self._field_filter(id_field, id_value)),
        )
        return matched

    def find_existing_files(
        self,
        collection_name: str,
        files: list[tuple[str, int]],
    ) -> list[ExistingFile]:
        if not files or not self.collection_exists(collection_name):
            return []

        existing = []
        file_dict: dict[str, int] = {}

        offset = None
        while True:
            result = self.client.scroll(
                collection_name=collection_name,
                limit=1000,
                offset=offset,
                with_vectors=False,
                with_payload=True,
            )

            points, next_offset = result

            if not points:
                break

            for point in points:
                if point.payload:
                    source = point.payload.get("source")
                    file_size = point.payload.get("file_size")
                    if source:
                        key = f"{source}:{file_size}"
                        file_dict[key] = file_dict.get(key, 0) + 1

            if next_offset is None:
                break
            offset = next_offset

        for filename, size in files:
            key = f"{filename}:{size}"
            if key in file_dict:
                existing.append(
                    ExistingFile(
                        source=filename,
                        file_size=size,
                        chunk_count=file_dict[key],
                    )
                )

        return existing

    def delete_by_source(self, collection_name: str, source: str) -> int:
        if not self.collection_exists(collection_name):
            return 0

        # An empty source addresses the points that carry no source at all — the group
        # the UI lists separately. Matching "" would match nothing, since the field is
        # absent rather than blank.
        condition = (
            IsEmptyCondition(is_empty=PayloadField(key="source"))
            if not source
            else FieldCondition(key="source", match=MatchValue(value=source))
        )
        delete_filter = Filter(must=[condition])

        self.client.delete(
            collection_name=collection_name,
            points_selector=FilterSelector(filter=delete_filter),
        )

        return 1

    def clone_collection(
        self,
        source_collection: str,
        target_collection: str,
        batch_size: int = 100,
    ) -> int:
        self.create_collection(target_collection)

        if not self.collection_exists(source_collection):
            return 0

        total_copied = 0
        offset = None

        while True:
            result = self.client.scroll(
                collection_name=source_collection,
                limit=batch_size,
                offset=offset,
                with_vectors=True,
                with_payload=True,
            )

            points, next_offset = result

            if not points:
                break

            new_points = []
            for point in points:
                new_points.append(
                    PointStruct(
                        id=point.id,
                        vector=point.vector,
                        payload=point.payload,
                    )
                )

            if new_points:
                self.client.upsert(
                    collection_name=target_collection,
                    points=new_points,
                )
                total_copied += len(new_points)

            if next_offset is None:
                break
            offset = next_offset

        return total_copied

    def list_items(
        self,
        collection_name: str,
        limit: int = 100,
        text_truncate_length: int = 200,
    ) -> tuple[list[VectorStoreSourceGroup], int]:
        if not self.collection_exists(collection_name):
            return [], 0

        source_groups: dict[str, VectorStoreSourceGroup] = {}
        total_items = 0
        offset = None

        while True:
            result = self.client.scroll(
                collection_name=collection_name,
                limit=min(limit, 1000),
                offset=offset,
                with_vectors=False,
                with_payload=True,
            )

            points, next_offset = result

            if not points:
                break

            for point in points:
                total_items += 1
                payload = dict(point.payload) if point.payload else {}
                text = payload.pop("text", "")
                # No source means the point was written by a workflow rather than
                # uploaded; the empty key keeps that group addressable for delete.
                source = payload.get("source") or ""
                file_size = payload.get("file_size")

                truncated_text = (
                    text[:text_truncate_length] + "..."
                    if len(text) > text_truncate_length
                    else text
                )

                item = VectorStoreItem(
                    id=str(point.id),
                    text=truncated_text,
                    source=source,
                    file_size=file_size,
                    metadata=payload,
                )

                if source not in source_groups:
                    source_groups[source] = VectorStoreSourceGroup(
                        source=source,
                        file_size=file_size,
                        chunk_count=0,
                        items=[],
                    )

                source_groups[source].chunk_count += 1
                source_groups[source].items.append(item)

            if next_offset is None:
                break
            offset = next_offset

        sorted_groups = sorted(
            source_groups.values(),
            key=lambda g: g.source.lower() if g.source else "",
        )
        return sorted_groups, total_items

    def delete_point(self, collection_name: str, point_id: str) -> bool:
        if not self.collection_exists(collection_name):
            return False

        self.client.delete(
            collection_name=collection_name,
            points_selector=[point_id],
        )
        return True


# Backward-compatible alias (existing imports use VectorStoreService).
VectorStoreService = QdrantVectorStoreService


def create_vector_store_service(
    qdrant_host: str,
    qdrant_port: int,
    qdrant_api_key: str | None,
    openai_api_key: str,
) -> QdrantVectorStoreService:
    return QdrantVectorStoreService(
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        qdrant_api_key=qdrant_api_key,
        openai_api_key=openai_api_key,
    )


def rag_credential_backend(config: dict) -> str:
    """Vector store backend selected inside a `rag` credential."""
    db_type = str(config.get("db_type") or "qdrant").strip()
    if db_type not in VECTOR_STORE_BACKENDS:
        raise ValueError(f"Unsupported vector store type: {db_type}")
    return db_type


def create_vector_store_service_for_credential(
    credential_type: object,
    config: dict,
) -> VectorStoreBackend:
    """Build the vector store backend implied by the credential type."""
    type_str = credential_type.value if hasattr(credential_type, "value") else str(credential_type)
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
    if type_str == "rag":
        embedding_config = embedding_config_from_credential(config)
        if rag_credential_backend(config) == "pgvector":
            from app.services.vector_store_pg import PgVectorStoreService

            return PgVectorStoreService(embedding_config=embedding_config)
        return QdrantVectorStoreService(
            qdrant_host=config.get("qdrant_host", "localhost"),
            qdrant_port=int(config.get("qdrant_port", 6333)),
            qdrant_api_key=config.get("qdrant_api_key"),
            embedding_config=embedding_config,
        )
    raise ValueError(f"Unsupported vector store credential type: {type_str}")
