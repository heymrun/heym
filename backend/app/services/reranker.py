from __future__ import annotations

import math
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.http_identity import merge_outbound_headers
from app.services.decision_models import (
    build_decision_body,
    call_decision_model,
    read_decision_usage,
)
from app.services.llm_trace import LLMTraceContext, record_llm_trace


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
DECISION_RERANK_MAX_CONCURRENCY = 8
DECISION_RERANK_QUESTION_ID = "relevance"

# Lowest first, as the score primitive requires. Each level names its situation in
# full because the decision model reads the text, not the position.
DECISION_RERANK_LEVELS: tuple[str, ...] = (
    "Irrelevant: the finding has nothing to do with the query.",
    "Tangential: the finding shares the topic but does not help answer the query.",
    "Partially relevant: the finding holds some of the information the query asks for.",
    "Highly relevant: the finding holds most of what is needed to answer the query.",
    "Answers it: the finding directly and fully answers the query.",
)

DECISION_RERANK_INSTRUCTIONS = (
    "How relevant is `finding` to answering `query`? Judge only whether this finding "
    "helps answer the query."
)


class DecisionRerankError(ValueError):
    """Raised when a decision model answer cannot be turned into a relevance score."""


def build_decision_rerank_body(*, model: str, query: str, text: str) -> dict[str, Any]:
    """The request that scores one finding against the query.

    One finding per request: given an array, the model spread a finding's relevance
    onto its neighbours, unsure which text `findings[i]` named.
    """
    return build_decision_body(
        model=model,
        state={"query": query, "finding": text},
        questions=[
            {
                "id": DECISION_RERANK_QUESTION_ID,
                "type": "score",
                "instructions": DECISION_RERANK_INSTRUCTIONS,
                "levels": list(DECISION_RERANK_LEVELS),
            }
        ],
    )


def read_decision_rerank_score(payload: object) -> float:
    """The finding's relevance on the 0-1 scale Cohere uses.

    A score answer is a probability-weighted position between the first and the last
    level, so it maps linearly onto 0-1.
    """
    answers = payload.get("answers") if isinstance(payload, dict) else None
    answer = answers.get(DECISION_RERANK_QUESTION_ID) if isinstance(answers, dict) else None
    value = answer.get("score") if isinstance(answer, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DecisionRerankError("Decision model returned no relevance score")
    top = len(DECISION_RERANK_LEVELS) - 1
    position = min(max(float(value), 0.0), float(top))
    return round(position / top, 4)


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

    def _request(self, query: str, document: DocumentToRerank) -> dict:
        # Untraced on purpose: the whole rerank is recorded as one trace instead.
        return call_decision_model(
            base_url=self.base_url,
            api_key=self.api_key,
            body=build_decision_rerank_body(model=self.model, query=query, text=document.text),
            timeout=self.timeout,
        )

    def rerank(
        self,
        query: str,
        documents: list[DocumentToRerank],
        top_n: int | None = None,
    ) -> list[RerankResult]:
        """Score each finding in its own request, in parallel, and return the best `top_n`.

        The first failure (`DecisionProviderError`, or `DecisionRerankError` for an answer
        without a score) is raised once the requests already running finish; requests not
        yet started are dropped. Nothing falls back to the original order. The rerank is
        recorded as a single trace, failed or not.
        """
        if not documents:
            return []
        if top_n is None:
            top_n = len(documents)

        started = time.monotonic()
        workers = min(len(documents), DECISION_RERANK_MAX_CONCURRENCY)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._request, query, document) for document in documents]
            wait(futures, return_when=FIRST_EXCEPTION)
            for future in futures:
                future.cancel()
        # Leaving the pool waited for the running requests, so every future is settled.

        payloads: list[dict | None] = []
        error: BaseException | None = None
        for future in futures:
            failure = None if future.cancelled() else future.exception()
            if failure is not None and error is None:
                error = failure
            payloads.append(None if future.cancelled() or failure else future.result())

        scores: list[float] = []
        if error is None:
            for index, payload in enumerate(payloads):
                try:
                    scores.append(read_decision_rerank_score(payload))
                except DecisionRerankError as exc:
                    error = DecisionRerankError(f"{exc} for finding {index}")
                    break

        self._record_trace(query, documents, payloads, error, started)
        if error is not None:
            raise error

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

    def _record_trace(
        self,
        query: str,
        documents: list[DocumentToRerank],
        payloads: list[dict | None],
        error: BaseException | None,
        started: float,
    ) -> None:
        """One trace for the whole rerank: every finding's answer, with summed token usage."""
        if self.trace_context is None:
            return
        answers: list[dict[str, Any]] = []
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        for index, payload in enumerate(payloads):
            if payload is None:
                answers.append({"finding": index, "answer": None})
                continue
            found = payload.get("answers")
            answer = found.get(DECISION_RERANK_QUESTION_ID) if isinstance(found, dict) else None
            answers.append({"finding": index, "answer": answer})
            prompt, completion = read_decision_usage(payload)
            if prompt is not None:
                prompt_tokens = (prompt_tokens or 0) + prompt
            if completion is not None:
                completion_tokens = (completion_tokens or 0) + completion
        reported_model = next(
            (str(p["model"]) for p in payloads if p is not None and p.get("model")), self.model
        )
        record_llm_trace(
            self.trace_context,
            request_type="decision.systemone",
            request={
                "model": self.model,
                "rerank": {
                    "query": query,
                    "findings": [document.text for document in documents],
                    "question": {
                        "instructions": DECISION_RERANK_INSTRUCTIONS,
                        "levels": list(DECISION_RERANK_LEVELS),
                    },
                    "requests": len(documents),
                },
            },
            response={"model": reported_model, "answers": answers},
            model=reported_model,
            provider="decision",
            error=str(error) if error is not None else None,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=(
                prompt_tokens + completion_tokens
                if prompt_tokens is not None and completion_tokens is not None
                else None
            ),
            elapsed_ms=(time.monotonic() - started) * 1000,
        )
