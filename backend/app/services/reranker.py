from dataclasses import dataclass, field

import httpx

from app.http_identity import merge_outbound_headers


@dataclass
class RerankResult:
    id: str
    text: str
    original_score: float
    relevance_score: float
    metadata: dict = field(default_factory=dict)


@dataclass
class DocumentToRerank:
    id: str
    text: str
    score: float
    metadata: dict = field(default_factory=dict)


class CohereRerankerService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.cohere.ai/v1"

    def rerank(
        self,
        query: str,
        documents: list[DocumentToRerank],
        top_n: int | None = None,
        model: str = "rerank-v3.5",
    ) -> list[RerankResult]:
        if not documents:
            return []

        if top_n is None:
            top_n = len(documents)

        doc_texts = [doc.text for doc in documents]

        headers = merge_outbound_headers(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

        payload = {
            "model": model,
            "query": query,
            "documents": doc_texts,
            "top_n": min(top_n, len(documents)),
            "return_documents": False,
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{self.base_url}/rerank",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        results = []
        for result in data.get("results", []):
            idx = result["index"]
            original_doc = documents[idx]
            results.append(
                RerankResult(
                    id=original_doc.id,
                    text=original_doc.text,
                    original_score=original_doc.score,
                    relevance_score=result["relevance_score"],
                    metadata=original_doc.metadata,
                )
            )

        return results


def create_reranker_service(api_key: str) -> CohereRerankerService:
    return CohereRerankerService(api_key=api_key)
