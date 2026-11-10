from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.http_identity import merge_outbound_headers
from app.services.decision_models import build_decision_body, call_decision_model
from app.services.llm_trace import LLMTraceContext


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


DECISION_RERANK_TIMEOUT_SECONDS = 60.0
DECISION_RERANK_QUERY_FIELD = "query"
DECISION_RERANK_FINDINGS_FIELD = "findings"

# Lowest first, as the score primitive requires. Each level names its situation in
# full because the decision model reads the text, not the position.
DECISION_RERANK_LEVELS: tuple[str, ...] = (
    "Irrelevant: the finding has nothing to do with the query.",
    "Tangential: the finding shares the topic but does not help answer the query.",
    "Partially relevant: the finding holds some of the information the query asks for.",
    "Highly relevant: the finding holds most of what is needed to answer the query.",
    "Answers it: the finding directly and fully answers the query.",
)


class DecisionRerankError(ValueError):
    """Raised when a decision model answer cannot be turned into relevance scores."""


def decision_rerank_question_id(index: int) -> str:
    """The answer key the decision model scores the finding at `index` under."""
    return f"finding_{index}"


def build_decision_rerank_body(
    *, model: str, query: str, documents: list[DocumentToRerank]
) -> dict[str, Any]:
    """One request that scores every finding against the query with a score question each."""
    questions = [
        {
            "id": decision_rerank_question_id(index),
            "type": "score",
            "instructions": (
                f"How relevant is `{DECISION_RERANK_FINDINGS_FIELD}[{index}]` (item {index} "
                f"of `{DECISION_RERANK_FINDINGS_FIELD}`, counting from 0) to answering "
                f"`{DECISION_RERANK_QUERY_FIELD}`? Judge only this finding and only whether "
                "it helps answer the query."
            ),
            "levels": list(DECISION_RERANK_LEVELS),
        }
        for index in range(len(documents))
    ]
    return build_decision_body(
        model=model,
        state={
            DECISION_RERANK_QUERY_FIELD: query,
            DECISION_RERANK_FINDINGS_FIELD: [doc.text for doc in documents],
        },
        questions=questions,
    )


def read_decision_rerank_scores(payload: object, count: int) -> list[float]:
    """Each finding's relevance on the 0-1 scale Cohere uses, in request order.

    A score answer is a probability-weighted position between the first and the last
    level, so it maps linearly onto 0-1. A missing score fails the whole rerank rather
    than ranking that finding by a guess.
    """
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, dict):
        raise DecisionRerankError("Decision model returned no answers")
    top = len(DECISION_RERANK_LEVELS) - 1
    scores: list[float] = []
    for index in range(count):
        answer = answers.get(decision_rerank_question_id(index))
        value = answer.get("score") if isinstance(answer, dict) else None
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise DecisionRerankError(f"Decision model returned no score for finding {index}")
        position = min(max(float(value), 0.0), float(top))
        scores.append(round(position / top, 4))
    return scores


class DecisionRerankerService:
    """Reranks findings by asking a decision model how relevant each one is to the query."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = DECISION_RERANK_TIMEOUT_SECONDS,
        trace_context: LLMTraceContext | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.trace_context = trace_context

    def rerank(
        self,
        query: str,
        documents: list[DocumentToRerank],
        top_n: int | None = None,
    ) -> list[RerankResult]:
        """Score every finding in one request and return the best `top_n`, most relevant first.

        Provider failures raise `DecisionProviderError`, a malformed answer raises
        `DecisionRerankError`; neither falls back to the original order.
        """
        if not documents:
            return []
        if top_n is None:
            top_n = len(documents)

        body = build_decision_rerank_body(model=self.model, query=query, documents=documents)
        payload = call_decision_model(
            base_url=self.base_url,
            api_key=self.api_key,
            body=body,
            timeout=self.timeout,
            trace_context=self.trace_context,
        )
        scores = read_decision_rerank_scores(payload, len(documents))

        # sorted() is stable, so tied findings keep their retrieval order.
        order = sorted(range(len(documents)), key=lambda index: -scores[index])
        return [
            RerankResult(
                id=documents[index].id,
                text=documents[index].text,
                original_score=documents[index].score,
                relevance_score=scores[index],
                metadata=documents[index].metadata,
            )
            for index in order[: max(min(top_n, len(documents)), 0)]
        ]
