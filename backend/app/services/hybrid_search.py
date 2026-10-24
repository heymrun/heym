"""Hybrid vector search: dense hits fused with BM25 keyword hits by reciprocal rank.

The keyword leg works on existing collections without re-indexing. A backend only has to
answer three questions about its stored text (``LexicalSource``); BM25 scoring and the
fusion are shared, so Qdrant and Postgres (pgvector) rank identically.
"""

import math
import re
from collections import Counter
from typing import Protocol

from app.services.vector_store import HybridSearchResult, LexicalDoc, SearchResult

BM25_K1 = 1.2
BM25_B = 0.75

# Standard reciprocal rank fusion constant (Cormack et al., 2009).
RRF_K = 60

MAX_QUERY_TERMS = 16
LEXICAL_CANDIDATE_LIMIT = 200

# Terms are looked up rarest first until their matches add up to this many documents. A
# term found in half the collection adds almost no BM25 weight but costs a ranking pass
# over every match.
LEXICAL_MATCH_BUDGET = 5000

POOL_MULTIPLIER = 3
MIN_POOL_SIZE = 30
MAX_POOL_SIZE = 200

# Letters and digits only, so "snake_case" and "e-mail" split the way the stores' own
# tokenizers split them.
_TOKEN_PATTERN = re.compile(r"[^\W_]+")


class LexicalSource(Protocol):
    """What a vector store must answer for the keyword leg."""

    def corpus_size(self, collection_name: str) -> int: ...

    def document_frequencies(self, collection_name: str, terms: list[str]) -> dict[str, int]:
        """Number of documents containing each term."""
        ...

    def candidates(
        self,
        collection_name: str,
        terms: list[str],
        limit: int,
        metadata_filter: dict | None,
    ) -> list[LexicalDoc]:
        """Documents containing any of ``terms`` (given rarest first), at most ``limit``."""
        ...


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens of ``text``."""
    return _TOKEN_PATTERN.findall(text.lower())


def query_terms(query: str) -> list[str]:
    """Distinct query tokens in order of appearance, capped at ``MAX_QUERY_TERMS``."""
    return list(dict.fromkeys(tokenize(query)))[:MAX_QUERY_TERMS]


def retrieval_terms(terms: list[str], doc_freq: dict[str, int]) -> list[str]:
    """Rarest terms whose matches fit the budget; the rarest is always kept.

    Terms left out still count when the candidates are scored.
    """
    chosen: list[str] = []
    matches = 0
    for term in sorted((t for t in terms if doc_freq.get(t, 0) > 0), key=doc_freq.__getitem__):
        if chosen and matches + doc_freq[term] > LEXICAL_MATCH_BUDGET:
            break
        chosen.append(term)
        matches += doc_freq[term]
    return chosen


def hybrid_pool_size(limit: int) -> int:
    """How many dense hits to fetch so fusion has more than ``limit`` documents to choose from."""
    return max(limit, min(max(limit * POOL_MULTIPLIER, MIN_POOL_SIZE), MAX_POOL_SIZE))


def bm25_scores(
    terms: list[str],
    docs: list[LexicalDoc],
    doc_freq: dict[str, int],
    corpus_size: int,
) -> dict[str, float]:
    """BM25 score of every document that contains at least one query term.

    Document frequencies and corpus size come from the whole collection. The average
    document length is measured on ``docs``, the only documents whose text is at hand.
    """
    if not terms or not docs:
        return {}

    tokenized = {doc.id: tokenize(doc.text) for doc in docs}
    counts = {doc_id: Counter(tokens) for doc_id, tokens in tokenized.items()}
    average_length = sum(len(tokens) for tokens in tokenized.values()) / len(tokenized) or 1.0
    total = max(corpus_size, len(docs))

    idf: dict[str, float] = {}
    for term in terms:
        observed = sum(1 for doc_counts in counts.values() if term in doc_counts)
        df = min(max(doc_freq.get(term, 0), observed), total)
        idf[term] = math.log(1.0 + (total - df + 0.5) / (df + 0.5))

    scores: dict[str, float] = {}
    for doc_id, doc_counts in counts.items():
        length_norm = 1.0 - BM25_B + BM25_B * len(tokenized[doc_id]) / average_length
        score = 0.0
        for term in terms:
            tf = doc_counts.get(term, 0)
            if tf:
                score += idf[term] * tf * (BM25_K1 + 1.0) / (tf + BM25_K1 * length_norm)
        if score > 0.0:
            scores[doc_id] = score
    return scores


def reciprocal_rank_fusion(rankings: list[list[str]]) -> dict[str, float]:
    """Fuse ranked id lists. 1.0 means first in every list; scores are comparable across runs."""
    ceiling = len(rankings) / (RRF_K + 1)
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (RRF_K + rank)
    return {doc_id: score / ceiling for doc_id, score in fused.items()}


def run_hybrid_search(
    source: LexicalSource,
    collection_name: str,
    query: str,
    dense: list[SearchResult],
    limit: int,
    metadata_filter: dict | None = None,
) -> list[HybridSearchResult]:
    """Fuse ``dense`` vector hits with BM25 hits from ``source`` and keep the best ``limit``.

    Dense hits are scored by BM25 too, so a document the keyword lookup missed but the
    vector search found still earns its keyword rank.
    """
    if limit <= 0:
        return []

    terms = query_terms(query)
    docs: dict[str, LexicalDoc] = {
        hit.id: LexicalDoc(id=hit.id, text=hit.text, metadata=hit.metadata) for hit in dense
    }

    corpus_size = source.corpus_size(collection_name) if terms else 0
    doc_freq: dict[str, int] = {}
    if corpus_size:
        doc_freq = source.document_frequencies(collection_name, terms)
        lookup = retrieval_terms(terms, doc_freq)
        if lookup:
            for doc in source.candidates(
                collection_name, lookup, LEXICAL_CANDIDATE_LIMIT, metadata_filter
            ):
                docs.setdefault(doc.id, doc)

    keyword = bm25_scores(terms, list(docs.values()), doc_freq, corpus_size)
    keyword_ranking = sorted(keyword, key=keyword.__getitem__, reverse=True)
    fused = reciprocal_rank_fusion([[hit.id for hit in dense], keyword_ranking])
    dense_scores = {hit.id: hit.score for hit in dense}

    ordered = sorted(fused, key=fused.__getitem__, reverse=True)[:limit]
    return [
        HybridSearchResult(
            id=doc_id,
            text=docs[doc_id].text,
            score=fused[doc_id],
            metadata=docs[doc_id].metadata,
            vector_score=dense_scores.get(doc_id),
            keyword_score=keyword.get(doc_id),
        )
        for doc_id in ordered
    ]
