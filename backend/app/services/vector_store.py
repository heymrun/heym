import json
import uuid
from dataclasses import dataclass, field

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.services.embedding import EMBEDDING_DIMENSIONS, EmbeddingService

QDRANT_PAYLOAD_LIMIT_BYTES = 30 * 1024 * 1024


@dataclass
class SearchResult:
    id: str
    text: str
    score: float
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


class VectorStoreService:
    def __init__(
        self,
        qdrant_host: str,
        qdrant_port: int,
        qdrant_api_key: str | None,
        openai_api_key: str,
    ):
        if qdrant_api_key:
            self.client = QdrantClient(
                host=qdrant_host,
                port=qdrant_port,
                api_key=qdrant_api_key,
            )
        else:
            self.client = QdrantClient(
                host=qdrant_host,
                port=qdrant_port,
            )
        self.embedding_service = EmbeddingService(openai_api_key)

    def create_collection(self, collection_name: str) -> bool:
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=EMBEDDING_DIMENSIONS,
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

        info = self.client.get_collection(collection_name)
        return CollectionStats(
            vector_count=info.vectors_count or 0,
            indexed_vectors_count=info.indexed_vectors_count or 0,
            points_count=info.points_count or 0,
            segments_count=len(info.segments) if info.segments else 0,
            status=str(info.status),
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

        search_filter = None
        if metadata_filter:
            conditions = []
            for key, value in metadata_filter.items():
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value),
                    )
                )
            if conditions:
                search_filter = Filter(must=conditions)

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

    def delete_points(self, collection_name: str, point_ids: list[str]) -> bool:
        self.client.delete(
            collection_name=collection_name,
            points_selector=point_ids,
        )
        return True

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

        delete_filter = Filter(
            must=[
                FieldCondition(
                    key="source",
                    match=MatchValue(value=source),
                )
            ]
        )

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
                source = payload.get("source", "Unknown")
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


def create_vector_store_service(
    qdrant_host: str,
    qdrant_port: int,
    qdrant_api_key: str | None,
    openai_api_key: str,
) -> VectorStoreService:
    return VectorStoreService(
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        qdrant_api_key=qdrant_api_key,
        openai_api_key=openai_api_key,
    )
