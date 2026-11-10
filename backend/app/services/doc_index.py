"""
Doc Index Service for Heym platform documentation.

Provides keyword search over docs content with bounded, relevant markdown excerpts.
No embedding or vector store - simple text matching.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_DOCS_DIR = _PROJECT_ROOT / "frontend" / "src" / "docs" / "content"

TOP_K = 5
# Leave room below dashboard chat's 96k-character tool-result limit, including JSON escaping.
MAX_SEARCH_RESULT_CHARS = 80_000

_NODE_DOC_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _get_docs_dir(docs_dir_override: str | None) -> Path:
    """Resolve docs directory path."""
    if docs_dir_override and docs_dir_override.strip():
        return Path(docs_dir_override.strip()).resolve()
    return _DEFAULT_DOCS_DIR


def read_node_doc(slug: str | None, docs_dir_override: str | None = None) -> str | None:
    """Return the markdown of ``nodes/<slug>.md`` from the docs, or None when it is not there.

    The slug comes from the client, so only plain lowercase slugs are accepted and the file
    must sit directly under the docs ``nodes`` folder.
    """
    if not slug or not _NODE_DOC_SLUG.fullmatch(slug):
        return None
    if docs_dir_override is None:
        from app.config import settings

        docs_dir_override = getattr(settings, "docs_dir", "")
    nodes_dir = (_get_docs_dir(docs_dir_override) / "nodes").resolve()
    path = (nodes_dir / f"{slug}.md").resolve()
    if path.parent != nodes_dir:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _extract_title(content: str) -> str:
    """Extract H1 title from markdown content."""
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _load_docs(docs_dir: Path) -> list[dict[str, Any]]:
    """Load all markdown docs with full content."""
    docs: list[dict[str, Any]] = []
    if not docs_dir.exists():
        logger.warning("Docs directory does not exist: %s", docs_dir)
        return docs

    for md_path in sorted(docs_dir.rglob("*.md")):
        try:
            raw = md_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to read %s: %s", md_path, e)
            continue

        rel = md_path.relative_to(docs_dir)
        category = rel.parent.as_posix()
        slug = md_path.stem
        path = f"/docs/{category}/{slug}"
        title = _extract_title(raw)

        docs.append(
            {
                "path": path,
                "title": title or slug,
                "content": raw,
                "search_text": f"{title} {slug} {category} {raw}".lower(),
            }
        )

    return docs


def _keyword_score(query: str, doc: dict[str, Any]) -> int:
    """Match whole terms and prefer titles over incidental mentions in a large reference."""
    terms = [term for term in re.findall(r"[\w-]+", query.lower()) if len(term) > 1]
    title = doc.get("title", "").lower()
    search_text = doc.get("search_text", "").lower()
    score = 0
    for term in terms:
        pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
        score += bool(re.search(pattern, search_text))
        score += 5 * bool(re.search(pattern, title))
    return score


def _encoded_length(text: str) -> int:
    """Count characters as serialized to the model, excluding surrounding JSON quotes."""
    return len(json.dumps(text)) - 2


def _excerpt_content(query: str, content: str, max_chars: int) -> str:
    """Keep the introduction and best matching passages within an escaped JSON budget."""
    if _encoded_length(content) <= max_chars:
        return content

    passages: list[str] = []
    start = 0
    while start < len(content):
        end = min(start + 2000, len(content))
        if end < len(content):
            # Prefer a line boundary and avoid splitting query terms across passages.
            boundary = content.rfind("\n", start + 1000, end)
            whitespace = re.search(r"\s", content[end : end + 100])
            if boundary >= 0:
                end = boundary + 1
            elif whitespace:
                end += whitespace.end()
        passages.append(content[start:end])
        start = end

    ranked = sorted(
        range(len(passages)),
        key=lambda index: (
            index == 0,
            _keyword_score(query, {"search_text": passages[index]}),
        ),
        reverse=True,
    )
    separator = "\n\n[... documentation passages omitted ...]\n\n"
    selected: dict[int, str] = {}
    remaining = max_chars
    for index in ranked:
        available = remaining - (_encoded_length(separator) if selected else 0)
        if available <= 0:
            break
        passage = passages[index]
        while _encoded_length(passage) > available:
            passage = passage[: len(passage) * available // _encoded_length(passage)]
        if passage:
            selected[index] = passage
            remaining = available - _encoded_length(passage)
    return separator.join(selected[index] for index in sorted(selected))


def _bound_search_results(
    query: str, results: list[dict[str, Any]], max_chars: int
) -> list[dict[str, Any]]:
    """Share the serialized result budget across docs without discarding their evidence."""
    if len(json.dumps({"results": results})) <= max_chars:
        return results
    bounded = [
        {**doc, "content": "", "excerpted": True, "original_length": len(doc["content"])}
        for doc in results
    ]
    remaining = max_chars - len(json.dumps({"results": bounded}))
    # Small docs stay whole; their unused allowance goes to longer pages.
    indices = sorted(
        range(len(results)), key=lambda index: _encoded_length(results[index]["content"])
    )
    for position, index in enumerate(indices):
        content = results[index]["content"]
        excerpt = _excerpt_content(query, content, remaining // (len(indices) - position))
        bounded[index]["content"] = excerpt
        if excerpt == content:
            bounded[index].pop("excerpted")
            bounded[index].pop("original_length")
        remaining -= _encoded_length(excerpt)
    return bounded


class DocIndexService:
    """Keyword-based documentation search with a bounded markdown result payload."""

    _instance: "DocIndexService | None" = None

    def __init__(self, docs_dir: Path | None = None) -> None:
        self._docs_dir = docs_dir or _DEFAULT_DOCS_DIR
        self._docs: list[dict[str, Any]] = []
        self._loaded = False

    @classmethod
    def get_instance(cls, docs_dir_override: str | None = None) -> "DocIndexService":
        """Get singleton instance."""
        if cls._instance is None:
            from app.config import settings

            override = (
                docs_dir_override
                if docs_dir_override is not None
                else getattr(settings, "docs_dir", "")
            )
            docs_path = _get_docs_dir(override)
            cls._instance = cls(docs_path)
        return cls._instance

    def _ensure_loaded(self) -> None:
        """Load docs on first search."""
        if self._loaded:
            return
        self._docs = _load_docs(self._docs_dir)
        self._loaded = True
        logger.info("Doc index loaded: %d docs from %s", len(self._docs), self._docs_dir)

    def search(
        self,
        query: str,
        top_k: int = TOP_K,
        max_chars: int = MAX_SEARCH_RESULT_CHARS,
    ) -> list[dict[str, Any]]:
        """
        Search documentation by keyword, excerpting long results to fit the model context.

        Returns list of {title, path, content} for up to top_k distinct docs.
        """
        if not query or not query.strip():
            return []

        self._ensure_loaded()

        if not self._docs:
            return []

        scored = [(doc, _keyword_score(query.strip(), doc)) for doc in self._docs]
        scored = [(d, s) for d, s in scored if s > 0]
        scored.sort(key=lambda x: x[1], reverse=True)

        seen_paths: set[str] = set()
        results: list[dict[str, Any]] = []
        for doc, _ in scored:
            path = doc["path"]
            if path in seen_paths:
                continue
            seen_paths.add(path)
            results.append(
                {
                    "title": doc["title"],
                    "path": path,
                    "content": doc["content"],
                }
            )
            if len(results) >= top_k:
                break

        return _bound_search_results(query, results, max_chars)
